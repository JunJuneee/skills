"""consolidate: re-read a domain's pages a few at a time and tidy them,
with no new source (the wiki's "dreaming" step). Python 3.9, stdlib only.

It merges pages about the same thing, settles facts that disagree (the
newer src date wins and the older src lines stay; an undecidable one is
only reported) and compresses bloated sections. It never deletes a fact:
every src line (id, date) and every https URL or `path / id` of the group
is still there afterwards. It reuses absorb's machinery: worktree, the
isolated runner, verify's page checks, deferral, merge and the caches.

One run, under the absorb lock (common.wiki_lock, so never next to absorb):

  1. domains.json guard (owners_unset, work_terms_unset). While foreign
     user rules exist personal pages are no candidates at all (they would
     take the run's group slots only to refuse): a warning
     user_rules_unisolated:<n>, and a failed run with that reason when
     nothing else is left to run.
  2. candidate groups (Python, no LLM) per domain, union-find in this
     order, each group at most max_pages_per_group pages:
       1 same subject: same type and a title/alias equal under NFKC +
         casefold
       2 same project: project pages sharing a repo; notes/ pages named
         after a project
       3 bloated page: main part over 12KB or a section over 40 list items
         (alone it is a group too)
       4 stale page: to fill up to max_groups_per_run, pages changed since
         their last consolidation, the longest unconsolidated first
     Left out: pages with uncommitted changes in main, pages a pending
     manual:<page> source points at (prepare.manual_items diffs them
     since..base_sha), pages that would fail verify even unchanged, root
     and generated files and _drafts/. decisions/* and notes/worklog-*.md
     are read-only context only. A group whose fingerprint (sorted
     path:blob) last ended with no change is not sent again
     (.state/consolidate-state.json).
  3. a fresh .absorb-wt at main HEAD; per group one isolated `claude -p`
     with absorb's flags minus --add-dir (absorb.build_argv with no
     staging folder), cwd .absorb-wt/<domain>/, the prompt's safety header
     first.
  4. per group: outside_group on the LLM's own changes; then Python
     handles merged_into (a loser linked from a place Python must not edit
     is kept: merge_blocked_locked_link, settled before any edit; else its
     names move to the survivor's aliases (that page only) and, less the
     names another page holds, to sources.json mention groups, links to it
     are rewritten domain-wide and it is deleted); then src_lost, src_added,
     link_lost, shrunk_too_much and page_identity_changed before verify's
     page checks, then promotion_regressed. A failed group is reset in the
     worktree and kept redacted under .state/failed/<run_id>/consolidate-<n>/.
     One commit per group: "wiki: consolidate <run_id> 묶음 <n> (<domain>)".
  5. absorb.settle_and_merge: deferral, the stored drafts with the merged
     links rewritten (stored before the merge, put back if it fails), root
     files reassembled from them, index.md, a log.md line, the whole-tree
     secret scan and merge --ff-only.
  6. after the merge: mention groups saved, caches and the rules file
     refreshed (absorb.refresh_caches_and_rules, the cache's pending block
     carried over), fingerprints recorded.

Modes: plan (candidates and counts only; no lock, no LLM, no worktree),
dry_run (LLM and checks; the redacted diff goes to
.state/consolidate/<run_id>/preview.diff, the newest 5 kept, nothing is
merged or recorded), normal. The session, --json and Slack get status,
reason codes and counts (public_report); page paths, conflicts and
problems go only to the mode's report file (0600):
.state/last-consolidate-report.json for normal runs,
last-consolidate-preview.json and last-consolidate-plan.json for the
others, so a look ahead never replaces the last real run's conflict list.
.state/last-consolidate (status) is written by normal runs only.

Scheduling (schedule.py): the existing launchd job's tick runs this when
absorb is not due and consolidate_due allows it (the 7-day rule, today's
absorb ok or empty), through schedule.run_consolidate, which keeps
.state/consolidate-ledger.json and sends the Slack line. report["command"]
is "consolidate" so the CLI and notify tell its report from absorb's.

The LLM step is injectable (`runner`) so tests never call a real model.
"""

import collections
import datetime
import hashlib
import os
import re
import sys
import unicodedata

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import absorb  # noqa: E402
import common  # noqa: E402
import prepare  # noqa: E402
import redact  # noqa: E402
import verify  # noqa: E402

PROMPT_TEMPLATE = "consolidate_prompt.md"
STATE_FILE = "consolidate-state.json"
REPORT_FILE = "last-consolidate-report.json"
LAST_FILE = "last-consolidate"
RUNNING_FILE = "consolidate-running.json"
PREVIEW_DIR = "consolidate"
PREVIEW_FILE = "preview.diff"

# First values (plan "후보 묶음 고르기"); settings.json consolidate.* overrides.
BLOAT_MAIN_BYTES = 12 * 1024
BLOAT_SECTION_ITEMS = 40
MAX_CONTEXT_PAGES = 6
STATE_KEEP_GROUPS = 500
MIN_STEM = 3
MIN_TITLE = 2

MODE_PLAN = "plan"
MODE_DRY_RUN = "dry_run"
MODE_NORMAL = "normal"
MODES = (MODE_PLAN, MODE_DRY_RUN, MODE_NORMAL)
REPORT_FILES = {MODE_NORMAL: REPORT_FILE, MODE_DRY_RUN: "last-consolidate-preview.json",
                MODE_PLAN: "last-consolidate-plan.json"}
PREVIEW_KEEP_RUNS = absorb.FAILED_KEEP_RUNS

SIGNAL_SUBJECT = 1
SIGNAL_PROJECT = 2
SIGNAL_BLOATED = 3
SIGNAL_STALE = 4
SIGNAL_CODES = {SIGNAL_SUBJECT: "same_subject", SIGNAL_PROJECT: "same_project",
                SIGNAL_BLOATED: "bloated", SIGNAL_STALE: "stale"}
SIGNAL_TEXT = {SIGNAL_SUBJECT: "같은 대상 의심", SIGNAL_PROJECT: "같은 프로젝트",
               SIGNAL_BLOATED: "비대한 페이지", SIGNAL_STALE: "오래 정리 안 한 페이지"}

RESULT_CHANGED = "changed"
RESULT_NO_CHANGE = "no_change"

STATUS_OK = absorb.STATUS_OK
STATUS_EMPTY = absorb.STATUS_EMPTY
STATUS_FAILED = absorb.STATUS_FAILED
STATUS_HELD = absorb.STATUS_HELD

_WORKLOG_RE = re.compile(r"^notes/worklog-[^/]*\.md$")

# --json-schema of the LLM's result. merged_into is a list of
# {page, into} objects, not the {loser: survivor} map of the plan text: the
# same additionalProperties-false shape as absorb's schema (a free-form map
# leaves its keys unchecked).
OUTPUT_SCHEMA = collections.OrderedDict([
    ("type", "object"),
    ("additionalProperties", False),
    ("properties", collections.OrderedDict([
        ("pages", {"type": "array", "items": {"type": "string"}}),
        ("merged_into", {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"page": {"type": "string"}, "into": {"type": "string"}},
            "required": ["page", "into"]}}),
        ("conflicts", {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"pages": {"type": "array", "items": {"type": "string"}},
                           "fact": {"type": "string"}},
            "required": ["pages", "fact"]}}),
        ("notes", {"type": "string"}),
    ])),
    ("required", ["pages", "merged_into", "conflicts", "notes"]),
])

MAX_CONFLICTS = 50
MAX_FACT_CHARS = 500


# ---------------------------------------------------------------------------
# Settings and state
# ---------------------------------------------------------------------------

def consolidate_settings(settings):
    """settings.json consolidate block (validated by common.validate_settings)
    with the bloat thresholds filled in."""
    cfg = dict((settings or {}).get("consolidate") or
               common.SETTINGS_DEFAULTS["consolidate"])
    cfg.setdefault("bloat_main_bytes", BLOAT_MAIN_BYTES)
    cfg.setdefault("bloat_section_items", BLOAT_SECTION_ITEMS)
    return cfg


def state_path(root):
    return os.path.join(common.state_dir(root), STATE_FILE)


def load_state(root):
    """.state/consolidate-state.json: {groups: {fingerprint: {result,
    run_id, at}}, pages: {path: {blob, run_id, at}}}; empty when missing
    or unreadable."""
    data = None
    try:
        data = common.load_json_file(state_path(root))
    except common.WikiError:
        data = None
    if not isinstance(data, dict):
        data = collections.OrderedDict()
    for key in ("groups", "pages"):
        if not isinstance(data.get(key), dict):
            data[key] = collections.OrderedDict()
    data["version"] = 1
    return data


def save_state(root, data):
    groups = data["groups"]
    if len(groups) > STATE_KEEP_GROUPS:
        ordered = sorted(groups.items(), key=lambda item: str((item[1] or {}).get("at") or ""))
        data["groups"] = collections.OrderedDict(ordered[-STATE_KEEP_GROUPS:])
    common.ensure_private_dir(common.state_dir(root))
    common.atomic_write_text(state_path(root), common.dumps_json(data), mode=0o600)


def fingerprint(blobs):
    """sha256 of a group's sorted 'path blob' lines."""
    lines = ["%s %s" % (path, blobs[path]) for path in sorted(blobs)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def head_blobs(root, sha, domain):
    """{path: blob sha} of the domain's tracked files at commit sha."""
    out = common.wiki_git(root, ["ls-tree", "-r", "-z", sha, "--", domain + "/"]).stdout
    blobs = {}
    for entry in out.decode("utf-8", "surrogateescape").split("\0"):
        meta, sep, path = entry.partition("\t")
        parts = meta.split()
        if sep and len(parts) == 3 and parts[1] == "blob":
            blobs[path] = parts[2]
    return blobs


# ---------------------------------------------------------------------------
# Candidate groups (plan "후보 묶음 고르기")
# ---------------------------------------------------------------------------

Entry = collections.namedtuple("Entry", "path rel fm title aliases type text blob readonly")


def _rel(path, domain):
    return path[len(domain) + 1:]


def _is_readonly(rel, fm):
    return (fm.get("type") == "decision" or rel.startswith("decisions/")
            or bool(_WORKLOG_RE.match(rel)))


def _stem(rel):
    return rel.rsplit("/", 1)[-1][:-3]


def _fold_list(values):
    return [verify.fold(v) for v in values or [] if isinstance(v, str) and v.strip()]


def pending_manual_pages(sources_data):
    pages = set()
    for entry in ((sources_data or {}).get("sources") or {}).values():
        if (isinstance(entry, dict) and entry.get("kind") == prepare.KIND_MANUAL
                and entry.get("status") == prepare.STATUS_PENDING and entry.get("page")):
            pages.add(entry["page"])
    return pages


def dirty_set(root):
    return set(path for _status, path in prepare.dirty_paths(root))


def _bloat(text, cfg):
    """[why] when the page is bloated (signal 3), else []."""
    why = []
    size = verify.main_bytes(text)
    if size > cfg["bloat_main_bytes"]:
        why.append("main_bytes:%d" % size)
    for heading, count in verify.section_item_counts(text).items():
        if count > cfg["bloat_section_items"]:
            why.append("section_items:%s:%d" % (heading, count))
    return why


def domain_catalog(root, domain, base, domains_cfg, sources_data, dirty, manual):
    """(entries, frozen, excluded) for one domain of main's working tree.

    entries: pages consolidate may group (writable) or show (readonly).
    frozen: {path: reason} of pages Python must not edit either (link
    rewrites): uncommitted, a pending manual source, untracked, or a page
    verify would fail even unchanged (unknown or withdrawn src, bad
    frontmatter, '## 내 메모' hidden by an open fence, a secret, a personal
    work_terms hit). excluded counts them by reason."""
    blobs = head_blobs(root, base, domain)
    index = verify.SourceIndex((sources_data or {}).get("sources"), [], domain)
    allow = verify.scan_allow(root, domains_cfg)
    terms = verify.Terms(domains_cfg.get("work_terms", []))
    other = [d for d in common.DOMAINS if d != domain]
    other_names = set()
    for name in other:
        other_names |= verify.page_basenames(root, name)
    entries = []
    frozen = collections.OrderedDict()
    excluded = collections.OrderedDict()

    def drop(path, reason):
        frozen[path] = reason
        excluded[reason] = excluded.get(reason, 0) + 1

    for path in verify.iter_page_files(root, domain):
        if path not in blobs:
            drop(path, "untracked")
            continue
        if path in dirty:
            drop(path, "dirty")
            continue
        if path in manual:
            drop(path, "manual_pending")
            continue
        try:
            text = verify.read_text(os.path.join(root, path))
        except (IOError, OSError, UnicodeDecodeError):
            drop(path, "page_unreadable")
            continue
        if verify.notes_hidden(text):
            drop(path, "my_notes_unlocatable")
            continue
        problems = []
        verify._check_page(root, base, "M", path, domain, index, other, allow, terms, problems,
                           other_names)
        if problems:
            drop(path, problems[0].split(":", 1)[0])
            continue
        fm, _err, _body, _nl = verify.page_split(text)
        rel = _rel(path, domain)
        aliases = [a for a in fm.get("aliases") or [] if isinstance(a, str) and a.strip()] \
            if isinstance(fm.get("aliases"), list) else []
        entries.append(Entry(path, rel, fm, fm.get("title"), aliases, fm.get("type"), text,
                             blobs[path], _is_readonly(rel, fm)))
    return entries, frozen, excluded


class _UnionFind(object):
    """Union-find over page paths that never builds a set larger than cap."""

    def __init__(self, paths, cap):
        self.parent = dict((path, path) for path in paths)
        self.size = dict((path, 1) for path in paths)
        self.signal = {}
        self.cap = cap

    def find(self, key):
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, a, b, signal):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            self.signal[ra] = min(self.signal.get(ra, signal), signal)
            return True
        if self.size[ra] + self.size[rb] > self.cap:
            return False
        if rb < ra:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        self.signal[ra] = min(self.signal.get(ra, signal), self.signal.get(rb, signal), signal)
        return True


def _subject_pairs(writable):
    """Signal 1: same type and a shared folded title/alias."""
    by_key = collections.OrderedDict()
    for entry in writable:
        for name in set(_fold_list([entry.title] + entry.aliases)):
            by_key.setdefault((entry.type, name), []).append(entry.path)
    pairs = []
    for key in sorted(by_key):
        paths = sorted(set(by_key[key]))
        pairs += [(paths[0], other) for other in paths[1:]]
    return pairs


def _project_pairs(writable):
    """Signal 2: project pages sharing a repo; a notes/ page whose file name
    or title starts with a project's."""
    projects = [e for e in writable if e.type == "project"]
    by_repo = collections.OrderedDict()
    for entry in projects:
        for repo in set(_fold_list(entry.fm.get("repos") if isinstance(entry.fm.get("repos"), list)
                                   else [])):
            by_repo.setdefault(repo, []).append(entry.path)
    pairs = []
    for repo in sorted(by_repo):
        paths = sorted(set(by_repo[repo]))
        pairs += [(paths[0], other) for other in paths[1:]]
    notes = [e for e in writable if e.rel.startswith("notes/")]
    for project in sorted(projects, key=lambda e: e.path):
        stem = verify.fold(_stem(project.rel))
        title = verify.fold(project.title)
        for note in sorted(notes, key=lambda e: e.path):
            note_stem = verify.fold(_stem(note.rel))
            by_stem = len(stem) >= MIN_STEM and (note_stem == stem
                                                 or note_stem.startswith(stem + "-"))
            by_title = (len(title) >= MIN_TITLE
                        and verify.fold(note.title).startswith(title))
            if by_stem or by_title:
                pairs.append((project.path, note.path))
    return pairs


def _context_for(members, readonly):
    """Read-only pages (decisions, worklog notes) the group links to or that
    link to the group, newest file names first, at most MAX_CONTEXT_PAGES."""
    mains = [verify.before_notes(e.text) for e in members]
    paths = [e.path for e in members]
    picked = []
    for entry in sorted(readonly, key=lambda e: e.path, reverse=True):
        main = verify.before_notes(entry.text)
        if (any(verify.links_to(text, entry.path) for text in mains)
                or any(verify.links_to(main, path) for path in paths)):
            picked.append(entry.path)
        if len(picked) >= MAX_CONTEXT_PAGES:
            break
    return sorted(picked)


def _last_at(state, path):
    return str(((state.get("pages") or {}).get(path) or {}).get("at") or "")


def _changed_since_consolidated(state, entry):
    record = (state.get("pages") or {}).get(entry.path)
    return not isinstance(record, dict) or record.get("blob") != entry.blob


def _new_group(domain, signal, members, why, context):
    group = collections.OrderedDict()
    group["group_id"] = 0
    group["domain"] = domain
    group["signal"] = signal
    group["signal_code"] = SIGNAL_CODES[signal]
    group["pages"] = sorted(e.path for e in members)
    group["why"] = collections.OrderedDict((e.path, list(why.get(e.path) or [])) for e in
                                           sorted(members, key=lambda e: e.path))
    group["context"] = context
    group["blobs"] = collections.OrderedDict((e.path, e.blob) for e in
                                             sorted(members, key=lambda e: e.path))
    group["fingerprint"] = fingerprint(group["blobs"])
    return group


def domain_groups(domain, entries, cfg, state):
    """Signal 1-3 groups of one domain, in plan order, plus the stale
    pages left for signal 4 (sorted, oldest consolidation first)."""
    writable = [e for e in entries if not e.readonly]
    readonly = [e for e in entries if e.readonly]
    by_path = dict((e.path, e) for e in writable)
    finder = _UnionFind(sorted(by_path), cfg["max_pages_per_group"])
    why = collections.OrderedDict((path, []) for path in sorted(by_path))
    for signal, pairs in ((SIGNAL_SUBJECT, _subject_pairs(writable)),
                          (SIGNAL_PROJECT, _project_pairs(writable))):
        for a, b in pairs:
            if finder.union(a, b, signal):
                for path in (a, b):
                    if SIGNAL_CODES[signal] not in why[path]:
                        why[path].append(SIGNAL_CODES[signal])
    bloated = set()
    for entry in writable:
        found = _bloat(entry.text, cfg)
        if found:
            bloated.add(entry.path)
            why[entry.path] += ["bloated:%s" % item for item in found]
    components = collections.OrderedDict()
    for path in sorted(by_path):
        components.setdefault(finder.find(path), []).append(path)
    groups = []
    for root_key, paths in components.items():
        signal = finder.signal.get(root_key)
        if signal is None:
            if not set(paths) & bloated:
                continue
            signal = SIGNAL_BLOATED
        members = [by_path[path] for path in paths]
        groups.append(_new_group(domain, signal, members, why, _context_for(members, readonly)))
    grouped = set(path for group in groups for path in group["pages"])
    stale = sorted((e for e in writable
                    if e.path not in grouped and _changed_since_consolidated(state, e)),
                   key=lambda e: (_last_at(state, e.path), e.path))
    return groups, stale, readonly


def select_groups(root, settings, domains_cfg, sources_data, state, base, domain=None,
                  max_groups=None, refuse=()):
    """Candidate groups of one run (no LLM). Returns an OrderedDict with
    groups (numbered 1..n in run order), skipped_unchanged, excluded
    {reason: n}, frozen {domain: {path: reason}}, pages (writable pages
    considered) and refused: candidates of the domains in refuse (personal
    while foreign user rules exist), which take no group slot (at most the
    run's limit is counted)."""
    cfg = consolidate_settings(settings)
    limit = cfg["max_groups_per_run"] if max_groups is None else max(0, int(max_groups))
    dirty = dirty_set(root)
    manual = pending_manual_pages(sources_data)
    found = []
    stale = []
    readonly = {}
    excluded = collections.OrderedDict()
    frozen = collections.OrderedDict()
    pages = 0
    domains = [domain] if domain else list(common.DOMAINS)
    for name in domains:
        entries, held, dropped = domain_catalog(root, name, base, domains_cfg, sources_data,
                                                dirty, manual)
        frozen[name] = held
        for reason, count in dropped.items():
            excluded[reason] = excluded.get(reason, 0) + count
        pages += len([e for e in entries if not e.readonly])
        groups, left, ro = domain_groups(name, entries, cfg, state)
        found += groups
        stale += [(name, entry) for entry in left]
        readonly[name] = ro
    found.sort(key=lambda g: (g["signal"], min(_last_at(state, p) for p in g["pages"]),
                              g["domain"], g["pages"][0]))
    skipped = 0
    refused = 0
    chosen = []
    for group in found:
        if len(chosen) >= limit:
            break
        record = state["groups"].get(group["fingerprint"])
        if isinstance(record, dict) and record.get("result") == RESULT_NO_CHANGE:
            skipped += 1
            continue
        if group["domain"] in refuse:
            refused += 1
            continue
        chosen.append(group)
    taken = set(path for group in chosen for path in group["pages"])
    stale.sort(key=lambda item: (_last_at(state, item[1].path), item[0], item[1].path))
    for name, entry in stale:
        if len(chosen) >= limit:
            break
        if entry.path in taken:
            continue
        group = _new_group(name, SIGNAL_STALE, [entry], {}, _context_for([entry],
                                                                         readonly[name]))
        record = state["groups"].get(group["fingerprint"])
        if isinstance(record, dict) and record.get("result") == RESULT_NO_CHANGE:
            skipped += 1
            continue
        if name in refuse:
            refused += 1
            continue
        chosen.append(group)
        taken.add(entry.path)
    for number, group in enumerate(chosen, 1):
        group["group_id"] = number
    out = collections.OrderedDict()
    out["groups"] = chosen
    out["skipped_unchanged"] = skipped
    out["excluded"] = excluded
    out["frozen"] = frozen
    out["pages"] = pages
    out["refused"] = min(refused, limit)
    return out


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_WHY_TEXT = {"same_subject": "같은 대상 의심", "same_project": "같은 프로젝트"}


def _why_text(codes):
    parts = []
    for code in codes:
        if code in _WHY_TEXT:
            parts.append(_WHY_TEXT[code])
        elif code.startswith("bloated:main_bytes:"):
            parts.append("본문 %dKB" % (int(code.rsplit(":", 1)[1]) // 1024))
        elif code.startswith("bloated:section_items:"):
            # The count only: a heading is page text, and page text never
            # enters the instruction part of the prompt (the safety header
            # calls page bodies data). The LLM reads the page itself.
            parts.append("섹션 하나에 %s항목" % code.rsplit(":", 1)[1])
    return " · ".join(parts)


def _page_line(path, domain, why=None):
    line = "- `%s` (현재 폴더 기준 `%s`)" % (path, _rel(path, domain))
    text = _why_text(why or [])
    return line + (": " + text if text else "")


def render_prompt(template, schema_md, group, cwd, today, min_keep_ratio):
    domain = group["domain"]
    values = {
        "DOMAIN": domain,
        "OTHER_DOMAIN": [d for d in common.DOMAINS if d != domain][0],
        "CWD": cwd,
        "TODAY": today,
        "REASON": SIGNAL_TEXT[group["signal"]],
        "PAGES": "\n".join(_page_line(path, domain, group["why"].get(path))
                           for path in group["pages"]),
        "CONTEXT": "\n".join(_page_line(path, domain) for path in group["context"]) or "(없음)",
        "MIN_KEEP": str(int(round(min_keep_ratio * 100))),
        "SCHEMA": schema_md.strip(),
    }
    text = template
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, value)
    return text


# ---------------------------------------------------------------------------
# The LLM's result
# ---------------------------------------------------------------------------

def resolve_page(value, wt, domain):
    """A page path from the LLM as a wiki-relative .md path, or None. The
    LLM's cwd is <wt>/<domain>, so a relative path without the domain
    prefix is read from there (verify.normalize_output reads from wt)."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = unicodedata.normalize("NFC", value.strip())
    wt_real = os.path.realpath(wt)
    if os.path.isabs(value):
        full = value
    elif value == domain or value.startswith(domain + "/"):
        full = os.path.join(wt_real, value)
    else:
        full = os.path.join(wt_real, domain, value)
    if not full.endswith(".md"):
        full += ".md"
    real = os.path.realpath(full)
    if not real.startswith(wt_real + os.sep):
        return None
    return os.path.relpath(real, wt_real).replace(os.sep, "/")


def normalize_output(data, wt, domain):
    """Validate and normalize the structured result. Raises BatchFailure
    (llm_output_invalid) on a bad shape. merged_into also takes the
    plan's {loser: survivor} map."""
    if not isinstance(data, dict):
        raise verify.BatchFailure(["llm_output_invalid:not an object"])
    merged = data.get("merged_into", [])
    if isinstance(merged, dict):
        merged = [{"page": key, "into": value} for key, value in merged.items()]
    for key, value in (("pages", data.get("pages", [])), ("merged_into", merged),
                       ("conflicts", data.get("conflicts", []))):
        if not isinstance(value, list):
            raise verify.BatchFailure(["llm_output_invalid:%s" % key])
    pages = [p for p in (resolve_page(v, wt, domain) for v in data.get("pages") or []) if p]
    pairs = []
    for item in merged:
        if not isinstance(item, dict):
            raise verify.BatchFailure(["llm_output_invalid:merged_into"])
        pairs.append((resolve_page(item.get("page"), wt, domain),
                      resolve_page(item.get("into"), wt, domain)))
    conflicts = []
    for item in (data.get("conflicts") or [])[:MAX_CONFLICTS]:
        if not isinstance(item, dict):
            continue
        fact = item.get("fact") if isinstance(item.get("fact"), str) else ""
        paths = [p for p in (resolve_page(v, wt, domain) for v in item.get("pages") or [])
                 if p] if isinstance(item.get("pages"), list) else []
        conflicts.append({"pages": paths, "fact": fact.strip()[:MAX_FACT_CHARS]})
    notes = data.get("notes") if isinstance(data.get("notes"), str) else ""
    return {"pages": pages, "merged_into": pairs, "conflicts": conflicts, "notes": notes[:2000]}


# ---------------------------------------------------------------------------
# Measures before and after (verify helpers)
# ---------------------------------------------------------------------------

def _identity(fm):
    if not isinstance(fm, dict):
        return None
    lists = {}
    for key in ("aliases", "repos"):
        value = fm.get(key)
        lists[key] = set(_fold_list(value if isinstance(value, list) else []))
    return {"type": fm.get("type"), "domain": fm.get("domain"), "title": fm.get("title"),
            "aliases": lists["aliases"], "repos": lists["repos"]}


def measure(text):
    """What a page must keep: src pairs, links, main-part bytes, identity."""
    if text is None:
        return {"pairs": set(), "links": set(), "bytes": 0, "identity": None, "text": None}
    fm, err, _body, _nl = verify.page_split(text)
    return {"pairs": verify.src_pairs(text), "links": verify.kept_links(text),
            "bytes": verify.main_bytes(text), "identity": _identity(fm if not err else None),
            "text": text}


def _read_or_none(full):
    if not os.path.isfile(full) or os.path.islink(full):
        return None
    return verify.read_text(full)


def _pre_text(wt, pre, path):
    blob = verify.blob_at(wt, pre, path)
    return blob.decode("utf-8") if blob is not None else None


def conservation_problems(wt, pre, before, writable, touched, losers, min_keep_ratio):
    """src_lost / src_added / link_lost / shrunk_too_much /
    page_identity_changed over the group's pages and the pages Python
    edited (before: {path: measure} of the writable pages before the LLM)."""
    scope = sorted(set(writable) | set(touched))
    old = {}
    new = {}
    for path in scope:
        old[path] = before[path] if path in before else measure(_pre_text(wt, pre, path))
        new[path] = measure(_read_or_none(os.path.join(wt, path)))
    problems = []
    pairs_old = set().union(*[m["pairs"] for m in old.values()]) if old else set()
    pairs_new = set().union(*[m["pairs"] for m in new.values()]) if new else set()
    problems += ["src_lost:%s@%s" % pair for pair in sorted(pairs_old - pairs_new)][:10]
    problems += ["src_added:%s@%s" % pair for pair in sorted(pairs_new - pairs_old)][:10]
    links_old = set().union(*[m["links"] for m in old.values()]) if old else set()
    links_new = set().union(*[m["links"] for m in new.values()]) if new else set()
    problems += ["link_lost:%s" % link[:200] for link in sorted(links_old - links_new)][:10]
    size_old = sum(old[p]["bytes"] for p in writable)
    size_new = sum(new[p]["bytes"] for p in writable)
    if size_old and size_new < min_keep_ratio * size_old:
        problems.append("shrunk_too_much:%d/%d" % (size_new, size_old))
    for path in scope:
        was = old[path]["identity"]
        if was is None or path in losers:
            continue
        now = new[path]["identity"]
        if new[path]["text"] is None:
            problems.append("page_identity_changed:%s" % path)
            continue
        if now is None:
            continue  # frontmatter_invalid from verify's page checks
        if (any(now[key] != was[key] for key in ("type", "domain", "title"))
                or not was["aliases"] <= now["aliases"] or not was["repos"] <= now["repos"]):
            problems.append("page_identity_changed:%s" % path)
    return problems


def unpaged_promotions(mentions, merges, pages):
    """Name groups with >= 3 sources and no page (verify.promotions)."""
    return len([1 for _names, _count, page in verify.promotions(mentions, merges, pages)
                if page is None])


# ---------------------------------------------------------------------------
# merged_into (plan "합치기 처리 순서")
# ---------------------------------------------------------------------------

def _root_notes_texts(ctx):
    """'## 내 메모' tails of root now.md/about-me.md, worktree and main."""
    texts = []
    for base in (ctx["wt"], ctx["root"]):
        for name in verify.ROOT_DRAFTS:
            try:
                text = _read_or_none(os.path.join(base, name))
            except (IOError, OSError, UnicodeDecodeError):
                text = None
            if text:
                texts.append(verify.notes_tail(text))
    return texts


_VAULT_GENERATED = ("index.md", "log.md") + tuple(verify.ROOT_DRAFTS)


def _vault_notes(base, domain):
    """Wiki-relative .md files under base outside domain/: the other
    domain's pages and every vault-level note (Obsidian daily notes, inbox
    notes, anything outside the domain folders), none of which a group may
    edit. Dot folders (.git, .state, .absorb-wt, .obsidian) and _drafts/
    are skipped, and so are index.md and log.md (rebuilt, no human links)
    and root now.md/about-me.md (Python rewrites them above '## 내 메모';
    _root_notes_texts checks the rest)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        top = dirpath == base
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                             and d != common.DRAFTS_DIRNAME and not (top and d == domain))
        for name in sorted(filenames):
            if not name.endswith(".md") or name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            if rel not in _VAULT_GENERATED:
                out.append(rel)
    return out


def outside_texts(ctx, domain):
    """[(path, text or None when unreadable)] of _vault_notes in the
    worktree and in main's working copy (untracked and edited notes)."""
    out = []
    for base in (ctx["wt"], ctx["root"]):
        for rel in _vault_notes(base, domain):
            try:
                out.append((rel, _read_or_none(os.path.join(base, rel))))
            except (IOError, OSError, UnicodeDecodeError):
                out.append((rel, None))
    return out


def locked_link(ctx, domain, loser, outside=None):
    """(locked, unique). locked: loser is linked from a place Python must
    not edit: a '## 내 메모' (domain pages, root files), frontmatter, a
    frozen page (worktree or main's working copy), the other domain's
    pages or any other note in the vault (outside_texts; a cross-domain
    link in a '## 내 메모' is allowed and committed), or a bare [[name]]
    link in a domain page while another file shares its name. unique: no
    other .md file in the vault has loser's file name, so a bare [[name]]
    means loser (Obsidian resolves bare names vault-wide)."""
    wt, root = ctx["wt"], ctx["root"]
    frozen = ctx["frozen"].get(domain) or {}
    if outside is None:
        outside = outside_texts(ctx, domain)
    stem = verify.fold(_stem(loser))
    unique = not any(verify.fold(_stem(rel)) == stem for rel, _text in outside)
    for path in verify.iter_page_files(wt, domain):
        if path != loser and verify.fold(_stem(path)) == stem:
            unique = False
    for text in _root_notes_texts(ctx):
        if verify.links_to(text, loser):
            return True, unique
    for _rel, text in outside:
        if text is None or verify.links_to(text, loser):
            return True, unique
    for path in verify.iter_page_files(wt, domain):
        if path == loser:
            continue
        try:
            text = verify.read_text(os.path.join(wt, path))
        except (IOError, OSError, UnicodeDecodeError):
            return True, unique
        fm, _err, body, _nl = verify.page_split(text)
        if path in frozen or verify.notes_hidden(text):
            if verify.links_to(body, loser) or verify.links_to(verify.fm_strings(fm), loser):
                return True, unique
            continue
        if (verify.links_to(verify.notes_tail(text), loser)
                or verify.links_to(verify.fm_strings(fm), loser)):
            return True, unique
        if not unique and any("/" not in t.strip() and verify.link_resolves_to(t, loser)
                              for t in verify.link_targets(body)):
            return True, unique
    for path in frozen:
        try:
            text = _read_or_none(os.path.join(root, path))
        except (IOError, OSError, UnicodeDecodeError):
            return True, unique
        if text and verify.links_to(text, loser):
            return True, unique
    return False, unique


def _union_repos(wt, survivor, loser_fm):
    """A project survivor keeps the loser's repos too (session hooks find
    projects by repo). Returns True when the survivor changed."""
    repos = loser_fm.get("repos") if isinstance(loser_fm.get("repos"), list) else []
    repos = [r for r in repos if isinstance(r, str) and r.strip()]
    if not repos:
        return False
    full = os.path.join(wt, survivor)
    fm, err, body, newline = verify.page_split(verify.read_text(full))
    if fm is None or err:
        return False
    have = fm.get("repos") if isinstance(fm.get("repos"), list) else []
    folded = set(_fold_list(have))
    missing = [r for r in repos if verify.fold(r) not in folded]
    if not missing:
        return False
    fm["repos"] = list(have) + missing
    common.atomic_write_text(full, common.render_page(fm, body, newline))
    return True


def apply_merges(ctx, group, pre, output, before):
    """Validate merged_into and carry it out in the worktree. Returns
    (applied [(loser, survivor, bare)], blocked [loser], touched paths,
    name groups for sources.json). Raises BatchFailure(merge_invalid)."""
    wt = ctx["wt"]
    domain = group["domain"]
    writable = set(group["pages"])
    losers = collections.OrderedDict()
    problems = []
    for loser, into in output["merged_into"]:
        if (not loser or not into or loser == into or loser not in writable
                or into not in writable or losers.get(loser, into) != into):
            problems.append("merge_invalid:%s" % (loser or "?"))
            continue
        losers[loser] = into
    for loser, into in losers.items():
        old = (before.get(loser) or {}).get("identity")
        survivor = (before.get(into) or {}).get("identity")
        text = _read_or_none(os.path.join(wt, loser))
        if (into in losers or text is None or text.strip() or old is None or survivor is None
                or old["type"] != survivor["type"]):
            problems.append("merge_invalid:%s" % loser)
    if problems:
        raise verify.BatchFailure(problems)
    # The vault walk only when there is a merge to check (inbox notes pile up).
    outside = outside_texts(ctx, domain) if losers else []
    # Which merges are refused is settled before any edit. A refused loser
    # comes back from pre with its '## 내 메모' and frontmatter, which may
    # link another loser that looked free while it was empty, so check
    # again until no new merge is refused. Only those merges are refused;
    # the rest of the group goes on (a refused loser's moved text stays).
    blocked, unique = [], {}
    pending = list(losers)
    while True:
        newly = []
        for loser in pending:
            locked, unique[loser] = locked_link(ctx, domain, loser, outside)
            if locked:
                newly.append(loser)
        if not newly:
            break
        for loser in newly:
            common.wiki_git(wt, ["checkout", pre, "--", loser])
        blocked += newly
        pending = [loser for loser in pending if loser not in newly]
    applied = [(loser, losers[loser], unique[loser]) for loser in pending]
    touched, kept_names = set(), []
    allow = ctx["domains"].get("redact_allow", [])
    terms = verify.Terms(ctx["domains"].get("work_terms", []))
    gone = set(pending)
    frozen = ctx["frozen"].get(domain) or {}
    for loser, into, unique in applied:
        loser_text = before[loser]["text"]
        loser_fm = verify.page_split(loser_text)[0] or {}
        aliases = loser_fm.get("aliases") if isinstance(loser_fm.get("aliases"), list) else []
        survivor_title = (before[into]["identity"] or {}).get("title")
        names = [n for n in [survivor_title, loser_fm.get("title")] + list(aliases)
                 if isinstance(n, str) and n.strip()]
        cleaned = verify.clean_groups([names], domain, terms, allow)
        if cleaned:
            # The survivor alone takes the loser's names. Synced over the
            # whole domain they would also land on any page sharing a
            # generic alias with the loser (another type, even).
            touched.update(verify.sync_aliases(wt, domain, cleaned, terms, only=[into]))
            kept_names.append((into, cleaned[0]))
        if loser_fm.get("type") == "project" and _union_repos(wt, into, loser_fm):
            touched.add(into)
        for path in verify.iter_page_files(wt, domain):
            if path in gone or path in frozen:
                continue
            full = os.path.join(wt, path)
            try:
                text = verify.read_text(full)
            except UnicodeDecodeError:
                continue
            new, count = verify.rewrite_links(text, loser, into, bare=unique)
            if count:
                common.atomic_write_text(full, new)
                touched.add(path)
        full = os.path.join(wt, loser)
        if os.path.lexists(full):
            os.unlink(full)
    # sources.json mention groups: every absorb syncs a stored group into
    # each page holding one of its names, so a name another live page
    # holds stays out (the survivor already has them all).
    groups = []
    pages = verify.load_pages(wt, domain)
    for into, names in kept_names:
        held = set(verify.fold(name) for page in pages if page.path != into
                   for name in page.names)
        kept = [name for name in names if verify.fold(name) not in held]
        if len(kept) >= 2:
            groups.append(kept)
    return applied, blocked, sorted(touched - gone), groups


# ---------------------------------------------------------------------------
# One group
# ---------------------------------------------------------------------------

def _new_outcome(group):
    outcome = collections.OrderedDict()
    outcome["group_id"] = group["group_id"]
    outcome["domain"] = group["domain"]
    outcome["signal"] = group["signal_code"]
    outcome["members"] = list(group["pages"])
    outcome["context"] = list(group["context"])
    outcome["fingerprint"] = group["fingerprint"]
    outcome["ok"] = False
    outcome["reason"] = None
    outcome["result"] = None
    outcome["problems"] = []
    outcome["deferred"] = False
    outcome["merged"] = False
    # pages: files this group's commit changed (absorb.defer_conflicts).
    outcome["pages"] = []
    outcome["removed"] = []
    outcome["merges"] = []
    outcome["blocked_merges"] = []
    outcome["conflicts"] = []
    outcome["warnings"] = []
    outcome["notes"] = ""
    outcome["cost_usd"] = None
    return outcome


def _batch_stub(group):
    """absorb.retain_failed_batch's batch shape: no sources, a folder name
    that never meets absorb's numeric batch folders."""
    return {"batch_id": "consolidate-%d" % group["group_id"], "sources": []}


def _dedupe(problems):
    out = []
    for problem in problems:
        if problem not in out:
            out.append(problem)
    return out


def run_group(ctx, group):
    """LLM step, merge handling and checks for one group. On any failure
    the worktree goes back to the group's starting commit."""
    wt = ctx["wt"]
    outcome = _new_outcome(group)
    domain = group["domain"]
    writable = set(group["pages"])
    pre = verify.head_sha(wt)
    cwd = os.path.join(wt, domain)
    result = None
    try:
        if ctx.get("runner_error") is not None:
            raise ctx["runner_error"]
        if domain == "personal" and ctx.get("foreign_rules"):
            raise verify.BatchFailure(["user_rules_unisolated"])
        before = dict((path, measure(verify.read_text(os.path.join(wt, path))))
                      for path in group["pages"])
        sources_data = ctx["working_sources"]
        index = verify.SourceIndex(sources_data.get("sources"), [], domain)
        mentions, merges = verify.stored_mentions(sources_data, domain)
        unpaged = unpaged_promotions(mentions, merges, verify.load_pages(wt, domain))
        request = {
            "group_id": group["group_id"], "domain": domain, "cwd": cwd, "staging_dir": None,
            "prompt": render_prompt(ctx["template"], ctx["schema_md"], group, cwd,
                                    ctx["now"].strftime("%Y-%m-%d"), ctx["cfg"]["min_keep_ratio"]),
            "schema": OUTPUT_SCHEMA, "pages": list(group["pages"]),
            "context": list(group["context"]),
        }
        result = ctx["runner"](request) or {}
        outcome["cost_usd"] = result.get("cost")
        if not result.get("ok"):
            raise verify.BatchFailure([result.get("reason") or "llm_error"])
        output = normalize_output(result.get("structured"), wt, domain)
        outcome["conflicts"] = output["conflicts"]
        outcome["notes"] = output["notes"]
        # The LLM's own write scope first, before Python edits pages
        # outside the group (link rewrites).
        outside = sorted(set(path for _status, path in verify.changed_files(wt, pre)
                             if path not in writable))
        if outside:
            raise verify.BatchFailure(["outside_group:%s" % path for path in outside])
        applied, blocked, touched, name_groups = apply_merges(ctx, group, pre, output, before)
        outcome["blocked_merges"] = blocked
        if blocked:
            outcome["warnings"].append("merge_blocked_locked_link:%d" % len(blocked))
        live = [{"id": source_id, "op": "changed"}
                for source_id in sorted(set(i for m in before.values() for i, _d in m["pairs"]))]
        repaired = verify.repair_src_ids(wt, pre, domain, live, index)
        if repaired:
            outcome["warnings"].append("src_id_repaired:%d" % repaired)
        losers = set(loser for loser, _into, _bare in applied)
        problems = conservation_problems(wt, pre, before, writable, touched, losers,
                                         ctx["cfg"]["min_keep_ratio"])
        scope = writable | set(touched)
        try:
            verify.check_changes(wt, pre, domain, lambda path: path in scope, index,
                                 ctx["domains"], outside_code="outside_group",
                                 scan_withdrawn=False)
        except verify.BatchFailure as exc:
            problems += exc.problems
        if not problems:
            after = unpaged_promotions(mentions, merges + name_groups,
                                       verify.load_pages(wt, domain))
            if after > unpaged:
                problems.append("promotion_regressed:%d" % (after - unpaged))
        if problems:
            raise verify.BatchFailure(_dedupe(problems))
        made = absorb.commit_worktree(wt, "wiki: consolidate %s 묶음 %d (%s)"
                                      % (ctx["run_id"], group["group_id"], domain))
        post = verify.head_sha(wt)
        outcome["ok"] = True
        outcome["result"] = RESULT_CHANGED if made else RESULT_NO_CHANGE
        outcome["pages"] = verify.touched_between(wt, pre, post) if made else []
        outcome["removed"] = sorted(losers)
        outcome["merges"] = [[loser, into] for loser, into, _bare in applied]
        ctx["private"][group["group_id"]] = {"applied": applied, "name_groups": name_groups}
    except common.WikiError as exc:
        outcome["ok"] = False
        outcome["reason"] = exc.reason
        outcome["problems"] = list(getattr(exc, "problems", []) or [str(exc)])[:20]
        if absorb.retain_failed_batch(ctx, _batch_stub(group), outcome, pre, result):
            outcome["warnings"].append("failed_draft_kept")
        absorb.reset_worktree(wt, pre)
    except (ValueError, OSError) as exc:
        outcome["ok"] = False
        outcome["reason"] = "page_unreadable"
        outcome["problems"] = ["page_unreadable:%s" % type(exc).__name__]
        if absorb.retain_failed_batch(ctx, _batch_stub(group), outcome, pre, result):
            outcome["warnings"].append("failed_draft_kept")
        absorb.reset_worktree(wt, pre)
    return outcome


# ---------------------------------------------------------------------------
# After the groups: root files, merge, state
# ---------------------------------------------------------------------------

def _live(outcomes):
    """Outcomes whose change goes into the merge."""
    return [o for o in outcomes if o["ok"] and o["result"] == RESULT_CHANGED and not o["deferred"]]


def _applied_merges(ctx, outcomes):
    out = []
    for outcome in _live(outcomes):
        out += (ctx["private"].get(outcome["group_id"]) or {}).get("applied") or []
    return out


def rewritten_drafts(stored, applied):
    """{name: {domain: text}} of the stored root-file fragments (stored:
    absorb.load_stored_drafts) with links to merged-away pages pointed at
    their survivors (only fragments that changed)."""
    out = dict((name, {}) for name in verify.ROOT_DRAFTS)
    for name in verify.ROOT_DRAFTS:
        for domain, text in (stored.get(name) or {}).items():
            new = text
            for loser, into, bare in applied:
                if loser.startswith(domain + "/"):
                    new, _count = verify.rewrite_links(new, loser, into, bare=bare)
            if new != text:
                out[name][domain] = new
    return out


def _store_fragments(root, original, drafts, written):
    """.state/drafts as drafts says ({name: {domain: text}}), before the
    merge: every absorb reassembles root now.md/about-me.md from these
    fragments, so one still linking a deleted page would bring the dead
    link back daily. A fragment written earlier in this run that no longer
    needs a rewrite (its group got deferred) goes back to original.
    written collects (name, domain). Raises WikiError(drafts_store_failed):
    the merge is then not made."""
    try:
        for name in verify.ROOT_DRAFTS:
            wanted = drafts.get(name) or {}
            again = set(domain for item, domain in written if item == name)
            for domain in sorted(set(wanted) | again):
                text = wanted.get(domain, (original.get(name) or {}).get(domain))
                if text is None:
                    continue
                written.add((name, domain))
                absorb.store_drafts(root, domain, {name: text})
    except (IOError, OSError) as exc:
        raise common.WikiError("drafts_store_failed", type(exc).__name__)


def _restore_fragments(root, original, written, warnings):
    """A merge that did not happen: the stored fragments this run wrote go
    back to their original text (best effort; a fragment left rewritten
    still links the survivor, which main holds)."""
    try:
        for name, domain in sorted(written):
            text = (original.get(name) or {}).get(domain)
            if text is not None:
                absorb.store_drafts(root, domain, {name: text})
    except (IOError, OSError) as exc:
        warnings.append("drafts_restore_failed:%s" % type(exc).__name__)


def _rewrite_root_files(wt, applied):
    """Links to merged-away pages in root now.md/about-me.md above
    '## 내 메모' (a domain without a stored fragment keeps its old text).
    Path links only: a bare [[name]] there may name the other domain's
    page."""
    for name in verify.ROOT_DRAFTS:
        full = os.path.join(wt, name)
        text = _read_or_none(full)
        if text is None:
            continue
        new = text
        for loser, into, _bare in applied:
            new, _count = verify.rewrite_links(new, loser, into, bare=False)
        if new != text and verify.notes_tail(new) == verify.notes_tail(text):
            common.atomic_write_text(full, new)


def _tally(chosen, outcomes):
    """(merges, changed pages, conflicts, failed groups, deferred groups):
    merges and changed pages of the chosen outcomes, the rest of all."""
    merges = sum(len(o["merges"]) for o in chosen)
    changed = sum(len([p for p in o["pages"] if p not in o["removed"]]) for o in chosen)
    conflicts = sum(len(o["conflicts"]) for o in outcomes if o["ok"] and not o["deferred"])
    failed = len([o for o in outcomes if not o["ok"]])
    deferred = len([o for o in outcomes if o["deferred"]])
    return merges, changed, conflicts, failed, deferred


def _log_line(report, outcomes):
    merges, changed, conflicts, failed, _deferred = _tally(_live(outcomes), outcomes)
    parts = ["- %s consolidate" % report["run_id"],
             "묶음 %d/%d" % (len([o for o in outcomes if o["ok"] and not o["deferred"]]),
                           len(outcomes)),
             "합침 %d" % merges, "고침 %d" % changed, "실패 %d" % failed,
             "어긋남 %d" % conflicts]
    reasons = sorted(set(o["reason"] for o in outcomes if o["reason"]))
    if reasons:
        parts.append("사유 " + ",".join(reasons))
    return " · ".join(parts)


def _existing_pending(root):
    """The context cache's pending block: written only by absorb
    (dev:pending_scope), so consolidate carries it over."""
    try:
        data = common.load_json_file(os.path.join(common.state_dir(root), "context-cache.json"))
    except common.WikiError:
        return None
    return data.get("pending") if isinstance(data, dict) else None


def _finish(ctx, report, outcomes, base, rules_path):
    root, wt = ctx["root"], ctx["wt"]
    # One snapshot of the stored fragments: write_generated may run up to
    # three times, and a later pass may defer a group whose merge an
    # earlier pass already wrote into the store.
    original = absorb.load_stored_drafts(root)
    written = set()

    def write_generated():
        applied = _applied_merges(ctx, outcomes)
        drafts = rewritten_drafts(original, applied)
        _store_fragments(root, original, drafts, written)
        codes = absorb.generate_root_files(ctx, drafts, maintenance=False)
        _rewrite_root_files(wt, applied)
        absorb._append_log(wt, _log_line(report, outcomes))
        return codes

    deferred, merge_error = absorb.settle_and_merge(
        ctx, base, outcomes, "wiki: consolidate %s 보류 (사람 편집과 겹침)" % ctx["run_id"],
        write_generated, "wiki: consolidate %s 색인·기록" % ctx["run_id"], report["warnings"])
    report["deferred_files"] = sorted(set(deferred))
    merged = merge_error is None
    if merged:
        for outcome in outcomes:
            outcome["merged"] = (outcome["ok"] and outcome["result"] == RESULT_CHANGED
                                 and not outcome["deferred"])
    elif written:
        _restore_fragments(root, original, written, report["warnings"])
    absorb.reset_worktree(wt, verify.head_sha(root))
    merged_groups = [o for o in outcomes if o["merged"]]
    if merged_groups:
        _post_merge(ctx, report, merged_groups, rules_path)
    _record_state(ctx, outcomes)
    report["head"] = verify.head_sha(root)
    return merge_error


def _post_merge(ctx, report, merged_groups, rules_path):
    """After the merge (the rewritten fragments are stored already, see
    _store_fragments): mention groups, caches and the rules file."""
    root = ctx["root"]
    try:
        data = prepare.load_sources(root)
        for outcome in merged_groups:
            groups = (ctx["private"].get(outcome["group_id"]) or {}).get("name_groups") or []
            if groups:
                verify.update_mentions(data, outcome["domain"], {}, groups)
        prepare.save_sources(root, data)
    except (common.WikiError, IOError, OSError) as exc:
        report["warnings"].append("source_state_failed:%s" % getattr(exc, "reason", "io"))
    absorb.refresh_caches_and_rules(ctx, report, ctx["run_id"], rules_path,
                                    lambda: _existing_pending(root))


def _record_state(ctx, outcomes):
    """Fingerprints and per-page last consolidation (normal mode only): a
    group with no change always, a changed one once merged. Failed or
    deferred groups leave no trace, so they come back next run."""
    root = ctx["root"]
    state = load_state(root)
    at = verify.iso_now(ctx["now"])
    head = verify.head_sha(root)
    for outcome in outcomes:
        if not outcome["ok"]:
            continue
        if outcome["result"] == RESULT_CHANGED and not outcome["merged"]:
            continue
        state["groups"][outcome["fingerprint"]] = collections.OrderedDict(
            [("result", outcome["result"]), ("run_id", ctx["run_id"]), ("at", at)])
        blobs = head_blobs(root, head, outcome["domain"])
        for path in outcome["members"]:
            if path in blobs:
                state["pages"][path] = collections.OrderedDict(
                    [("blob", blobs[path]), ("run_id", ctx["run_id"]), ("at", at)])
            else:
                state["pages"].pop(path, None)
    try:
        save_state(root, state)
    except (common.WikiError, IOError, OSError):
        pass


def write_preview(ctx, base):
    """dry_run: the run's diff, redacted, at .state/consolidate/<run_id>/
    preview.diff (folders 0700, file 0600; the newest PREVIEW_KEEP_RUNS run
    folders are kept). Returns the path or None."""
    root, wt = ctx["root"], ctx["wt"]
    try:
        diff = common.wiki_git(wt, ["diff", "--no-color", "--no-ext-diff", base, "HEAD"]).stdout
        text = diff.decode("utf-8", "replace")
        allow = verify.scan_allow(wt, ctx["domains"])
        known = verify.known_source_ids(ctx["working_sources"].get("sources"))
        base_dir = os.path.join(common.state_dir(root), PREVIEW_DIR)
        run_dir = os.path.join(base_dir, ctx["run_id"])
        for path in (common.state_dir(root), base_dir, run_dir):
            common.ensure_private_dir(path)
        path = os.path.join(run_dir, PREVIEW_FILE)
        common.atomic_write_text(path, redact.redact(text, allow, known).text, mode=0o600)
        # Like the failed store: the newest few previews only.
        absorb.prune_run_dirs(base_dir, PREVIEW_KEEP_RUNS)
        return path
    except (common.WikiError, IOError, OSError):
        return None


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

COMMAND = "consolidate"


def new_report(mode=MODE_NORMAL, scheduled=False):
    report = collections.OrderedDict()
    report["command"] = COMMAND
    report["ok"] = False
    report["status"] = None
    report["reason"] = None
    report["mode"] = mode
    report["scheduled"] = bool(scheduled)
    report["run_id"] = None
    report["base_sha"] = None
    report["head"] = None
    report["domain"] = None
    report["candidates"] = collections.OrderedDict()
    report["groups"] = []
    report["merges"] = 0
    report["changed"] = 0
    report["failed"] = 0
    report["conflicts"] = 0
    report["deferred_groups"] = 0
    report["rules_added"] = 0
    report["rules_removed"] = 0
    report["deferred_files"] = []
    report["warnings"] = []
    report["preview_path"] = None
    report["summary_line"] = ""
    return report


def summary_line(report):
    status = report["status"]
    if status == STATUS_FAILED:
        return "위키 정리: 실패 (%s)" % (report.get("reason") or "unknown")
    if report["mode"] == MODE_PLAN:
        cand = report.get("candidates") or {}
        return "위키 정리 계획: 묶음 %d · 페이지 %d · 건너뜀 %d" % (
            len(report["groups"]), sum(len(g.get("pages") or []) for g in report["groups"]),
            cand.get("skipped_unchanged", 0))
    if status == STATUS_EMPTY:
        return "위키 정리: 묶음 0"
    parts = ["묶음 %d" % len(report["groups"]), "합침 %d" % report["merges"],
             "고침 %d" % report["changed"], "실패 %d" % report["failed"],
             "어긋남 %d" % report["conflicts"]]
    if report.get("deferred_groups"):
        parts.append("보류 %d" % report["deferred_groups"])
    prefix = "위키 정리(미리보기): " if report["mode"] == MODE_DRY_RUN else "위키 정리: "
    if status == STATUS_HELD:
        prefix += "한도 보류 · "
    return prefix + " · ".join(parts)


PUBLIC_KEYS = ("command", "ok", "status", "reason", "mode", "scheduled", "run_id", "merges",
               "changed", "failed", "conflicts", "deferred_groups", "rules_added",
               "rules_removed", "summary_line")


def public_report(report, report_path=None):
    """What a session (text or --json) and Slack may see: status, reason
    codes and counts only. Page paths, conflicts and problems stay in the
    report file."""
    out = collections.OrderedDict()
    for key in PUBLIC_KEYS:
        if key in report:
            out[key] = report[key]
    cand = report.get("candidates") or {}
    out["candidates"] = collections.OrderedDict([
        ("pages", cand.get("pages", 0)), ("skipped_unchanged", cand.get("skipped_unchanged", 0)),
        ("refused", cand.get("refused", 0)),
        ("excluded", collections.OrderedDict(cand.get("excluded") or {}))])
    groups = []
    for group in report.get("groups") or []:
        item = collections.OrderedDict()
        item["group_id"] = group.get("group_id")
        item["domain"] = group.get("domain")
        item["signal"] = group.get("signal") or group.get("signal_code")
        item["members"] = len(group.get("members") or group.get("pages") or [])
        for key in ("ok", "reason", "result", "deferred", "merged"):
            if key in group:
                item[key] = group.get(key)
        for key in ("merges", "blocked_merges", "conflicts", "problems"):
            if key in group:
                item[key] = len(group.get(key) or [])
        if "removed" in group:
            item["changed"] = len([p for p in group.get("pages") or []
                                   if p not in group.get("removed") or []])
        groups.append(item)
    out["groups"] = groups
    out["deferred_files"] = len(report.get("deferred_files") or [])
    out["warnings"] = absorb.warning_codes(report.get("warnings"))
    sent = report.get("notify")
    if isinstance(sent, dict):
        out["notify"] = collections.OrderedDict(
            (key, sent.get(key)) for key in ("state", "text", "mode", "sent", "reason"))
    if report_path:
        out["report_path"] = report_path
    return out


def report_path(root, mode=MODE_NORMAL):
    """The full report file of a run in that mode. plan and dry_run have
    their own, so a look ahead never replaces the last real run's report
    (its conflict list and failure details live only there)."""
    return os.path.join(common.state_dir(root), REPORT_FILES.get(mode, REPORT_FILE))


def write_report_file(root, report):
    """The full report (group page paths, problems, redacted conflicts) to
    its mode's report file (report_path, 0600). Returns the path or None."""
    try:
        common.ensure_private_dir(common.state_dir(root))
        path = report_path(root, report.get("mode") or MODE_NORMAL)
        common.atomic_write_text(path, common.dumps_json(report), mode=0o600)
        return path
    except (common.WikiError, IOError, OSError, TypeError, ValueError):
        return None


def last_path(root):
    return os.path.join(common.state_dir(root), LAST_FILE)


def read_last(root):
    try:
        data = common.load_json_file(last_path(root))
    except common.WikiError:
        return None
    return data if isinstance(data, dict) else None


def read_running_marker(root):
    """The marker of a live consolidate (pid, started_at), or None; the
    same semantics as absorb's (absorb.read_running_marker)."""
    return absorb.read_running_marker(root, RUNNING_FILE)


def write_last(root, report, now):
    """.state/last-consolidate (run_id, finished_at, mode, status, reason,
    summary_line) for `status`'s 마지막 정리: normal runs only (a plan or
    a preview tidied nothing; the 7-day rule ignores them too)."""
    if (report.get("mode") or MODE_NORMAL) != MODE_NORMAL:
        return
    data = collections.OrderedDict()
    for key in ("run_id", "mode", "status", "reason", "summary_line"):
        data[key] = report.get(key)
    data["finished_at"] = verify.iso_now(now)
    try:
        common.ensure_private_dir(common.state_dir(root))
        common.atomic_write_text(last_path(root), common.dumps_json(data), mode=0o600)
    except (common.WikiError, IOError, OSError):
        pass


def _redact_private(ctx, outcomes):
    """LLM-written text (conflict facts, notes) was never scanned: redact it
    before it reaches the report file."""
    try:
        allow = verify.scan_allow(ctx["wt"], ctx["domains"])
    except (IOError, OSError):
        allow = list(ctx["domains"].get("redact_allow", []) or [])
    known = verify.known_source_ids(ctx["working_sources"].get("sources"))
    for outcome in outcomes:
        for item in outcome["conflicts"]:
            item["fact"] = redact.redact(item["fact"], allow, known).text
        outcome["notes"] = redact.redact(outcome["notes"], allow, known).text


def _settle_status(report, outcomes, merge_error):
    if report["mode"] == MODE_NORMAL:
        chosen = [o for o in outcomes if o["merged"]]
    else:
        # dry_run: what would have merged.
        chosen = [o for o in outcomes if o["ok"] and o["result"] == RESULT_CHANGED]
    merges, changed, conflicts, failed, deferred = _tally(chosen, outcomes)
    report["merges"], report["changed"], report["conflicts"] = merges, changed, conflicts
    report["failed"], report["deferred_groups"] = failed, deferred
    failed_groups = [o for o in outcomes if not o["ok"]]
    if merge_error is not None:
        report["status"] = STATUS_FAILED
        report["reason"] = merge_error.reason
    elif not outcomes:
        report["status"] = STATUS_EMPTY
    elif any(o["reason"] == "budget_exceeded" for o in failed_groups):
        report["status"] = STATUS_HELD
        report["reason"] = "budget_exceeded"
    elif failed_groups and len(failed_groups) == len(outcomes):
        report["status"] = STATUS_FAILED
        report["reason"] = failed_groups[0]["reason"]
    else:
        report["status"] = STATUS_OK


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def _setup(root):
    """(domains_cfg, settings, sources) or a WikiError."""
    domains_cfg = common.load_domains(root)
    guard = common.domains_guard(domains_cfg, root)
    if guard:
        raise common.WikiError(guard, "domains.json: fill in owners and work_terms first")
    settings = common.load_settings(root)
    return domains_cfg, settings, prepare.load_sources(root)


def _plan_groups_public(groups):
    return [collections.OrderedDict([
        ("group_id", g["group_id"]), ("domain", g["domain"]), ("signal", g["signal_code"]),
        ("pages", list(g["pages"])), ("context", list(g["context"])),
        ("why", g["why"]), ("fingerprint", g["fingerprint"])]) for g in groups]


def consolidate(root, environ=None, now=None, runner=None, rules_path=None, mode=MODE_NORMAL,
                domain=None, max_groups=None, scheduled=False):
    """Run consolidate once. Returns the report (the full one; print
    public_report of it). Raises LockBusy when absorb or another
    consolidate holds the lock (plan takes no lock) and
    WikiError(not_initialized) for a missing wiki.

    schedule.run_consolidate wraps this (ledger, Slack line); its
    scheduled call comes from schedule.run_absorb's "not due" branch. The
    ledger keeps the mode, so a dry run never counts for the 7-day rule."""
    environ = os.environ if environ is None else environ
    now = now or datetime.datetime.now()
    if mode not in MODES:
        raise ValueError("unknown consolidate mode %r" % (mode,))
    if domain is not None and domain not in common.DOMAINS:
        raise common.WikiError("domain_invalid", "domain must be work or personal")
    if not common.is_initialized(root) or not os.path.isdir(os.path.join(root, ".git")):
        raise common.WikiError("not_initialized", "%s is not a wiki; run wiki init" % root)
    rules_path = rules_path or absorb.default_rules_path(environ)
    if mode == MODE_PLAN:
        return _plan(root, environ, now, rules_path, domain, max_groups)
    with common.wiki_lock(root):
        absorb.write_running_marker(root, now, RUNNING_FILE)
        try:
            return _run(root, environ, now, runner, rules_path, mode, domain, max_groups,
                        scheduled)
        except Exception as exc:
            report = new_report(mode, scheduled)
            report["status"] = STATUS_FAILED
            report["reason"] = (exc.reason if isinstance(exc, common.WikiError)
                                else "internal_error")
            report["summary_line"] = summary_line(report)
            write_last(root, report, now)
            raise
        finally:
            absorb.remove_running_marker(root, RUNNING_FILE)


def _refused_domains(report, environ, rules_path, root, domains_cfg):
    """(domains whose pages are no candidates, foreign rules count):
    personal while foreign user rules exist (absorb.foreign_user_rules).
    Its groups would only refuse with user_rules_unisolated, so they must
    not take the run's group slots (the same ones would come back first
    every week). Adds user_rules_present:<n>."""
    terms = verify.Terms(domains_cfg.get("work_terms", []))
    count = absorb.foreign_user_rules(environ, rules_path, root, terms)
    if not count:
        return (), 0
    report["warnings"].append("user_rules_present:%d" % count)
    return ("personal",), count


def _note_refused(report, plan):
    """user_rules_unisolated:<n> for refused candidates; True when they
    were all there was (the run then fails with that reason)."""
    if plan["refused"]:
        report["warnings"].append("user_rules_unisolated:%d" % plan["refused"])
    return bool(plan["refused"]) and not plan["groups"]


def _plan(root, environ, now, rules_path, domain, max_groups):
    report = new_report(MODE_PLAN)
    report["run_id"] = common.make_run_id(now)
    report["domain"] = domain
    try:
        domains_cfg, settings, sources = _setup(root)
        base = verify.head_sha(root)
        refuse, _count = _refused_domains(report, environ, rules_path, root, domains_cfg)
        plan = select_groups(root, settings, domains_cfg, sources, load_state(root), base,
                             domain, max_groups, refuse)
    except common.WikiError as exc:
        report["status"] = STATUS_FAILED
        report["reason"] = exc.reason
        report["summary_line"] = summary_line(report)
        write_report_file(root, report)
        return report
    report["base_sha"] = base
    report["candidates"] = _candidates(plan)
    report["groups"] = _plan_groups_public(plan["groups"])
    if _note_refused(report, plan):
        report["status"] = STATUS_FAILED
        report["reason"] = "user_rules_unisolated"
    else:
        report["status"] = STATUS_OK if plan["groups"] else STATUS_EMPTY
    report["ok"] = report["status"] != STATUS_FAILED
    report["summary_line"] = summary_line(report)
    write_report_file(root, report)
    return report


def _candidates(plan):
    out = collections.OrderedDict()
    out["pages"] = plan["pages"]
    out["groups"] = len(plan["groups"])
    out["skipped_unchanged"] = plan["skipped_unchanged"]
    out["refused"] = plan["refused"]
    out["excluded"] = plan["excluded"]
    out["frozen"] = plan["frozen"]
    return out


def _run(root, environ, now, runner, rules_path, mode, domain, max_groups, scheduled):
    report = new_report(mode, scheduled)
    report["run_id"] = common.make_run_id(now)
    report["domain"] = domain
    try:
        domains_cfg, settings, sources = _setup(root)
        base = verify.head_sha(root)
        refuse, foreign = _refused_domains(report, environ, rules_path, root, domains_cfg)
        plan = select_groups(root, settings, domains_cfg, sources, load_state(root), base,
                             domain, max_groups, refuse)
    except common.WikiError as exc:
        report["status"] = STATUS_FAILED
        report["reason"] = exc.reason
        report["warnings"].append("%s:%s" % (exc.reason, str(exc)[:300]))
        return _done(root, report, now)
    report["base_sha"] = base
    report["candidates"] = _candidates(plan)
    only_refused = _note_refused(report, plan)
    if not plan["groups"]:
        _settle_status(report, [], None)
        if only_refused:
            report["status"] = STATUS_FAILED
            report["reason"] = "user_rules_unisolated"
        return _done(root, report, now)
    outcomes = []
    merge_error = None
    try:
        wt = absorb.setup_worktree(root, base)
        ctx = {"root": root, "wt": wt, "now": now, "run_id": report["run_id"],
               "domains": domains_cfg, "cfg": consolidate_settings(settings),
               "working_sources": sources, "run_sources": [], "runner": runner,
               "runner_error": None, "private": {}, "frozen": plan["frozen"],
               # run_group keeps refusing personal groups (belt-and-braces).
               "foreign_rules": foreign}
        ctx["template"] = absorb.read_template(PROMPT_TEMPLATE)
        schema_path = os.path.join(wt, "SCHEMA.md")
        ctx["schema_md"] = (verify.read_text(schema_path) if os.path.isfile(schema_path)
                            else absorb.read_template("SCHEMA.md"))
        if runner is None:
            try:
                ctx["runner"] = absorb.ClaudeRunner.from_settings(settings, environ)
            except common.WikiError as exc:
                ctx["runner_error"] = exc
        for group in plan["groups"]:
            outcomes.append(run_group(ctx, group))
        _redact_private(ctx, outcomes)
        if mode == MODE_DRY_RUN:
            report["preview_path"] = write_preview(ctx, base)
        else:
            merge_error = _finish(ctx, report, outcomes, base, rules_path)
    finally:
        try:
            absorb.remove_worktree(root)
        except common.WikiError:
            report["warnings"].append("worktree_cleanup_failed")
    report["groups"] = outcomes
    for outcome in outcomes:
        for code in outcome["warnings"]:
            report["warnings"].append(code)
    _settle_status(report, outcomes, merge_error)
    return _done(root, report, now)


def _done(root, report, now):
    report["summary_line"] = summary_line(report)
    report["ok"] = report["status"] in (STATUS_OK, STATUS_EMPTY, STATUS_HELD)
    write_last(root, report, now)
    write_report_file(root, report)
    return report
