"""absorb verify step (T3). Python 3.9, stdlib only.

Everything here runs in Python after the isolated LLM step; the LLM never
writes index.md, log.md, root now.md/about-me.md, caches or the rules file.

Per batch (in the absorb worktree, against the batch's starting commit):
  - changed files = `git diff --name-status -z --no-renames <pre>` plus every
    untracked file including ignored ones (`git ls-files --others -z`, no
    --exclude-standard, so writes into gitignored paths such as _drafts/
    are seen). Any path outside allowed_globs, a symlink or a non-regular
    file fails the whole batch (contract 1).
  - pages: valid frontmatter, domain equal to the batch domain, .md only
  - '## 내 메모' tails byte-for-byte unchanged; a deleted page whose notes
    hold text fails (D1)
  - section src: every src of a changed page must be a known source of the
    page's domain; an unknown id fails (its domain cannot be checked); a src
    pointing at a source withdrawn from this domain fails anywhere in the
    domain (contract 1)
  - no link into the other domain (D9)
  - contract-4 secret rescan; personal pages and drafts must not hit
    work_terms (D5)
Then Python post-processing: alias sync for merged names (D9) and link
conversion that skips '## 내 메모', code and frontmatter (D9).

After all batches: index.md, root now.md/about-me.md assembled from
<domain>/_drafts fragments with '## 내 메모' preserved byte-for-byte (D16,
panel D-2), paused status after 21 days, a whole-tree secret scan before
merge (contract 4). After the merge: .state/context-cache.json and
alias-cache.json (references/caches.md) and the domain-neutral rules file
(D12).
"""

import collections
import datetime
import json
import os
import re
import shutil
import stat
import sys
import unicodedata
import urllib.parse

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import common  # noqa: E402
import redact  # noqa: E402

MAX_DRAFT_CHARS = 12000
MAX_PAGE_BYTES = 512 * 1024
AS_OF_DAYS = 14
PAUSED_DAYS = 21
PROMOTE_MIN_SOURCES = 3
MIN_LINK_NAME = 3

RULES_MAX_LINES = 30
RULES_MAX_CHARS = 3000
RULES_MAX_LINE_CHARS = 240
RULES_HEADER = ("# 작업 선호 (wiki가 만든 파일)\n\n"
                "개인 위키 absorb가 도메인과 무관한 선호만 모아 다시 쓴다. 직접 고치지 않는다.\n\n")

ROOT_DRAFTS = ("now.md", "about-me.md")
ABOUT_ME_SECTIONS = ("하는 일", "일하는 방식", "반복되는 선호")
TEXT_SUFFIXES = (".md", ".json", ".txt", ".gitignore")

_HANGUL_RE = re.compile(u"[ᄀ-ᇿ㄰-㆏ꥠ-꥿가-힯ힰ-퟿]")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#^\n]+)(?:[#^][^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\]")
_MDLINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"\n]*\")?\s*\)")
_PROTECT_RE = re.compile(r"`[^`\n]*`|\[\[[^\]\n]*\]\]|!?\[[^\]\n]*\]\([^)\n]*\)|<!--.*?-->"
                         r"|<[^>\n]+>|[A-Za-z][A-Za-z0-9+.-]*://\S+")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(\s|$)")
_SECTION_RE = re.compile(r"^## (.+?)\s*$")


class BatchFailure(common.WikiError):
    """A batch failed verification; reason is the first problem's code."""

    def __init__(self, problems):
        self.problems = list(problems)
        first = self.problems[0] if self.problems else "verify_failed"
        common.WikiError.__init__(self, first.split(":", 1)[0], "; ".join(self.problems[:10]))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def fold(text):
    return unicodedata.normalize("NFKC", text or "").casefold()


class Terms(object):
    """work_terms matcher: NFKC + casefold on both sides (D5, D12), with
    the home folder replaced by '~' first (common.strip_home, fix round 1;
    home defaults to $HOME)."""

    def __init__(self, terms, home=None):
        self.terms = [fold(term) for term in terms or () if fold(term).strip()]
        self.home = home

    def hits(self, text):
        if not self.terms or not text:
            return False
        folded = fold(common.strip_home(text, self.home))
        return any(term in folded for term in self.terms)


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def read_text(path):
    return read_bytes(path).decode("utf-8")


def git_out(cwd, args, check=True):
    return common.wiki_git(cwd, args, check=check).stdout


def head_sha(cwd):
    return git_out(cwd, ["rev-parse", "--verify", "HEAD"]).decode("ascii").strip()


def blob_at(cwd, sha, path):
    """Bytes of path at commit sha, or None when absent there."""
    proc = common.wiki_git(cwd, ["cat-file", "-e", "%s:%s" % (sha, path)], check=False)
    if proc.returncode != 0:
        return None
    return git_out(cwd, ["cat-file", "blob", "%s:%s" % (sha, path)])


def _split_z(data):
    return [part for part in data.decode("utf-8", "surrogateescape").split("\0") if part]


def changed_files(wt, base):
    """[(status, path)] changed in the worktree since base: tracked changes
    (A/M/D/T...) and every untracked file, ignored ones included ('?')."""
    tokens = _split_z(git_out(wt, ["diff", "--name-status", "-z", "--no-renames", base]))
    changes = []
    for index in range(0, len(tokens) - 1, 2):
        changes.append((tokens[index][:1], tokens[index + 1]))
    for path in _split_z(git_out(wt, ["ls-files", "--others", "-z"])):
        changes.append(("?", path))
    return changes


def touched_between(cwd, old, new):
    """Paths changed between two commits (names only)."""
    return _split_z(git_out(cwd, ["diff", "--name-only", "-z", "--no-renames", old, new]))


def page_split(text):
    """(fm dict or None, fm_error or None, body, newline)."""
    try:
        fm_text, body, newline = common.split_frontmatter(text)
    except common.FrontmatterError as exc:
        return None, str(exc), text, "\n"
    if fm_text is None:
        return None, None, body, newline
    try:
        return common.parse_frontmatter_block(fm_text), None, body, newline
    except common.FrontmatterError as exc:
        return None, str(exc), body, newline


def notes_tail(text):
    """The '## 내 메모' tail (heading to end of file), '' when missing."""
    _fm, _err, body, _nl = page_split(text)
    return common.split_my_notes(body)[1]


# notes_guard prefix of a page whose '## 내 메모' heading is hidden in code.
HIDDEN_NOTES_MARK = "\x00hidden-notes\x00"


def _body_notes_hidden(body):
    raw = any(common.is_my_notes_heading(line) for line in body.splitlines())
    return raw and not common.split_my_notes(body)[1]


def notes_hidden(text):
    """True when a page has a raw '## 내 메모' line that split_my_notes
    cannot find: an unclosed (or mismatched) fence above it, e.g. ```
    pasted in Obsidian, turns the human's notes into 'code'."""
    _fm, _err, body, _nl = page_split(text)
    return _body_notes_hidden(body)


def notes_guard(text):
    """What D1 freezes in a page: its '## 내 메모' tail, or, when the
    heading is hidden by an open fence (notes_hidden), the whole body
    (fix round 1: the human's text cannot be told apart from the LLM's
    there, so all of it is human-owned). Compare with same_notes."""
    _fm, _err, body, _nl = page_split(text)
    if _body_notes_hidden(body):
        return HIDDEN_NOTES_MARK + body
    return common.split_my_notes(body)[1]


def same_notes(old_tail, new_tail):
    """'## 내 메모' tails compare byte-for-byte, except that a page without
    the heading equals one that gained only the empty heading (SCHEMA puts
    it last on every page, so the LLM may add it to a human page). A
    hidden-notes guard (notes_guard) only equals itself."""
    if old_tail == new_tail:
        return True
    if old_tail.startswith(HIDDEN_NOTES_MARK) or new_tail.startswith(HIDDEN_NOTES_MARK):
        return False
    empty = ("", common.MY_NOTES_HEADING)
    return old_tail.strip() in empty and new_tail.strip() in empty and not old_tail.strip()


def before_notes(text):
    """Body text before '## 내 메모' (frontmatter excluded)."""
    _fm, _err, body, _nl = page_split(text)
    return common.split_my_notes(body)[0]


def fences_balanced(text):
    """True when every ``` / ~~~ fence opened in text is closed again
    (same rules as strip_fences and common.split_my_notes)."""
    fence = None
    for line in (text or "").splitlines():
        fence, _match = common.fence_step(fence, line)
    return fence is None


def root_assemblable(current):
    """A root now.md/about-me.md can be reassembled only when its fences
    balance and its '## 내 메모' heading is found outside code (an open
    fence above it, e.g. ``` pasted in Obsidian, would hide the human's
    notes from the assembler and drop them)."""
    if not fences_balanced(current):
        return False
    raw_heading = any(common.is_my_notes_heading(line)
                      for line in (current or "").splitlines())
    return not raw_heading or bool(notes_tail(current))


def strip_fences(text):
    """Text with fenced code blocks blanked (for link and src scans)."""
    out = []
    fence = None
    for line in text.splitlines(True):
        fence, match = common.fence_step(fence, line)
        if match:
            out.append("\n")
            continue
        out.append("\n" if fence else line)
    return "".join(out)


def src_ids(text):
    return [match.group(1) for match in common.SRC_COMMENT_RE.finditer(strip_fences(text))]


def src_dates(text):
    return [match.group(2) for match in common.SRC_COMMENT_RE.finditer(strip_fences(text))]


def link_targets(text):
    """Link targets in text (wikilinks and markdown links), code excluded."""
    clean = strip_fences(text)
    clean = re.sub(r"`[^`\n]*`", "", clean)
    targets = [match.group(1).strip() for match in _WIKILINK_RE.finditer(clean)]
    targets += [match.group(1).strip() for match in _MDLINK_RE.finditer(clean)]
    return targets


def wikilink_targets(text):
    """Wikilink targets only (code excluded)."""
    clean = strip_fences(text)
    clean = re.sub(r"`[^`\n]*`", "", clean)
    return [match.group(1).strip() for match in _WIKILINK_RE.finditer(clean)]


def target_path(target):
    """Normalized wiki-relative path of a link target, or None for URLs."""
    value = urllib.parse.unquote(target).strip()
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        return None
    while True:
        if value.startswith("./"):
            value = value[2:]
        elif value.startswith("../"):
            value = value[3:]
        elif value.startswith("/"):
            value = value[1:]
        else:
            break
    return value


def target_domain(target):
    path = target_path(target)
    if not path:
        return None
    head = path.split("/", 1)[0]
    return head if head in common.DOMAINS else None


def page_basenames(wt, domain):
    """Folded basenames (no .md) of the pages in one domain folder."""
    names = set()
    for rel in iter_page_files(wt, domain):
        names.add(fold(rel.rsplit("/", 1)[-1][:-3]))
    return names


def crosses_domain(text, other, other_names):
    """True when text links into another domain: a path-prefixed target, or
    a bare wikilink whose basename is a page of the other domain (Obsidian
    resolves bare wikilinks vault-wide by file name, D9)."""
    for target in link_targets(text):
        if target_domain(target) in other:
            return True
    for target in wikilink_targets(text):
        path = target_path(target)
        if not path or target_domain(target) is not None:
            continue
        base = path.rsplit("/", 1)[-1]
        if base.endswith(".md"):
            base = base[:-3]
        if fold(base) in other_names:
            return True
    return False


def fm_strings(fm):
    """Every string value in a frontmatter dict, one per line (for the
    cross-domain link check: Obsidian renders frontmatter links too)."""
    out = []

    def walk(value):
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(fm or {})
    return "\n".join(out)


def strip_src_comments(text):
    """text without its '<!-- src: <id> @date -->' comments. Source ids are
    built from file and folder names (an encoded home folder, a handoff
    file name) and are checked separately by SourceIndex as known sources
    of the batch's domain, so their spelling is no page content (review
    round 3: a work term in the home folder name failed every personal
    memory page forever)."""
    return common.SRC_COMMENT_RE.sub("", text or "")


def personal_term_hit(terms, path, main_part, fm):
    """A personal page hits work_terms in its path, body (before '## 내 메모',
    src comments excluded) or frontmatter (D5: the path shows up in
    index.md, query and links)."""
    return terms.hits(path + "\n" + strip_src_comments(main_part) + "\n"
                      + json.dumps(fm or {}, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Source index (contract 1: section src)
# ---------------------------------------------------------------------------

class SourceIndex(object):
    """id -> domain for src checks of one batch.

    Known: active/consumed/pending/closed entries of sources.json and this
    batch's non-deleted sources. A merged manual:<page> source stays in
    sources.json as `closed`, so a page may keep citing it; a manual id
    with no record is unknown like any other (never inferred from the id).
    Withdrawn from `domain`: this batch's deleted ops and entries already
    marked deleted in `domain`.
    """

    def __init__(self, entries, batch_sources, domain):
        self.domain = domain
        self.domains = {}
        self.withdrawn = set()
        for source_id, entry in (entries or {}).items():
            status = entry.get("status")
            if (status in ("active", "consumed", "pending", "closed")
                    and entry.get("domain") in common.DOMAINS):
                self.domains[source_id] = entry["domain"]
            elif status == "deleted" and entry.get("domain") == domain:
                self.withdrawn.add(source_id)
        for source in batch_sources:
            if source.get("op") == "deleted":
                if source.get("domain") == domain:
                    self.withdrawn.add(source["id"])
            else:
                self.domains[source["id"]] = source["domain"]
                self.withdrawn.discard(source["id"])

    def known_ids(self):
        """Every id this index knows (withdrawn included): the ids redact
        may exempt inside src comments (fix round 1)."""
        return set(self.domains) | self.withdrawn

    def domain_of(self, source_id):
        """Known domain of a src id, or None. Callers check withdrawn ids
        first."""
        return self.domains.get(source_id)


# ---------------------------------------------------------------------------
# Page catalog
# ---------------------------------------------------------------------------

Page = collections.namedtuple("Page", "path fm body title aliases names")


def iter_page_files(wt, domain):
    base = os.path.join(wt, domain)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                             and d != common.DRAFTS_DIRNAME)
        for name in sorted(filenames):
            if not name.endswith(".md") or name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            yield os.path.relpath(full, wt).replace(os.sep, "/")


_STEM_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def scan_allow(wt, domains_cfg):
    """redact_allow plus the wiki's own page file names long enough to be
    entropy candidates (review round 3). A page name in [[...]] or in text
    is a file path (contract 4) once a page of that name exists; a name
    with a 24+ char high-entropy part is never added."""
    allow = list(domains_cfg.get("redact_allow", []) or [])
    stems = set()
    for domain in common.DOMAINS:
        for rel in iter_page_files(wt, domain):
            stem = rel.rsplit("/", 1)[-1][:-3]
            if (len(stem) >= redact.ENTROPY_MIN_LEN and _STEM_RE.match(stem)
                    and not redact.has_secret_part(stem)):
                stems.add(stem)
    return allow + sorted(stems)


def with_scan_allow(wt, domains_cfg):
    """domains_cfg copy whose redact_allow is scan_allow(wt, domains_cfg)."""
    cfg = dict(domains_cfg)
    cfg["redact_allow"] = scan_allow(wt, domains_cfg)
    return cfg


def load_pages(wt, domain):
    pages = []
    for rel in iter_page_files(wt, domain):
        try:
            text = read_text(os.path.join(wt, rel))
        except (IOError, OSError, UnicodeDecodeError):
            continue
        fm, err, body, _nl = page_split(text)
        if fm is None or err:
            continue
        title = fm.get("title") if isinstance(fm.get("title"), str) else None
        if not title:
            continue
        aliases = []
        if isinstance(fm.get("aliases"), list):
            aliases = [a for a in fm["aliases"] if isinstance(a, str) and a.strip()]
        pages.append(Page(rel, fm, body, title, aliases, [title] + aliases))
    return pages


def page_activity(page):
    dates = src_dates(page.body)
    updated = page.fm.get("updated")
    if isinstance(updated, str) and common.DATE_RE.match(updated[:10]):
        dates.append(updated[:10])
    return max(dates) if dates else ""


def section_text(body, heading):
    """Text of '## <heading>' up to the next '## ' heading (code-aware)."""
    out = []
    inside = False
    fence = None
    for line in body.splitlines(True):
        fence, match = common.fence_step(fence, line)
        if not match and fence is None:
            heading_match = _SECTION_RE.match(line.rstrip("\r\n"))
            if heading_match:
                if inside:
                    break
                inside = heading_match.group(1).strip() == heading
                continue
        if inside:
            out.append(line)
    return "".join(out)


def first_text_line(text):
    for line in strip_fences(text or "").splitlines():
        line = common.SRC_COMMENT_RE.sub("", line).strip()
        line = re.sub(r"^([-*+]|\d+\.)\s+", "", line).strip()
        if line and not line.startswith("<!--") and not line.startswith("#"):
            return line
    return ""


# ---------------------------------------------------------------------------
# Batch verification
# ---------------------------------------------------------------------------

BatchCheck = collections.namedtuple("BatchCheck", "changes pages drafts warnings broken_links")


def _is_gitkeep(path):
    return os.path.basename(path) == ".gitkeep"


def _is_draft(path, domain):
    return path.startswith("%s/%s/" % (domain, common.DRAFTS_DIRNAME))


def _check_page(wt, pre_sha, status, path, domain, index, other, allow, terms, problems,
                other_names=frozenset()):
    """Checks for one changed page. Appends problems; returns True if it is
    a live page (not deleted, not a draft)."""
    full = os.path.join(wt, path)
    old = blob_at(wt, pre_sha, path) if status not in ("?", "A") else None
    old_guard = notes_guard(old.decode("utf-8", "replace")) if old is not None else None
    if status == "D":
        if old_guard is not None:
            if old_guard.startswith(HIDDEN_NOTES_MARK):
                problems.append("my_notes_unlocatable:%s" % path)
            elif old_guard and old_guard.strip() != common.MY_NOTES_HEADING:
                problems.append("my_notes_changed:%s" % path)
        return False
    if not path.endswith(".md"):
        problems.append("non_markdown:%s" % path)
        return False
    data = read_bytes(full)
    if len(data) > MAX_PAGE_BYTES:
        problems.append("page_too_large:%s" % path)
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        problems.append("not_utf8:%s" % path)
        return False
    fm, err, body, _nl = page_split(text)
    if err or fm is None:
        problems.append("frontmatter_invalid:%s" % path)
        return False
    errors = common.validate_page_frontmatter(fm)
    if errors:
        problems.append("frontmatter_invalid:%s:%s" % (path, errors[0]))
    if fm.get("domain") != domain:
        problems.append("page_domain_mismatch:%s" % path)
    main_part, notes = common.split_my_notes(body)
    if old is not None:
        if old_guard.startswith(HIDDEN_NOTES_MARK):
            if not same_notes(old_guard, notes_guard(text)):
                problems.append("my_notes_unlocatable:%s" % path)
        elif not same_notes(old_guard, notes_guard(text)):
            problems.append("my_notes_changed:%s" % path)
    elif notes.strip() not in ("", common.MY_NOTES_HEADING):
        # A page the LLM creates may only end with an empty heading: text
        # under it would count as human-owned from then on (D1, D5, D9).
        problems.append("my_notes_changed:%s" % path)
    for source_id in src_ids(main_part):
        if source_id in index.withdrawn:
            problems.append("src_withdrawn:%s:%s" % (path, source_id))
            continue
        src_domain = index.domain_of(source_id)
        if src_domain is None:
            problems.append("src_unknown:%s:%s" % (path, source_id))
        elif src_domain != domain:
            problems.append("src_cross_domain:%s:%s" % (path, source_id))
    if (crosses_domain(main_part, other, other_names)
            or crosses_domain(fm_strings(fm), other, other_names)):
        problems.append("cross_domain_link:%s" % path)
    if redact.scan(text, allow, index.known_ids()):
        problems.append("secret_found:%s" % path)
    if domain == "personal" and personal_term_hit(terms, path, main_part, fm):
        problems.append("work_terms_hit:%s" % path)
    return True


def check_batch(wt, pre_sha, batch, entries, domains_cfg, extra_sources=()):
    """Verify the LLM's changes for one batch. Returns BatchCheck or raises
    BatchFailure. Does not modify anything. extra_sources are the sources of
    batches that already passed earlier in the same run (their ids are known
    before commit_batch records them)."""
    domain = common.batch_domain(batch["sources"])
    globs = batch["allowed_globs"]
    allow = scan_allow(wt, domains_cfg)
    terms = Terms(domains_cfg.get("work_terms", []))
    index = SourceIndex(entries, list(extra_sources) + list(batch["sources"]), domain)
    other = [d for d in common.DOMAINS if d != domain]
    other_names = set()
    for name in other:
        other_names |= page_basenames(wt, name)
    problems = []
    warnings = []
    changes = changed_files(wt, pre_sha)

    for _status, path in changes:
        if not common.path_allowed(path, globs):
            problems.append("outside_allowed_globs:%s" % path)
            continue
        full = os.path.join(wt, path)
        if os.path.lexists(full):
            mode = os.lstat(full).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                problems.append("not_regular_file:%s" % path)
    if problems:
        raise BatchFailure(problems)

    drafts = {}
    pages = []
    for status, path in changes:
        if _is_draft(path, domain):
            name = path.rsplit("/", 1)[-1]
            if name not in ROOT_DRAFTS or path.count("/") != 2:
                warnings.append("draft_ignored:%s" % path)
                continue
            try:
                text = read_text(os.path.join(wt, path))
            except UnicodeDecodeError:
                problems.append("not_utf8:%s" % path)
                continue
            if len(text) > MAX_DRAFT_CHARS:
                problems.append("draft_too_large:%s" % path)
            if not fences_balanced(text):
                # An open fence would swallow the root file's later
                # sections, '## 내 메모' included, once assembled.
                problems.append("draft_unbalanced_fence:%s" % path)
            if redact.scan(text, allow, index.known_ids()):
                problems.append("secret_found:%s" % path)
            if domain == "personal" and terms.hits(strip_src_comments(text)):
                problems.append("work_terms_hit:%s" % path)
            if crosses_domain(text, other, other_names):
                problems.append("cross_domain_link:%s" % path)
            drafts[name] = text
            continue
        if _is_gitkeep(path):
            full = os.path.join(wt, path)
            if status != "D" and os.path.isfile(full) and os.path.getsize(full) != 0:
                problems.append("gitkeep_not_empty:%s" % path)
            continue
        if _check_page(wt, pre_sha, status, path, domain, index, other, allow, terms, problems,
                       other_names):
            pages.append(path)

    # A source withdrawn from this domain must not stay cited anywhere in it.
    if index.withdrawn:
        for rel in iter_page_files(wt, domain):
            try:
                main_part = before_notes(read_text(os.path.join(wt, rel)))
            except (IOError, OSError, UnicodeDecodeError):
                continue
            for source_id in src_ids(main_part):
                if source_id in index.withdrawn:
                    problems.append("src_withdrawn:%s:%s" % (rel, source_id))
    if problems:
        unique = []
        for problem in problems:
            if problem not in unique:
                unique.append(problem)
        raise BatchFailure(unique)
    broken = count_broken_links(wt, domain, pages)
    return BatchCheck(changes, pages, drafts, warnings, broken)


def count_broken_links(wt, domain, paths):
    broken = 0
    for rel in paths:
        try:
            main_part = before_notes(read_text(os.path.join(wt, rel)))
        except (IOError, OSError, UnicodeDecodeError):
            continue
        for target in link_targets(main_part):
            path = target_path(target)
            if not path or target_domain(target) != domain:
                continue
            if not path.endswith(".md"):
                path += ".md"
            if not os.path.isfile(os.path.join(wt, path)):
                broken += 1
    return broken


def remove_drafts(wt, domain):
    path = os.path.join(wt, domain, common.DRAFTS_DIRNAME)
    if os.path.lexists(path):
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)


def notes_snapshot(wt, paths):
    """{path: '## 내 메모' tail} for re-checking after Python edits."""
    snap = {}
    for rel in paths:
        full = os.path.join(wt, rel)
        if os.path.isfile(full):
            try:
                snap[rel] = notes_guard(read_text(full))
            except UnicodeDecodeError:
                # Not UTF-8 (e.g. a CP949 export): check_batch already failed
                # the batch if the LLM changed it, and Python's alias and
                # link passes skip it (load_pages), so it stays as it is.
                continue
    return snap


def assert_notes_unchanged(wt, snapshot):
    problems = []
    for rel, tail in snapshot.items():
        full = os.path.join(wt, rel)
        try:
            same = os.path.isfile(full) and same_notes(tail, notes_guard(read_text(full)))
        except UnicodeDecodeError:
            same = False
        if not same:
            problems.append("my_notes_changed:%s" % rel)
    if problems:
        raise BatchFailure(problems)


# ---------------------------------------------------------------------------
# Structured output (panel D-6)
# ---------------------------------------------------------------------------

OUTPUT_SCHEMA = collections.OrderedDict([
    ("type", "object"),
    ("additionalProperties", False),
    ("properties", collections.OrderedDict([
        ("pages", {"type": "array", "items": {"type": "string"}}),
        ("merges", {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}),
        ("mentions", {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"name": {"type": "string"},
                           "sources": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "sources"]}}),
        ("withdrawn_src", {"type": "array", "items": {"type": "string"}}),
        ("notes", {"type": "string"}),
    ])),
    ("required", ["pages", "merges", "mentions", "withdrawn_src", "notes"]),
])


def normalize_output(data, wt, batch):
    """Validate the LLM's structured result and normalize it.

    pages come back as absolute paths (measured on 2.1.318); both sides are
    realpath'ed and made relative to the worktree. Mentions keep only ids of
    this batch's non-deleted sources. Raises BatchFailure on a bad shape.
    """
    if not isinstance(data, dict):
        raise BatchFailure(["llm_output_invalid:not an object"])
    for key in ("pages", "merges", "mentions", "withdrawn_src"):
        if not isinstance(data.get(key, []), list):
            raise BatchFailure(["llm_output_invalid:%s" % key])
    wt_real = os.path.realpath(wt)
    pages = []
    for value in data.get("pages") or []:
        if not isinstance(value, str) or not value:
            continue
        full = value if os.path.isabs(value) else os.path.join(wt_real, value)
        real = os.path.realpath(full)
        if real.startswith(wt_real + os.sep):
            pages.append(os.path.relpath(real, wt_real).replace(os.sep, "/"))
    batch_ids = set(s["id"] for s in batch["sources"] if s.get("op") != "deleted")
    mentions = collections.OrderedDict()
    for item in data.get("mentions") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = unicodedata.normalize("NFC", item["name"]).strip()
        ids = [i for i in item.get("sources") or [] if isinstance(i, str) and i in batch_ids]
        if name and ids and len(name) <= 80:
            mentions.setdefault(name, set()).update(ids)
    merges = []
    for group in data.get("merges") or []:
        if isinstance(group, list):
            names = [unicodedata.normalize("NFC", n).strip() for n in group
                     if isinstance(n, str) and n.strip() and len(n.strip()) <= 80]
            if len(names) >= 2:
                merges.append(names)
    withdrawn = [s for s in data.get("withdrawn_src") or [] if isinstance(s, str)]
    notes = data.get("notes") if isinstance(data.get("notes"), str) else ""
    return {"pages": pages, "mentions": mentions, "merges": merges,
            "withdrawn_src": withdrawn, "notes": notes[:2000]}


# ---------------------------------------------------------------------------
# Mentions (D9)
# ---------------------------------------------------------------------------

def merge_groups(groups):
    """Union name groups that share a (folded) name. Returns list of lists."""
    parent = {}
    display = collections.OrderedDict()

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for group in groups:
        keys = []
        for name in group:
            key = fold(name)
            if not key:
                continue
            display.setdefault(key, name)
            parent.setdefault(key, key)
            keys.append(key)
        for key in keys[1:]:
            a, b = find(keys[0]), find(key)
            if a != b:
                parent[b] = a
    buckets = collections.OrderedDict()
    for key in display:
        buckets.setdefault(find(key), []).append(display[key])
    return list(buckets.values())


def mention_groups(mentions, merges):
    """[(names, ids)] for one domain: names merged by the LLM count together."""
    groups = merge_groups([[name] for name in mentions] + list(merges))
    folded = {}
    for name, ids in mentions.items():
        folded.setdefault(fold(name), set()).update(ids)
    result = []
    for names in groups:
        ids = set()
        for name in names:
            ids |= folded.get(fold(name), set())
        result.append((names, ids))
    return result


def update_mentions(sources_data, domain, mentions, merges):
    """Accumulate one batch's mentions into a sources.json dict (in place)."""
    store = sources_data.setdefault("mentions", collections.OrderedDict())
    block = store.setdefault(domain, collections.OrderedDict())
    for name, ids in mentions.items():
        block[name] = sorted(set(block.get(name) or []) | set(ids))
    groups_store = sources_data.setdefault("mention_groups", collections.OrderedDict())
    existing = groups_store.get(domain) or []
    groups_store[domain] = [g for g in merge_groups(list(existing) + list(merges)) if len(g) >= 2]


def stored_mentions(sources_data, domain):
    block = (sources_data.get("mentions") or {}).get(domain) or {}
    mentions = collections.OrderedDict((name, set(ids)) for name, ids in block.items())
    merges = (sources_data.get("mention_groups") or {}).get(domain) or []
    return mentions, merges


def promotions(mentions, merges, pages):
    """Name groups with >= 3 sources: [(names, count, existing page or None)]."""
    by_name = {}
    for page in pages:
        for name in page.names:
            by_name.setdefault(fold(name), page.path)
    result = []
    for names, ids in mention_groups(mentions, merges):
        if len(ids) < PROMOTE_MIN_SOURCES:
            continue
        page = None
        for name in names:
            page = page or by_name.get(fold(name))
        result.append((names, len(ids), page))
    return result


def clean_name(name, domain, terms, allow):
    """A merge or mention name may enter frontmatter and caches only when it
    carries no contract-4 secret and, in personal, no work_terms (D5)."""
    if redact.scan(name, allow):
        return False
    return not (domain == "personal" and terms.hits(name))


def clean_groups(groups, domain, terms, allow):
    """Name groups with unclean names dropped (groups left with < 2 names
    disappear)."""
    out = []
    for names in groups:
        kept = [name for name in names if clean_name(name, domain, terms, allow)]
        if len(kept) >= 2:
            out.append(kept)
    return out


def clean_mentions(mentions, domain, terms, allow):
    return collections.OrderedDict((name, ids) for name, ids in mentions.items()
                                   if clean_name(name, domain, terms, allow))


def known_source_ids(entries, extra_sources=()):
    """sources.json ids plus this run's batch source ids: what redact may
    exempt inside src comments (fix round 1)."""
    ids = set(entries or {})
    ids.update(source["id"] for source in extra_sources or () if source.get("id"))
    return ids


def recheck_pages(wt, domain, paths, domains_cfg, known_ids=None):
    """Contract-4 and (personal) work_terms check, frontmatter included, of
    pages Python changed after check_batch (aliases, links). Raises
    BatchFailure."""
    allow = scan_allow(wt, domains_cfg)
    terms = Terms(domains_cfg.get("work_terms", []))
    other = [d for d in common.DOMAINS if d != domain]
    other_names = set()
    for name in other:
        other_names |= page_basenames(wt, name)
    problems = []
    for rel in sorted(set(paths)):
        full = os.path.join(wt, rel)
        if not os.path.isfile(full):
            continue
        try:
            text = read_text(full)
        except UnicodeDecodeError:
            problems.append("page_unreadable:%s" % rel)
            continue
        if redact.scan(text, allow, known_ids):
            problems.append("secret_found:%s" % rel)
        fm, _err, body, _nl = page_split(text)
        main_part = common.split_my_notes(body)[0]
        if (crosses_domain(main_part, other, other_names)
                or crosses_domain(fm_strings(fm), other, other_names)):
            problems.append("cross_domain_link:%s" % rel)
        if domain == "personal" and personal_term_hit(terms, rel, main_part, fm):
            problems.append("work_terms_hit:%s" % rel)
    if problems:
        raise BatchFailure(problems)


def sync_aliases(wt, domain, groups, terms=None):
    """Add every merged name to the aliases of the page that already holds
    one of them (D9). Python edits frontmatter only. Returns changed paths.
    A personal page whose path hits work_terms is never edited: the edit
    would fail recheck_pages on every run (stored groups persist)."""
    changed = []
    pages = load_pages(wt, domain)
    if domain == "personal" and terms is not None:
        pages = [page for page in pages if not terms.hits(page.path)]
    for page in pages:
        have = set(fold(name) for name in page.names)
        missing = []
        for names in groups:
            if have & set(fold(name) for name in names):
                for name in names:
                    if fold(name) not in have and fold(name) not in [fold(m) for m in missing]:
                        missing.append(name)
        if not missing:
            continue
        full = os.path.join(wt, page.path)
        fm, err, body, newline = page_split(read_text(full))
        if fm is None or err:
            continue
        aliases = list(fm.get("aliases") or []) if isinstance(fm.get("aliases"), list) else []
        fm["aliases"] = aliases + missing
        common.atomic_write_text(full, common.render_page(fm, body, newline))
        changed.append(page.path)
    return changed


# ---------------------------------------------------------------------------
# Link conversion (D9): skips '## 내 메모', code, frontmatter, headings
# ---------------------------------------------------------------------------

def _name_regex(name):
    name = name.strip()
    if len(unicodedata.normalize("NFKC", name)) < MIN_LINK_NAME or "\n" in name:
        return None
    escaped = re.escape(name)
    if _HANGUL_RE.search(name):
        return re.compile(escaped, re.IGNORECASE)
    return re.compile(r"(?<![0-9A-Za-z_])" + escaped + r"(?![0-9A-Za-z_])", re.IGNORECASE)


def _link_once(text, regexes, link_target):
    """Replace the first unprotected match of any of regexes in text (the
    earliest position wins, the longer name on a tie). (text, done)."""
    lines = text.splitlines(True)
    fence = None
    for index, line in enumerate(lines):
        fence, match = common.fence_step(fence, line)
        if match:
            continue
        if fence or _HEADING_RE.match(line) or line.lstrip().startswith("<!--"):
            continue
        pos = 0
        pieces = []
        for protected in _PROTECT_RE.finditer(line):
            pieces.append((line[pos:protected.start()], False))
            pieces.append((protected.group(0), True))
            pos = protected.end()
        pieces.append((line[pos:], False))
        out = []
        done = False
        for chunk, is_protected in pieces:
            if not done and not is_protected:
                found = None
                for regex in regexes:
                    candidate = regex.search(chunk)
                    if candidate and (found is None or candidate.start() < found.start()
                                      or (candidate.start() == found.start()
                                          and candidate.end() > found.end())):
                        found = candidate
                if found:
                    chunk = "%s[[%s|%s]]%s" % (chunk[:found.start()], link_target,
                                               found.group(0), chunk[found.end():])
                    done = True
            out.append(chunk)
        if done:
            lines[index] = "".join(out)
            return "".join(lines), True
    return text, False


def convert_links(text, targets, self_path):
    """Link the first plain mention of each same-domain page in text.

    targets: [(names, page_path)]. The frontmatter and the '## 내 메모' tail
    are copied byte-for-byte; code blocks, inline code, existing links,
    comments, URLs and headings are skipped. A page already linked is not
    linked again.
    """
    try:
        _fm_text, body, _newline = common.split_frontmatter(text)
    except common.FrontmatterError:
        return text
    head = text[:len(text) - len(body)]
    main_part, notes = common.split_my_notes(body)
    for names, page_path in targets:
        if page_path == self_path:
            continue
        target = page_path[:-3] if page_path.endswith(".md") else page_path
        if "[[%s" % target in main_part or "(%s)" % page_path in main_part:
            continue
        regexes = [r for r in (_name_regex(name) for name in names) if r is not None]
        if regexes:
            main_part, _done = _link_once(main_part, regexes, target)
    return head + main_part + notes


def link_pages(wt, domain, paths, terms=None):
    """Run link conversion on the given pages. Returns changed paths.

    A personal page whose path hits work_terms (a human can name a file
    that way in Obsidian) is never a link target: the link would put the
    term into the linking page and fail recheck_pages on every run."""
    pages = load_pages(wt, domain)
    if domain == "personal" and terms is not None:
        pages = [page for page in pages if not terms.hits(page.path)]
    targets = sorted(((page.names, page.path) for page in pages),
                     key=lambda item: -max(len(n) for n in item[0]))
    changed = []
    for rel in paths:
        full = os.path.join(wt, rel)
        if not os.path.isfile(full):
            continue
        try:
            text = read_text(full)
        except UnicodeDecodeError:
            continue
        new = convert_links(text, targets, rel)
        if new != text:
            common.atomic_write_text(full, new)
            changed.append(rel)
    return changed


# ---------------------------------------------------------------------------
# Generated files: index.md, root now.md / about-me.md, paused status
# ---------------------------------------------------------------------------

def build_index(wt, now, terms=None):
    """index.md. Personal pages whose path hits work_terms are left out."""
    lines = ["# 위키 색인", "",
             "absorb가 실행마다 다시 만든다. 직접 고치지 않는다. (%s)"
             % now.strftime("%Y-%m-%d %H:%M"), ""]
    for domain, subdirs in common.DOMAIN_SUBDIRS.items():
        lines += ["## %s" % domain, ""]
        pages = load_pages(wt, domain)
        if domain == "personal" and terms is not None:
            pages = [page for page in pages if not terms.hits(page.path)]
        for sub in subdirs:
            group = [p for p in pages if p.path.startswith("%s/%s/" % (domain, sub))]
            if not group:
                continue
            lines += ["### %s" % sub, ""]
            for page in sorted(group, key=lambda p: fold(p.title)):
                summary = page.fm.get("summary") if isinstance(page.fm.get("summary"), str) else ""
                first = first_text_line(summary)
                item = "- [[%s|%s]]" % (page.path[:-3], page.title.replace("|", "/"))
                if first:
                    item += " — " + first
                lines.append(item)
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _split_sections(text):
    """(preface, [(heading, body)]) for '## ' sections, code-aware."""
    preface = []
    sections = []
    fence = None
    for line in text.splitlines(True):
        fence, match = common.fence_step(fence, line)
        heading = None
        if not match and fence is None:
            heading = _SECTION_RE.match(line.rstrip("\r\n"))
        if heading:
            sections.append([heading.group(1).strip(), []])
        elif sections:
            sections[-1][1].append(line)
        else:
            preface.append(line)
    return "".join(preface), [(h, "".join(b)) for h, b in sections]


def _demote(text):
    """Fragment headings: drop a leading '# ' title, '## x' -> '### x'."""
    out = []
    fence = None
    for line in text.splitlines(True):
        fence, match = common.fence_step(fence, line)
        if not match and fence is None:
            if re.match(r"^# ", line):
                continue
            if re.match(r"^#{2,5} ", line):
                line = "#" + line
        out.append(line)
    return "".join(out).strip("\n")


def _fragment_body(text, domain):
    """A now.md fragment without a wrapping '## <domain>' heading."""
    preface, sections = _split_sections(text)
    if (len(sections) == 1 and sections[0][0] == domain
            and not preface.replace("#", "").strip()):
        return sections[0][1]
    return text


def recent_decisions(wt, now, days=30, limit=10):
    since = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    items = []
    for domain in common.DOMAINS:
        for page in load_pages(wt, domain):
            if page.fm.get("type") != "decision":
                continue
            decided = page.fm.get("decided")
            if isinstance(decided, str) and decided[:10] >= since:
                items.append((decided[:10], domain, page))
    items.sort(key=lambda item: (item[0], item[2].path), reverse=True)
    return ["- %s · %s · [[%s|%s]]" % (d, domain, p.path[:-3], p.title.replace("|", "/"))
            for d, domain, p in items[:limit]]


def _root_parts(current):
    _fm_text, body, _nl = common.split_frontmatter(current)
    head = current[:len(current) - len(body)]
    main_part, notes = common.split_my_notes(body)
    preface, sections = _split_sections(main_part)
    return head, preface, sections, notes


def assemble_now(current, fragments, decisions):
    """Root now.md from per-domain fragments; '## 내 메모' kept byte-for-byte.
    A domain without a fragment keeps its current section text."""
    head, preface, sections, notes = _root_parts(current)
    existing = dict(sections)
    parts = [preface.rstrip("\n") + "\n"]
    for domain in common.DOMAINS:
        text = fragments.get(domain)
        parts.append("\n## %s\n" % domain)
        if text and text.strip():
            parts.append("\n" + _demote(_fragment_body(text, domain)) + "\n")
        elif existing.get(domain, "").strip():
            parts.append("\n" + existing[domain].strip("\n") + "\n")
    parts.append("\n## 최근 결정\n")
    if decisions:
        parts.append("\n" + "\n".join(decisions) + "\n")
    if notes:
        parts.append("\n")
    return head + "".join(parts) + notes


def _split_subsections(body):
    """(preface, {name: text}) for '### ' subsections of one section."""
    preface = []
    subs = collections.OrderedDict()
    current = None
    for line in body.splitlines(True):
        match = re.match(r"^### (.+?)\s*$", line.rstrip("\r\n"))
        if match:
            current = match.group(1).strip()
            subs[current] = ""
        elif current is None:
            preface.append(line)
        else:
            subs[current] += line
    return "".join(preface), subs


def assemble_about_me(current, fragments):
    """Root about-me.md: each section gathers '### <domain>' parts from the
    domains' fragments; '## 내 메모' kept byte-for-byte. A domain without a
    fragment keeps its current part."""
    head, preface, sections, notes = _root_parts(current)
    headings = [h for h, _b in sections]
    for wanted in ABOUT_ME_SECTIONS:
        if wanted not in headings:
            headings.append(wanted)
    current_parts = {}
    for heading, body in sections:
        current_parts[heading] = _split_subsections(body)[1]
    by_domain = {}
    for domain, text in fragments.items():
        by_domain[domain] = dict(_split_sections(text or "")[1])
    parts = [preface.rstrip("\n") + "\n"]
    for heading in headings:
        parts.append("\n## %s\n" % heading)
        for domain in common.DOMAINS:
            if domain in by_domain:
                section = _demote(by_domain[domain].get(heading, ""))
            else:
                section = current_parts.get(heading, {}).get(domain, "").strip("\n")
            if section.strip():
                parts.append("\n### %s\n\n%s\n" % (domain, section))
    if notes:
        parts.append("\n")
    return head + "".join(parts) + notes


def apply_paused(wt, now):
    """Project pages without a new source for 21 days get status: paused."""
    cutoff = (now - datetime.timedelta(days=PAUSED_DAYS)).strftime("%Y-%m-%d")
    changed = []
    for domain in common.DOMAINS:
        for page in load_pages(wt, domain):
            if page.fm.get("type") != "project" or page.fm.get("status") != "active":
                continue
            activity = page_activity(page)
            if not activity or activity >= cutoff:
                continue
            full = os.path.join(wt, page.path)
            fm, err, body, newline = page_split(read_text(full))
            if fm is None or err:
                continue
            fm["status"] = "paused"
            common.atomic_write_text(full, common.render_page(fm, body, newline))
            changed.append(page.path)
    return changed


def scan_tree(wt, allow, known_ids=None):
    """Contract 4 over the whole wiki tree (worktree files, .git excluded).
    Returns ['<path>:<kinds>'] for every hit."""
    hits = []
    for dirpath, dirnames, filenames in os.walk(wt):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            if name == ".git":
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not name.endswith(TEXT_SUFFIXES):
                continue
            try:
                text = read_text(full)
            except (IOError, OSError, UnicodeDecodeError):
                continue
            kinds = redact.scan(text, allow, known_ids)
            if kinds:
                rel = os.path.relpath(full, wt).replace(os.sep, "/")
                hits.append("%s:%s" % (rel, ",".join(sorted(kinds))))
    return hits


# ---------------------------------------------------------------------------
# Caches (references/caches.md) and the rules file (D12)
# ---------------------------------------------------------------------------

def iso_now(now):
    if now.tzinfo is None:
        now = now.astimezone()
    return now.replace(microsecond=0).isoformat()


def _str_list(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _section_srcs(text):
    return [(m.group(1), m.group(2)) for m in common.SRC_COMMENT_RE.finditer(strip_fences(text))]


def _handoff_expired(text, cutoff):
    """True when every src of text is a handoff source older than cutoff
    (and there is at least one)."""
    srcs = _section_srcs(text)
    return bool(srcs) and all(i.startswith("handoff:") and d < cutoff for i, d in srcs)


_ITEM_START_RE = re.compile(r"^ {0,3}(?:[-*+]|\d+[.)])\s")


def _state_blocks(text):
    """Split a section into blocks: a list item (marker line plus its
    continuation lines) or a paragraph; blank lines are separate one-line
    blocks. Fenced code stays inside the block it starts in."""
    blocks = []
    current = []
    fence = None
    for line in text.splitlines(True):
        if fence is not None:
            current.append(line)
            fence, _match = common.fence_step(fence, line)
            continue
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            blocks.append([line])
            continue
        if _ITEM_START_RE.match(line) and current:
            blocks.append(current)
            current = []
        current.append(line)
        fence, _match = common.fence_step(fence, line)
    if current:
        blocks.append(current)
    return blocks


def _line_indent(line):
    return len(line) - len(line.lstrip(" "))


def _src_only(text):
    return bool(common.SRC_COMMENT_RE.search(text)) and not common.SRC_COMMENT_RE.sub(
        "", text).strip()


def _state_units(text):
    """Blocks grouped into the units D10 expires together (review round 3):
    a block holding only src comments belongs to the content block before
    it (an LLM often leaves a blank line between an item and its src), and
    an item or line indented deeper than the list item before it is that
    item's child or continuation. Blank lines between units stay their own
    units. Returns a list of strings."""
    units = []  # [is_content, base_indent or None, text]
    pending = []
    for block in _state_blocks(text):
        joined = "".join(block)
        if not joined.strip():
            pending.append(joined)
            continue
        first = block[0]
        item = _ITEM_START_RE.match(first) or re.match(r"^ *(?:[-*+]|\d+[.)])\s", first)
        attach = False
        if units and units[-1][0]:
            base = units[-1][1]
            if _src_only(joined):
                attach = True
            elif base is not None and _line_indent(first) > base:
                attach = True
        if attach:
            units[-1][2] += "".join(pending) + joined
        else:
            units.extend([False, None, b] for b in pending)
            units.append([True, _line_indent(first) if item else None, joined])
        pending = []
    units.extend([False, None, b] for b in pending)
    return [unit[2] for unit in units]


def _expire_items(text, cutoff):
    """D10 per item: drop each unit of text (see _state_units) whose srcs
    are all handoff sources older than cutoff. Units without a src stay
    (they cannot be dated). Returns the new text (unchanged when nothing
    expired)."""
    kept = []
    dropped = False
    for joined in _state_units(text):
        if joined.strip() and _handoff_expired(joined, cutoff):
            dropped = True
            continue
        kept.append(joined)
    if not dropped:
        return text
    out = []
    for piece in kept:
        if not piece.strip() and out and not out[-1].strip():
            continue  # collapse the blank lines a dropped block leaves
        out.append(piece)
    while len(out) > 1 and not out[-1].strip() and not out[-2].strip():
        out.pop()
    return "".join(out)


def _replace_section(body, heading, new_text):
    """body with the text of '## <heading>' (up to the next '## ' heading,
    code-aware) replaced by new_text. The heading line itself stays."""
    out = []
    state = "before"  # before -> inside -> after
    fence = None
    for line in body.splitlines(True):
        fence, match = common.fence_step(fence, line)
        is_heading = None
        if not match and fence is None:
            is_heading = _SECTION_RE.match(line.rstrip("\r\n"))
        if state == "before" and is_heading and is_heading.group(1).strip() == heading:
            out.append(line)
            out.append(new_text)
            state = "inside"
            continue
        if state == "inside":
            if is_heading:
                state = "after"
            else:
                continue
        out.append(line)
    return "".join(out)


def expire_handoff_state(wt, now):
    """D10: each item (list item or paragraph, see _state_units) of a
    project's '## 현재 상태' whose srcs are all handoff sources older than
    14 days is dropped; a section left with nothing is emptied (heading
    kept). Units without a src stay. '## 내 메모' is never touched.
    Returns changed paths."""
    cutoff = (now - datetime.timedelta(days=AS_OF_DAYS)).strftime("%Y-%m-%d")
    heading = common.CURRENT_STATE_HEADING[3:]
    changed = []
    for domain in common.DOMAINS:
        for page in load_pages(wt, domain):
            if page.fm.get("type") != "project":
                continue
            main_part, _notes = common.split_my_notes(page.body)
            state = section_text(main_part, heading)
            if not state.strip():
                continue
            # Always per unit (fix round 1): a line without a src cannot be
            # dated, so it stays even when every dated unit is stale (D1).
            new_state = _expire_items(state, cutoff)
            if new_state == state:
                continue
            if not new_state.strip():
                new_state = "\n"
            full = os.path.join(wt, page.path)
            text = read_text(full)
            _fm_text, body, _nl = common.split_frontmatter(text)
            head = text[:len(text) - len(body)]
            before, notes = common.split_my_notes(body)
            new = head + _replace_section(before, heading, new_state) + notes
            if new != text:
                common.atomic_write_text(full, new)
                changed.append(page.path)
    return changed


def _project_entry(page, now):
    entry = collections.OrderedDict()
    entry["title"] = page.title
    entry["page"] = page.path
    entry["repos"] = _str_list(page.fm.get("repos"))
    entry["status"] = page.fm.get("status") or "active"
    summary = page.fm.get("summary") if isinstance(page.fm.get("summary"), str) else ""
    as_of = page.fm.get("as_of")
    if isinstance(as_of, str) and common.DATE_RE.match(as_of[:10]):
        cutoff = (now - datetime.timedelta(days=AS_OF_DAYS)).strftime("%Y-%m-%d")
        state = section_text(common.split_my_notes(page.body)[0],
                             common.CURRENT_STATE_HEADING[3:])
        fresh = any(d >= cutoff for _i, d in _section_srcs(state))
        if as_of[:10] < cutoff and not fresh:
            # D10: a handoff state expires after 14 days, unless the state
            # was refreshed from a newer source since.
            summary = ""
    entry["summary"] = summary.strip()
    entry["this_week"] = first_text_line(section_text(page.body, "이번 주 무엇을 왜"))
    return entry


def _pref_entry(page):
    entry = collections.OrderedDict()
    entry["title"] = page.title
    entry["page"] = page.path
    entry["scope"] = page.fm.get("scope") or "domain"
    entry["repos"] = _str_list(page.fm.get("repos"))
    summary = page.fm.get("summary") if isinstance(page.fm.get("summary"), str) else ""
    entry["text"] = first_text_line(summary) or first_text_line(section_text(page.body, "선호"))
    return entry


def _clean_entry(entry, allow, terms, domain):
    blob = json.dumps(entry, ensure_ascii=False)
    if redact.scan(blob, allow):
        return False
    return not (domain == "personal" and terms.hits(blob))


def _desc(date_text):
    """Sort key for descending YYYY-MM-DD strings."""
    return tuple(-ord(ch) for ch in date_text)


def build_context_cache(wt, domains_cfg, run_id, now, pending=None):
    allow = domains_cfg.get("redact_allow", [])
    terms = Terms(domains_cfg.get("work_terms", []))
    cache = collections.OrderedDict()
    cache["version"] = 1
    cache["generated_at"] = iso_now(now)
    cache["as_of"] = now.strftime("%Y-%m-%d %H:%M")
    cache["run_id"] = run_id
    cache["owners"] = collections.OrderedDict(domains_cfg.get("owners") or {})
    blocks = collections.OrderedDict()
    for domain in common.DOMAINS:
        projects = []
        prefs = []
        for page in load_pages(wt, domain):
            kind = page.fm.get("type")
            if kind == "project":
                entry = _project_entry(page, now)
                if _clean_entry(entry, allow, terms, domain):
                    projects.append((page_activity(page), entry))
            elif kind == "pref" and (page.fm.get("scope") or "domain") in ("domain", "repo"):
                entry = _pref_entry(page)
                if _clean_entry(entry, allow, terms, domain):
                    prefs.append(entry)
        projects.sort(key=lambda item: (item[1]["status"] == "paused", not item[0],
                                        _desc(item[0]), fold(item[1]["title"])))
        block = collections.OrderedDict()
        block["projects"] = [entry for _activity, entry in projects]
        block["prefs"] = sorted(prefs, key=lambda e: fold(e["title"]))
        blocks[domain] = block
    cache["domains"] = blocks
    if pending is not None:
        cache["pending"] = pending
    return cache


def build_alias_cache(wt, now, domains_cfg=None):
    """Per-domain page names for the prompt nudge. Names hitting a secret
    or (personal) work_terms are left out, as in the context cache."""
    domains_cfg = domains_cfg or {}
    allow = domains_cfg.get("redact_allow", [])
    terms = Terms(domains_cfg.get("work_terms", []))
    cache = collections.OrderedDict()
    cache["version"] = 1
    cache["generated_at"] = iso_now(now)
    blocks = collections.OrderedDict()
    for domain in common.DOMAINS:
        entries = []
        for page in load_pages(wt, domain):
            if not clean_name(page.title, domain, terms, allow) or not clean_name(
                    page.path, domain, terms, allow):
                continue
            entry = collections.OrderedDict()
            entry["page"] = page.path
            entry["title"] = page.title
            entry["aliases"] = [name for name in page.aliases
                                if clean_name(name, domain, terms, allow)]
            entries.append(entry)
        blocks[domain] = entries
    cache["domains"] = blocks
    return cache


def write_cache(path, data, domains_cfg):
    """Atomic 0600 write after a contract-4 scan of the whole document.
    Returns False (and keeps the old file) when the scan hits."""
    text = common.dumps_json(data)
    if redact.scan(text, domains_cfg.get("redact_allow", [])):
        return False
    common.ensure_private_dir(os.path.dirname(path))
    common.atomic_write_text(path, text, mode=0o600)
    return True


def _known_personal(source_id, entries):
    entry = (entries or {}).get(source_id) or {}
    return (entry.get("domain") == "personal"
            and entry.get("status") in ("active", "consumed", "closed"))


def rules_lines(wt, domains_cfg, entries=None):
    """Domain-neutral preference lines for the rules file (D12, panel).

    Only personal pref pages with scope: global and at least one src
    (verify guarantees every src of a personal page is a personal source).
    With entries (sources.json), at least one src must be a personal source
    sources.json actually records, so a cited id nobody recorded never
    promotes a line into the file every session loads.
    Work pages never feed the rules file. Each line is checked on its own:
    contract-4 secrets and work_terms (NFKC + casefold) drop the line.
    Lines are capped in count, length and total size.
    """
    allow = domains_cfg.get("redact_allow", [])
    terms = Terms(domains_cfg.get("work_terms", []))
    lines = []
    total = 0
    for page in sorted(load_pages(wt, "personal"), key=lambda p: fold(p.title)):
        if page.fm.get("type") != "pref" or page.fm.get("scope") != "global":
            continue
        cited = src_ids(common.split_my_notes(page.body)[0])
        if not cited:
            continue
        if entries is not None and not any(_known_personal(i, entries) for i in cited):
            continue
        summary = page.fm.get("summary") if isinstance(page.fm.get("summary"), str) else ""
        text = first_text_line(summary) or first_text_line(section_text(page.body, "선호"))
        text = " ".join(text.split())
        if not text:
            continue
        line = "- %s" % text
        if len(line) > RULES_MAX_LINE_CHARS or line in lines:
            continue
        if (redact.scan(line, allow) or terms.hits(line) or terms.hits(page.title)
                or terms.hits(page.path)):
            continue
        if len(lines) >= RULES_MAX_LINES or total + len(line) + 1 > RULES_MAX_CHARS:
            break
        lines.append(line)
        total += len(line) + 1
    return lines


def rules_text(lines):
    return RULES_HEADER + "\n".join(lines) + ("\n" if lines else "")


def write_rules(path, lines, backup_dir, run_id):
    """Write the rules file when it changes; back up the old one first.
    Returns (added, removed) line counts."""
    text = rules_text(lines)
    old_lines = []
    if os.path.isfile(path):
        old = read_text(path)
        if old == text:
            return 0, 0
        old_lines = [line for line in old.splitlines() if line.startswith("- ")]
        common.ensure_private_dir(backup_dir)
        backup = os.path.join(backup_dir, "wiki-prefs.%s.md" % run_id)
        common.atomic_write_text(backup, old, mode=0o600)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, 0o700)
    common.atomic_write_text(path, text, mode=0o644)
    added = len([line for line in lines if line not in old_lines])
    removed = len([line for line in old_lines if line not in lines])
    return added, removed
