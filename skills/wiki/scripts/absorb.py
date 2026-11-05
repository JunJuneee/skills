"""absorb (T3): prepare -> isolated LLM step -> verify -> merge.
Python 3.9, stdlib only.

One run, under the absorb lock (D6):

  1. prepare (T2): human edits committed, sources diffed and redacted,
     staging/<batch>/ and .state/run.json written. base_sha = main HEAD.
  2. a fresh detached git worktree WIKI_ROOT/.absorb-wt at base_sha (D7).
  3. per batch: staging sealed (files 0444, directories 0555), then the LLM
     step as an isolated `claude -p` (panel D-1/D-2):
       cwd .absorb-wt/<domain>/, --add-dir staging/<batch> only,
       --restricted --strict-mcp-config --setting-sources "" --tools
       Read,Edit,Write,Glob,Grep --permission-mode acceptEdits
       --permission-prompts none --no-session-persistence
       --output-format json --json-schema <D-6 schema> --model <settings>
       --max-budget-usd <settings>; the prompt on stdin; env -i style
       environment (HOME, USER, PATH, LLM_WIKI_HOOK=0, plus
       CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 and CLAUDE_CODE_DISABLE_CLAUDE_MDS=1).
     The claude binary is probed with --help first; a missing flag fails
     the run (claude_flags_missing) instead of running with weaker
     isolation. Then verify (verify.py). A failed batch is reset in the
     worktree only; its sources are offered again next run. Before the
     reset, the files it changed are kept, redacted, under
     .state/failed/<run_id>/<batch_id>/ with failure.json (last 5 runs).
  4. deferral (D7, per batch): a file whose working-tree bytes in main
     differ from base_sha (Obsidian edits are uncommitted) keeps main's
     version; every batch touching it is deferred whole.
  5. index.md, root now.md/about-me.md, paused status and a log.md line,
     then a whole-tree secret scan (contract 4) and `merge --ff-only`.
     If main moved, the run fails (main_moved). If the merged files do not
     match, only the absorb-touched files that still hold absorb's bytes
     are rolled back; a file a person wrote meanwhile is left alone.
  6. after the merge: source state advanced for merged batches
     (prepare.commit_batch / finalize_run), mentions stored, caches written
     to main's .state/, the rules file written (D12 default
     ~/.claude/rules/wiki-prefs.md, resolved from the environ passed in:
     $WIKI_RULES_PATH, else $CLAUDE_CONFIG_DIR/rules/, else
     $HOME/.claude/rules/), .state/last-absorb updated.

The LLM step is injectable (`runner`) so tests never call a real model.
"""

import collections
import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import common  # noqa: E402
import prepare  # noqa: E402
import redact  # noqa: E402
import verify  # noqa: E402

SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
PROMPT_TEMPLATE = "absorb_prompt.md"
LAST_ABSORB = "last-absorb"
LAST_REPORT = "last-report.json"
DRAFTS_STORE = "drafts"
BACKUPS_DIR = "backups"
RULES_FILENAME = "wiki-prefs.md"
# .state/<this>: {realpath of a rules file: sha256 of the text absorb last
# wrote there} (fix round 2: the rules file is trusted by provenance).
RULES_RECORD = "rules-written.json"
RUNNING_FILE = "absorb-running.json"
# .state/<this>/<run_id>/<batch_id>/: a failed batch's draft, redacted (fix
# round 3, I-3: a failure used to leave nothing to diagnose).
FAILED_DIR = "failed"
FAILED_KEEP_RUNS = 5

LLM_TOOLS = "Read,Edit,Write,Glob,Grep"
REQUIRED_FLAGS = (
    "--print", "--restricted", "--strict-mcp-config", "--setting-sources", "--tools",
    "--add-dir", "--permission-mode", "--permission-prompts", "--no-session-persistence",
    "--output-format", "--json-schema", "--model", "--max-budget-usd",
)
REQUIRED_HELP_WORDS = ("acceptEdits", '"none"')
DEFAULT_LLM_TIMEOUT = 1800
PROBE_TIMEOUT = 30
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_FAILED = "failed"
STATUS_HELD = "held"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def templates_dir():
    """templates/ next to the scripts (flat .bin/<ver>/ copy) or in the skill."""
    for candidate in (os.path.join(SCRIPTS_DIR, "templates"), os.path.join(SKILL_DIR, "templates")):
        if os.path.isdir(candidate):
            return candidate
    raise common.WikiError("templates_missing", "templates/ not found next to %s" % SCRIPTS_DIR)


def read_template(name):
    with open(os.path.join(templates_dir(), name), "r", encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------------------
# The isolated LLM step (panel D-1, D-2, D-6)
# ---------------------------------------------------------------------------

def resolve_claude(settings, environ):
    """settings.claude_path (absolute, pinned by schedule install), else
    `claude` on PATH."""
    path = settings.get("claude_path") or ""
    if not path:
        path = shutil.which("claude", path=environ.get("PATH") or os.defpath) or ""
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise common.WikiError("claude_missing", "no executable claude found (settings.claude_path)")
    return os.path.abspath(path)


def llm_env(environ, claude_path):
    """Minimal environment for the LLM subprocess (env -i style).

    CLAUDE_CODE_DISABLE_AUTO_MEMORY and CLAUDE_CODE_DISABLE_CLAUDE_MDS are
    belt-and-braces next to --setting-sources "" (measured on 2.1.318 and
    2.1.285: a project CLAUDE.md and a project .claude/rules canary were
    visible without the flags and hidden by the flags alone and by
    CLAUDE_CODE_DISABLE_CLAUDE_MDS alone; the user CLAUDE.md was hidden
    too; fix round 1, scripts/isolation_probe.py: the user CLAUDE.md, user
    rules (nested and symlinked) and auto-memory canaries a plain
    `claude -p` showed were hidden by the flags alone and by the env
    alone, see SKILL.md).
    CLAUDE_CONFIG_DIR is passed through only so a non-default login works.
    """
    home = environ.get("HOME") or os.path.expanduser("~")
    path = [os.path.dirname(claude_path)] + [p for p in SYSTEM_PATH
                                             if p != os.path.dirname(claude_path)]
    env = {
        "HOME": home,
        "USER": environ.get("USER") or os.path.basename(home.rstrip("/")) or "wiki",
        "PATH": ":".join(path),
        "LLM_WIKI_HOOK": "0",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    }
    if environ.get("CLAUDE_CONFIG_DIR"):
        env["CLAUDE_CONFIG_DIR"] = environ["CLAUDE_CONFIG_DIR"]
    return env


def foreign_user_rules(environ, rules_path=None, root=None, terms=None):
    """Number of .md files in the user rules folder the LLM's claude would
    see (CLAUDE_CONFIG_DIR, else HOME/.claude; llm_env passes both),
    symlinked folders included, other than the wiki's own rules file
    (_own_rules_file: needs the wiki root's RULES_RECORD and the work_terms
    matcher; without root every file counts). scripts/isolation_probe.py
    measured that folder hidden from the model on 2.1.318 by two
    independent layers; any other rules file (an employer's workflow
    rules, say) could still carry work text into a personal batch if a
    later claude loaded it, so personal batches keep refusing to run while
    such files exist (user_rules_unisolated, belt-and-braces)."""
    config = (environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    if not config:
        home = environ.get("HOME") or os.path.expanduser("~")
        config = os.path.join(home, ".claude")
    base = os.path.join(config, "rules")
    if not os.path.isdir(base):
        return 0
    count = 0
    own = [os.path.join(base, RULES_FILENAME)] + ([rules_path] if rules_path else [])
    own = set(os.path.realpath(path) for path in own)
    record = read_rules_record(root) if root else {}
    # followlinks (fix round 1): shared or employer rules are typically a
    # symlinked folder; visited realpaths stop a symlink loop.
    visited = set()
    for dirpath, dirnames, filenames in os.walk(base, followlinks=True):
        real_dir = os.path.realpath(dirpath)
        if real_dir in visited:
            dirnames[:] = []
            continue
        visited.add(real_dir)
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.endswith(".md"):
                continue
            full = os.path.join(dirpath, name)
            if os.path.realpath(full) in own and _own_rules_file(full, record, terms):
                continue
            count += 1
    return count


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_rules_record(root):
    """{realpath: sha256} from .state/RULES_RECORD ({} when missing or bad)."""
    try:
        with open(os.path.join(common.state_dir(root), RULES_RECORD), "r",
                  encoding="utf-8") as handle:
            data = json.load(handle)
    except (IOError, OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return dict((key, value) for key, value in data.items()
                if isinstance(key, str) and isinstance(value, str))


def record_rules_write(root, path, lines):
    """Remember the sha256 of the rules text absorb just wrote (or found
    already written) at path, for _own_rules_file."""
    record = read_rules_record(root)
    record[os.path.realpath(path)] = _sha256_text(verify.rules_text(lines))
    state = common.state_dir(root)
    common.ensure_private_dir(state)
    common.atomic_write_text(os.path.join(state, RULES_RECORD),
                             json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
                             + "\n", mode=0o600)


def _own_rules_file(path, record=None, terms=None):
    """True only for a regular file (no symlink) whose text has the shape
    verify.rules_text writes (RULES_HEADER, then '- ' lines only), is
    exactly the text absorb last wrote there (sha256 in RULES_RECORD) and
    hits no work_terms. A file merely named wiki-prefs.md or passed as
    --rules-path is not trusted by its name (fix round 1), nor by its shape
    (fix round 2: a same-shaped file with work text, or an edited one)."""
    if os.path.islink(path) or not os.path.isfile(path):
        return False
    try:
        text = verify.read_text(path)
    except (IOError, OSError, UnicodeDecodeError):
        return False
    if not text.startswith(verify.RULES_HEADER):
        return False
    if not all(line.startswith("- ") for line in text[len(verify.RULES_HEADER):].splitlines()):
        return False
    if (record or {}).get(os.path.realpath(path)) != _sha256_text(text):
        return False
    return terms is not None and not terms.hits(text)


def probe_claude(claude_path, env, timeout=PROBE_TIMEOUT):
    """Fail unless `claude --help` lists every flag absorb relies on."""
    try:
        proc = subprocess.run([claude_path, "--help"], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                              env=env, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise common.WikiError("claude_probe_failed", "cannot run %s --help: %s" % (claude_path, exc))
    text = proc.stdout.decode("utf-8", "replace")
    missing = [flag for flag in REQUIRED_FLAGS
               if not re.search(r"(^|[\s,])" + re.escape(flag) + r"($|[\s,=<\[])", text, re.M)]
    missing += [word for word in REQUIRED_HELP_WORDS if word not in text]
    if proc.returncode != 0 or missing:
        raise common.WikiError("claude_flags_missing",
                               "%s lacks required flags: %s" % (claude_path, ", ".join(missing)
                                                               or "help failed"))
    return True


def build_argv(claude_path, staging_dir, model, budget, schema_text):
    return [
        claude_path, "-p",
        "--restricted",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--tools", LLM_TOOLS,
        "--add-dir", staging_dir,
        "--permission-mode", "acceptEdits",
        "--permission-prompts", "none",
        "--no-session-persistence",
        "--output-format", "json",
        "--json-schema", schema_text,
        "--model", model,
        "--max-budget-usd", "%s" % budget,
    ]


def parse_claude_output(stdout):
    """The single JSON result of --output-format json (last JSON line)."""
    text = stdout.decode("utf-8", "replace").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("type") == "result":
                return data
    return None


class ClaudeRunner(object):
    """Runs one batch through `claude -p` with the panel-decided flags."""

    def __init__(self, claude_path, model, budget, environ, timeout=DEFAULT_LLM_TIMEOUT):
        self.claude_path = claude_path
        self.model = model
        self.budget = budget
        self.env = llm_env(environ, claude_path)
        self.timeout = timeout
        self.probed = False

    @classmethod
    def from_settings(cls, settings, environ):
        timeout = settings.get("llm_timeout_seconds", DEFAULT_LLM_TIMEOUT)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            timeout = DEFAULT_LLM_TIMEOUT
        runner = cls(resolve_claude(settings, environ), settings["model"],
                     settings["max_budget_usd"], environ, timeout)
        runner.probe()
        return runner

    def probe(self):
        probe_claude(self.claude_path, self.env)
        self.probed = True

    def __call__(self, request):
        argv = build_argv(self.claude_path, request["staging_dir"], self.model, self.budget,
                          json.dumps(request["schema"], ensure_ascii=False))
        try:
            proc = subprocess.run(argv, input=request["prompt"].encode("utf-8"),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=request["cwd"], env=self.env, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": "llm_timeout"}
        except OSError as exc:
            return {"ok": False, "reason": "llm_spawn_failed", "message": str(exc)}
        data = parse_claude_output(proc.stdout)
        if data is None:
            return {"ok": False, "reason": "llm_output_invalid",
                    "message": "exit %d" % proc.returncode}
        result = {"cost": data.get("total_cost_usd"), "subtype": data.get("subtype")}
        if data.get("subtype") == "error_max_budget_usd":
            result.update(ok=False, reason="budget_exceeded")
        elif data.get("is_error") or data.get("subtype") != "success" or proc.returncode != 0:
            result.update(ok=False, reason="llm_error")
        elif not isinstance(data.get("structured_output"), dict):
            result.update(ok=False, reason="llm_output_invalid")
        else:
            result.update(ok=True, reason=None, structured=data["structured_output"])
        return result


# ---------------------------------------------------------------------------
# Prompt (panel D-10)
# ---------------------------------------------------------------------------

def _source_lines(batch, state):
    lines = []
    for source in batch["sources"]:
        lines.append("- id: `%s` · op: %s · 날짜: %s" % (source["id"], source["op"], source["date"]))
        if source.get("redacted_path"):
            lines.append("  - 원본: %s" % os.path.join(state, source["redacted_path"]))
        if source.get("diff_path"):
            lines.append("  - 차이: %s" % os.path.join(state, source["diff_path"]))
    return "\n".join(lines)


def render_prompt(template, schema_md, request_info):
    values = {
        "DOMAIN": request_info["domain"],
        "OTHER_DOMAIN": request_info["other_domain"],
        "CWD": request_info["cwd"],
        "ALLOWED_GLOBS": ", ".join(request_info["allowed_globs"]),
        "STAGING_DIR": request_info["staging_dir"],
        "TODAY": request_info["today"],
        "MAX_SOURCES": str(common.MAX_SOURCES_PER_BATCH),
        "SOURCES": request_info["sources"],
        "CONTEXT": request_info["context"] or "(없음)",
        "PROMOTE": request_info["promote"] or "(없음)",
        "SCHEMA": schema_md.strip(),
    }
    text = template
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, value)
    return text


def _promote_lines(promoted):
    lines = []
    for names, count, page in promoted:
        where = "이미 있음: %s (aliases만 보강)" % page if page else "새 페이지를 만든다"
        lines.append("- %s (원본 %d개) → %s" % (" / ".join(names), count, where))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Worktree and git helpers (destructive git only with -C <worktree>)
# ---------------------------------------------------------------------------

def worktree_path(root):
    return os.path.join(root, common.WORKTREE_DIRNAME)


def remove_worktree(root):
    wt = worktree_path(root)
    if os.path.lexists(wt):
        prepare.make_writable(wt)
        common.wiki_git(root, ["worktree", "remove", "--force", wt], check=False)
        if os.path.lexists(wt):
            shutil.rmtree(wt, ignore_errors=True)
    common.wiki_git(root, ["worktree", "prune"], check=False)


def setup_worktree(root, base_sha):
    remove_worktree(root)
    wt = worktree_path(root)
    common.wiki_git(root, ["worktree", "add", "--detach", "-q", wt, base_sha])
    return wt


def reset_worktree(wt, sha):
    common.wiki_git(wt, ["reset", "-q", "--hard", sha])
    common.wiki_git(wt, ["clean", "-q", "-fdx"])


def commit_worktree(wt, message):
    """Commit everything in the worktree. Returns True if a commit was made."""
    common.wiki_git(wt, ["add", "-A", "--", "."])
    staged = common.wiki_git(wt, ["diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        return False
    common.wiki_git(wt, ["commit", "-q", "--no-verify", "-m", message])
    return True


def main_differs(root, base_sha, path):
    """True when main's working-tree file is not the base_sha version
    (uncommitted Obsidian edits, new untracked file, deletion)."""
    full = os.path.join(root, path)
    blob = verify.blob_at(root, base_sha, path)
    if blob is None:
        return os.path.lexists(full)
    if not os.path.lexists(full) or os.path.islink(full) or not os.path.isfile(full):
        return True
    return verify.read_bytes(full) != blob


def restore_in_worktree(wt, base_sha, paths):
    """Put paths back to their base_sha version in the worktree."""
    for path in paths:
        if verify.blob_at(wt, base_sha, path) is None:
            common.wiki_git(wt, ["rm", "-q", "-f", "--ignore-unmatch", "--", path])
            full = os.path.join(wt, path)
            if os.path.lexists(full):
                os.unlink(full)
        else:
            common.wiki_git(wt, ["checkout", base_sha, "--", path])


def defer_conflicts(root, wt, base_sha, batches, message):
    """Drop the worktree's change to every file main changed meanwhile, and
    defer whole batches: a batch touching such a file is marked deferred and
    all of its pages go back too (repeated until no new batch joins), so a
    deferred batch never half-merges and its re-offer next run is clean.
    Returns the restored paths."""
    head = verify.head_sha(wt)
    if head == base_sha:
        return []
    touched = verify.touched_between(wt, base_sha, head)
    deferred = set(path for path in touched if main_differs(root, base_sha, path))
    grew = True
    while grew:
        grew = False
        for outcome in batches:
            if outcome["ok"] and not outcome["deferred"] and set(outcome["pages"]) & deferred:
                outcome["deferred"] = True
                deferred |= set(outcome["pages"])
                grew = True
    restore = sorted(path for path in deferred if path in set(touched))
    if restore:
        restore_in_worktree(wt, base_sha, restore)
        commit_worktree(wt, message)
    return restore


def merged_mismatches(root, sha, paths):
    """Paths whose main working-tree bytes differ from commit sha."""
    bad = []
    for path in paths:
        blob = verify.blob_at(root, sha, path)
        full = os.path.join(root, path)
        if blob is None:
            if os.path.lexists(full):
                bad.append(path)
        elif not os.path.isfile(full) or verify.read_bytes(full) != blob:
            bad.append(path)
    return bad


def _matches_commit(root, sha, path):
    """True when main's working-tree path is exactly commit sha's version
    (same bytes, or absent in both)."""
    blob = verify.blob_at(root, sha, path)
    full = os.path.join(root, path)
    if blob is None:
        return not os.path.lexists(full)
    if os.path.islink(full) or not os.path.isfile(full):
        return False
    return verify.read_bytes(full) == blob


def rollback_main(root, base_sha, paths, merged_sha=None):
    """Undo a merge touching only absorb's files: HEAD and index back to
    base_sha (--mixed keeps every other working-tree file as it is), then
    each absorb-touched file restored to its base_sha version.

    With merged_sha, only files that still hold absorb's merged bytes are
    restored. A file that differs was written by a person (Obsidian) after
    the merge; it is left as it is, so the next prepare captures it as a
    manual:<page> source instead of erasing it (D7)."""
    common.wiki_git(root, ["reset", "-q", "--mixed", base_sha])
    kept = []
    for path in paths:
        if merged_sha is not None and not _matches_commit(root, merged_sha, path):
            kept.append(path)
            continue
        full = os.path.join(root, path)
        if verify.blob_at(root, base_sha, path) is None:
            if os.path.lexists(full) and not os.path.isdir(full):
                os.unlink(full)
        else:
            common.wiki_git(root, ["checkout", base_sha, "--", path])
    return kept


# ---------------------------------------------------------------------------
# State files
# ---------------------------------------------------------------------------

def last_absorb_path(root):
    return os.path.join(common.state_dir(root), LAST_ABSORB)


def read_last_absorb(root):
    try:
        data = common.load_json_file(last_absorb_path(root))
    except common.WikiError:
        return None
    return data if isinstance(data, dict) else None


def write_last_absorb(root, report, now):
    data = collections.OrderedDict()
    data["run_id"] = report.get("run_id")
    data["finished_at"] = verify.iso_now(now)
    data["status"] = report.get("status")
    data["reason"] = report.get("reason")
    data["summary_line"] = report.get("summary_line")
    common.ensure_private_dir(common.state_dir(root))
    common.atomic_write_text(last_absorb_path(root), common.dumps_json(data), mode=0o600)


def last_report_path(root):
    return os.path.join(common.state_dir(root), LAST_REPORT)


def write_report_file(root, report):
    """The full report (problems with page paths and source ids, warnings
    with paths) goes to .state/last-report.json (0600), never to the
    calling session. Returns the path, or None when it cannot be written."""
    try:
        common.ensure_private_dir(common.state_dir(root))
        path = last_report_path(root)
        common.atomic_write_text(path, common.dumps_json(report), mode=0o600)
        return path
    except (common.WikiError, IOError, OSError, TypeError, ValueError):
        return None


def warning_codes(warnings):
    """{code: count} of warnings, code = the text before the first ':'."""
    codes = collections.OrderedDict()
    for warning in warnings or []:
        code = str(warning).split(":", 1)[0].split(" ", 1)[0][:60] or "warning"
        codes[code] = codes.get(code, 0) + 1
    return codes


PUBLIC_KEYS = ("ok", "status", "reason", "run_id", "scheduled", "skipped", "applied",
               "new_pages", "quarantined", "unresolved", "rules_added", "rules_removed",
               "rules_path", "summary_line")


def public_report(report, report_path=None):
    """What `wiki absorb` prints in a session (text or --json): status,
    reason codes and counts only, the same as the Slack line (D2, SKILL
    rule 5). Page paths, source ids and titles stay in the report file."""
    out = collections.OrderedDict()
    for key in PUBLIC_KEYS:
        if key in report:
            out[key] = report[key]
    batches = []
    for outcome in report.get("batches") or []:
        item = collections.OrderedDict()
        for key in ("batch_id", "domain", "sources", "ok", "reason", "deferred", "merged",
                    "broken_links"):
            item[key] = outcome.get(key)
        item["problems"] = len(outcome.get("problems") or [])
        item["pages"] = len(outcome.get("pages") or [])
        item["new_pages"] = len(outcome.get("new_pages") or [])
        batches.append(item)
    out["batches"] = batches
    out["deferred_files"] = len(report.get("deferred_files") or [])
    out["warnings"] = warning_codes(report.get("warnings"))
    sent = report.get("notify")
    if isinstance(sent, dict):
        out["notify"] = collections.OrderedDict(
            (key, sent.get(key)) for key in ("state", "text", "mode", "sent", "reason"))
    if report_path:
        out["report_path"] = report_path
    return out


def drafts_store_dir(root, domain):
    return os.path.join(common.state_dir(root), DRAFTS_STORE, domain)


def load_stored_drafts(root):
    """{name: {domain: text}} of the last merged fragments (.state/drafts)."""
    stored = dict((name, {}) for name in verify.ROOT_DRAFTS)
    for domain in common.DOMAINS:
        base = drafts_store_dir(root, domain)
        for name in verify.ROOT_DRAFTS:
            path = os.path.join(base, name)
            if os.path.isfile(path):
                try:
                    stored[name][domain] = verify.read_text(path)
                except (IOError, OSError, UnicodeDecodeError):
                    pass
    return stored


def store_drafts(root, domain, drafts):
    base = drafts_store_dir(root, domain)
    common.ensure_private_dir(os.path.dirname(base))
    common.ensure_private_dir(base)
    for name, text in drafts.items():
        common.atomic_write_text(os.path.join(base, name), text, mode=0o600)


def obsidian_warnings(root, domains_cfg):
    """D3: community plugins outside obsidian_plugins_allow."""
    path = os.path.join(root, ".obsidian", "community-plugins.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            plugins = json.load(handle)
    except (IOError, OSError, ValueError):
        return ["obsidian_plugins_unreadable"]
    allow = set(domains_cfg.get("obsidian_plugins_allow") or [])
    if not isinstance(plugins, list):
        return ["obsidian_plugins_unreadable"]
    return ["obsidian_plugin_not_allowed:%s" % p for p in plugins
            if isinstance(p, str) and p not in allow]


# ---------------------------------------------------------------------------
# One batch
# ---------------------------------------------------------------------------

def _new_outcome(batch):
    outcome = collections.OrderedDict()
    outcome["batch_id"] = batch["batch_id"]
    outcome["domain"] = common.batch_domain(batch["sources"])
    outcome["sources"] = len(batch["sources"])
    outcome["ok"] = False
    outcome["reason"] = None
    outcome["problems"] = []
    outcome["deferred"] = False
    outcome["merged"] = False
    outcome["pages"] = []
    outcome["new_pages"] = []
    outcome["broken_links"] = 0
    outcome["warnings"] = []
    outcome["cost_usd"] = None
    return outcome


def failed_dir(root):
    return os.path.join(common.state_dir(root), FAILED_DIR)


def _retained_name(rel, allow):
    """rel as a path under the failed store: its own name when it holds no
    secret-shaped string, else a hashed name (the LLM chose the name)."""
    parts = [part for part in rel.split("/") if part]
    if (parts and all(part not in (".", "..") for part in parts)
            and not redact.scan(" %s " % rel, allow)):
        return "/".join(parts)
    digest = hashlib.sha256(rel.encode("utf-8", "replace")).hexdigest()[:12]
    return "_renamed/%s%s" % (digest, ".md" if rel.endswith(".md") else "")


def _prune_failed(root, keep=FAILED_KEEP_RUNS):
    """Keep the newest `keep` run folders of the failed store (run ids sort
    by time)."""
    base = failed_dir(root)
    try:
        runs = sorted(name for name in os.listdir(base)
                      if os.path.isdir(os.path.join(base, name)) and not name.startswith("."))
    except OSError:
        return
    for name in runs[:-keep] if keep > 0 else runs:
        shutil.rmtree(os.path.join(base, name), ignore_errors=True)


def _private_parents(dest, target):
    """Create target's missing parent folders below dest, each 0700."""
    parent = os.path.dirname(target)
    chain = []
    while parent != dest and not os.path.isdir(parent):
        chain.append(parent)
        parent = os.path.dirname(parent)
    for folder in reversed(chain):
        common.ensure_private_dir(folder)


def retain_failed_batch(ctx, batch, outcome, pre, result=None):
    """Keep a failed batch's draft for diagnosis (fix round 3, I-3): every
    file the LLM step changed in the worktree since pre, redacted with the
    allow list and known ids verify scans with, under
    .state/failed/<run_id>/<batch_id>/ (folders 0700, files 0600; .state/
    is gitignored), plus failure.json (reason, problems, source ids,
    changed files, the LLM's structured output; all redacted). A secret
    hit shows as [REDACTED:<kind>] at its place. A file name that is
    itself secret-shaped is stored under a hash. The newest
    FAILED_KEEP_RUNS runs are kept. Returns the folder, or None when it
    could not be written; never raises, so the batch's failure reason
    stays its own."""
    root, wt = ctx["root"], ctx["wt"]
    try:
        allow = verify.scan_allow(wt, ctx["domains"])
        known = verify.known_source_ids((ctx.get("working_sources") or {}).get("sources"),
                                        list(ctx.get("run_sources") or [])
                                        + list(batch["sources"]))
        base = failed_dir(root)
        run_dir = os.path.join(base, str(ctx.get("run_id") or "run"))
        dest = os.path.join(run_dir, str(batch["batch_id"]))
        for path in (common.state_dir(root), base, run_dir):
            common.ensure_private_dir(path)
        if os.path.lexists(dest):
            shutil.rmtree(dest, ignore_errors=True)
        common.ensure_private_dir(dest)
        files = []
        for status, rel in verify.changed_files(wt, pre):
            item = collections.OrderedDict()
            item["status"] = status
            item["path"] = redact.redact(rel, allow, known).text
            item["kept"] = None
            full = os.path.join(wt, rel)
            if status == "D" or not os.path.lexists(full):
                pass
            elif os.path.islink(full) or not os.path.isfile(full):
                item["note"] = "not_regular_file"
            else:
                try:
                    text = verify.read_text(full)
                except (IOError, OSError, UnicodeDecodeError, ValueError):
                    item["note"] = "unreadable"
                else:
                    name = _retained_name(rel, allow)
                    target = os.path.join(dest, name)
                    _private_parents(dest, target)
                    common.atomic_write_text(target, redact.redact(text, allow, known).text,
                                             mode=0o600)
                    item["kept"] = name
            files.append(item)
        info = collections.OrderedDict()
        info["run_id"] = ctx.get("run_id")
        info["batch_id"] = batch["batch_id"]
        info["domain"] = outcome.get("domain")
        info["reason"] = outcome.get("reason")
        # A problem is '<code>:<detail>'; only the detail (page path,
        # source id) is redacted, so 'secret_found:' itself stays readable.
        info["problems"] = []
        for problem in outcome.get("problems") or []:
            code, sep, detail = str(problem).partition(":")
            info["problems"].append(code + sep + redact.redact(detail, allow, known).text)
        info["sources"] = [source.get("id") for source in batch["sources"]]
        info["files"] = files
        structured = (result or {}).get("structured")
        if structured is not None:
            info["structured_output"] = json.loads(redact.redact(
                json.dumps(structured, ensure_ascii=False), allow, known).text)
        common.atomic_write_text(os.path.join(dest, "failure.json"),
                                 common.dumps_json(info), mode=0o600)
        _prune_failed(root)
        return dest
    except Exception:  # noqa: BLE001 - keeping a draft must not mask the failure
        return None


def run_batch(ctx, batch, record):
    """LLM step + verify + Python post-processing for one batch. On any
    failure the worktree goes back to the batch's starting commit."""
    root, wt = ctx["root"], ctx["wt"]
    outcome = _new_outcome(batch)
    domain = outcome["domain"]
    batch_id = batch["batch_id"]
    pre = verify.head_sha(wt)
    state = common.state_dir(root)
    staging = prepare.batch_dir(root, batch_id)
    cwd = os.path.join(wt, domain)
    if not os.path.isdir(cwd):
        os.makedirs(cwd)
    working = ctx["working_sources"]
    result = None
    try:
        if ctx.get("runner_error") is not None:
            raise ctx["runner_error"]
        if domain == "personal" and ctx.get("foreign_rules"):
            raise verify.BatchFailure(["user_rules_unisolated"])
        mentions, merges = verify.stored_mentions(working, domain)
        promoted = verify.promotions(mentions, merges, verify.load_pages(wt, domain))
        context_files = [os.path.join(state, rel) for rel in record.get("context") or []]
        info = {
            "domain": domain,
            "other_domain": [d for d in common.DOMAINS if d != domain][0],
            "cwd": cwd,
            "allowed_globs": batch["allowed_globs"],
            "staging_dir": staging,
            "today": ctx["now"].strftime("%Y-%m-%d"),
            "sources": _source_lines(batch, state),
            "context": "\n".join("- %s" % path for path in context_files),
            "promote": _promote_lines(promoted),
        }
        request = {
            "batch_id": batch_id, "domain": domain, "cwd": cwd, "staging_dir": staging,
            "prompt": render_prompt(ctx["template"], ctx["schema_md"], info),
            "schema": verify.OUTPUT_SCHEMA, "allowed_globs": batch["allowed_globs"],
            "sources": batch["sources"],
        }
        prepare.seal_batch(root, batch_id)
        result = ctx["runner"](request) or {}
        outcome["cost_usd"] = result.get("cost")
        staging_problems = prepare.check_batch_staging(root, batch_id, record["manifest"])
        if staging_problems:
            raise verify.BatchFailure(["staging_modified:%s" % p for p in staging_problems])
        if not result.get("ok"):
            raise verify.BatchFailure([result.get("reason") or "llm_error"])
        output = verify.normalize_output(result.get("structured"), wt, batch)
        check = verify.check_batch(wt, pre, batch, working["sources"], ctx["domains"],
                                   extra_sources=ctx["run_sources"])
        # Names from the LLM go into frontmatter aliases, sources.json and
        # alias-cache.json after check_batch: drop secret or (personal)
        # work_terms names first (D5), stored groups included.
        allow = ctx["domains"].get("redact_allow", [])
        terms = verify.Terms(ctx["domains"].get("work_terms", []))
        output["merges"] = verify.clean_groups(output["merges"], domain, terms, allow)
        output["mentions"] = verify.clean_mentions(output["mentions"], domain, terms, allow)
        verify.remove_drafts(wt, domain)
        all_pages = list(verify.iter_page_files(wt, domain))
        snapshot = verify.notes_snapshot(wt, all_pages)
        groups = verify.clean_groups(
            [g for g in verify.merge_groups(list(merges) + output["merges"]) if len(g) >= 2],
            domain, terms, allow)
        aliased = verify.sync_aliases(wt, domain, groups, terms)
        linked = verify.link_pages(wt, domain, sorted(set(check.pages)), terms)
        verify.assert_notes_unchanged(wt, snapshot)
        verify.recheck_pages(wt, domain, list(aliased) + list(linked), ctx["domains"],
                             verify.known_source_ids(working["sources"],
                                                     list(ctx["run_sources"]) + list(batch["sources"])))
        commit_worktree(wt, "wiki: absorb %s 묶음 %d (%s)" % (ctx["run_id"], batch_id, domain))
        post = verify.head_sha(wt)
        outcome["ok"] = True
        outcome["pages"] = verify.touched_between(wt, pre, post) if post != pre else []
        outcome["new_pages"] = sorted(set(
            path for status, path in check.changes
            if status in ("A", "?") and path.endswith(".md")
            and not verify._is_draft(path, domain) and path in outcome["pages"]))
        outcome["broken_links"] = check.broken_links
        outcome["warnings"] = list(check.warnings)
        # Draft text and mention names stay out of the printed report.
        ctx["private"][batch_id] = {"drafts": check.drafts, "mentions": output["mentions"],
                                    "merges": output["merges"]}
        verify.update_mentions(working, domain, output["mentions"], output["merges"])
        ctx["run_sources"].extend(batch["sources"])
    except common.WikiError as exc:
        outcome["ok"] = False
        outcome["reason"] = exc.reason
        outcome["problems"] = list(getattr(exc, "problems", []) or [str(exc)])[:20]
        if retain_failed_batch(ctx, batch, outcome, pre, result):
            outcome["warnings"].append("failed_draft_kept")
        reset_worktree(wt, pre)
    except (ValueError, OSError) as exc:
        # An undecodable or unreadable page (e.g. a CP949 export) fails this
        # batch, not the whole run.
        outcome["ok"] = False
        outcome["reason"] = "page_unreadable"
        outcome["problems"] = ["page_unreadable:%s" % type(exc).__name__]
        if retain_failed_batch(ctx, batch, outcome, pre, result):
            outcome["warnings"].append("failed_draft_kept")
        reset_worktree(wt, pre)
    return outcome


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def default_rules_path(environ):
    """D12: ~/.claude/rules/wiki-prefs.md, from the given environment so
    manual and scheduled runs (the plist carries HOME and CLAUDE_CONFIG_DIR)
    resolve the same file and tests resolve a temp HOME. WIKI_RULES_PATH
    overrides it."""
    explicit = (environ.get("WIKI_RULES_PATH") or "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    config = (environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    if not config:
        home = environ.get("HOME") or os.path.expanduser("~")
        config = os.path.join(home, ".claude")
    return os.path.join(os.path.abspath(config), "rules", RULES_FILENAME)


def _hours_since(previous, now):
    if not previous or not isinstance(previous.get("finished_at"), str):
        return None
    try:
        text = previous["finished_at"]
        moment = datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    naive_now = now.replace(tzinfo=None) if now.tzinfo else now
    return round((naive_now - moment).total_seconds() / 3600.0, 1)


def _log_line(report, prep, interval, broken):
    ok = [b for b in report["batches"] if b["ok"]]
    parts = ["- %s" % report["run_id"],
             "반영 대기 %d" % prep.get("sources", 0),
             "묶음 %d/%d" % (len(ok), len(report["batches"])),
             "격리 %d" % report["quarantined"],
             "판정 불가 %d" % report["unresolved"],
             "간격 %s" % ("%sh" % interval if interval is not None else "-")]
    if broken:
        parts.append("끊긴 링크 %d" % broken)
    reasons = sorted(set(b["reason"] for b in report["batches"] if b["reason"]))
    if reasons:
        parts.append("사유 " + ",".join(reasons))
    return " · ".join(parts)


def _append_log(wt, line):
    path = os.path.join(wt, "log.md")
    text = verify.read_text(path) if os.path.isfile(path) else "# absorb 기록\n\n"
    if not text.endswith("\n"):
        text += "\n"
    common.atomic_write_text(path, text + line + "\n")


def _write_if_changed(path, text):
    current = verify.read_text(path) if os.path.isfile(path) else None
    if current != text:
        common.atomic_write_text(path, text)
        return True
    return False


def generate_root_files(ctx, merged_drafts):
    """index.md, now.md, about-me.md and paused status in the worktree.

    Returns warning codes. A root file is never a reason to fail the run
    (review round 3): a fragment whose fences do not balance is dropped
    (`draft_unbalanced_fence:<name>:<domain>`), and a root file that cannot
    be reassembled safely (its own fences do not balance, its '## 내 메모'
    sits inside code, or the result would change 내 메모 or leave a fence
    open) is left as it is (`root_file_skipped:<name>`)."""
    root, wt, now = ctx["root"], ctx["wt"], ctx["now"]
    terms = verify.Terms(ctx["domains"].get("work_terms", []))
    warnings = []
    _write_if_changed(os.path.join(wt, "index.md"), verify.build_index(wt, now, terms))
    stored = load_stored_drafts(root)
    for name in verify.ROOT_DRAFTS:
        fragments = dict(stored.get(name) or {})
        fragments.update(merged_drafts.get(name) or {})
        for domain in sorted(fragments):
            if not verify.fences_balanced(fragments[domain]):
                warnings.append("draft_unbalanced_fence:%s:%s" % (name, domain))
                del fragments[domain]
        if not fragments:
            continue
        path = os.path.join(wt, name)
        current = verify.read_text(path) if os.path.isfile(path) else read_template(
            os.path.join("root", name))
        if not verify.root_assemblable(current):
            warnings.append("root_file_skipped:%s" % name)
            continue
        if name == "now.md":
            text = verify.assemble_now(current, fragments, verify.recent_decisions(wt, now))
        else:
            text = verify.assemble_about_me(current, fragments)
        if (verify.notes_tail(text) != verify.notes_tail(current)
                or not verify.fences_balanced(text)):
            warnings.append("root_file_skipped:%s" % name)
            continue
        _write_if_changed(path, text)
    verify.expire_handoff_state(wt, now)
    verify.apply_paused(wt, now)
    return warnings


GENERATED_FILES = ("index.md", "log.md", "now.md", "about-me.md")


def _merged_drafts(ctx, batches):
    """{name: {domain: text}} from batches that passed and are not deferred."""
    merged = dict((name, {}) for name in verify.ROOT_DRAFTS)
    for outcome in batches:
        if outcome["ok"] and not outcome["deferred"]:
            private = ctx["private"].get(outcome["batch_id"]) or {}
            for name, text in (private.get("drafts") or {}).items():
                merged[name][outcome["domain"]] = text
    return merged


def _summary_line(report):
    status = report["status"]
    if status == STATUS_FAILED:
        return "위키: 실패 (%s)" % (report.get("reason") or "unknown")
    if status == STATUS_EMPTY:
        return "위키: 반영 0 · 격리 %d" % report["quarantined"]
    parts = ["반영 %d" % report["applied"], "새 페이지 %d" % report["new_pages"],
             "격리 %d" % report["quarantined"],
             "전역 선호 +%d/−%d" % (report["rules_added"], report["rules_removed"])]
    failed = [b for b in report["batches"] if not b["ok"]]
    if failed:
        parts.append("실패 %d" % len(failed))
    deferred = [b for b in report["batches"] if b["deferred"]]
    if deferred:
        parts.append("보류 %d" % len(deferred))
    elif report.get("deferred_files"):
        parts.append("보류 파일 %d" % len(report["deferred_files"]))
    prefix = "위키: 한도 보류 · " if status == STATUS_HELD else "위키: "
    return prefix + " · ".join(parts)


def _pending_block(report, prep_json, run, now):
    """caches.md 'pending': sources of batches that did not merge."""
    counts = collections.OrderedDict((domain, 0) for domain in common.DOMAINS)
    titles = collections.OrderedDict((domain, []) for domain in common.DOMAINS)
    for outcome in report["batches"]:
        if outcome["merged"]:
            continue
        record = (prep_json.get("batches") or {}).get(str(outcome["batch_id"])) or {}
        for rec in (record.get("sources") or {}).values():
            counts[outcome["domain"]] += 1
            if rec.get("title"):
                titles[outcome["domain"]].append(rec["title"])
    block = collections.OrderedDict()
    block["updated_at"] = verify.iso_now(now)
    block["unresolved"] = run.get("unresolved", 0)
    block["domains"] = collections.OrderedDict(
        (domain, {"count": counts[domain], "titles": titles[domain][:20]})
        for domain in common.DOMAINS)
    return block


def new_report():
    report = collections.OrderedDict()
    report["ok"] = False
    report["status"] = None
    report["reason"] = None
    report["run_id"] = None
    report["base_sha"] = None
    report["head"] = None
    report["applied"] = 0
    report["new_pages"] = 0
    report["quarantined"] = 0
    report["unresolved"] = 0
    report["rules_added"] = 0
    report["rules_removed"] = 0
    report["rules_path"] = None
    report["batches"] = []
    report["deferred_files"] = []
    report["warnings"] = []
    report["summary_line"] = ""
    return report


def absorb(root, environ=None, paths=None, now=None, runner=None, rules_path=None,
           scheduled=False, fs_root="/", remote_fn=None):
    """Run absorb once. Returns the report dict (also summarized in
    .state/last-absorb). Raises LockBusy when another absorb holds the lock
    and WikiError(not_initialized) for a missing wiki."""
    environ = os.environ if environ is None else environ
    now = now or datetime.datetime.now()
    if not common.is_initialized(root) or not os.path.isdir(os.path.join(root, ".git")):
        raise common.WikiError("not_initialized", "%s is not a wiki; run wiki init" % root)
    with common.wiki_lock(root):
        write_running_marker(root, now)
        try:
            return _run(root, environ, paths, now, runner,
                        rules_path or default_rules_path(environ), scheduled, fs_root, remote_fn)
        except Exception as exc:
            # Whatever raised after the lock, `status` must not keep showing
            # the previous run's line: record a failed run, then re-raise
            # for run_absorb's ledger.
            report = new_report()
            report["status"] = STATUS_FAILED
            report["reason"] = (exc.reason if isinstance(exc, common.WikiError)
                                else "internal_error")
            report["summary_line"] = _summary_line(report)
            try:
                write_last_absorb(root, report, now)
            except (common.WikiError, IOError, OSError):
                pass
            raise
        finally:
            remove_running_marker(root)


def running_marker_path(root):
    return os.path.join(common.state_dir(root), RUNNING_FILE)


def write_running_marker(root, now):
    """.state/absorb-running.json (pid, started_at) for `status`, which
    never takes the lock itself (a scheduled tick would then skip)."""
    data = collections.OrderedDict()
    data["pid"] = os.getpid()
    data["started_at"] = verify.iso_now(now)
    try:
        common.ensure_private_dir(common.state_dir(root))
        common.atomic_write_text(running_marker_path(root), common.dumps_json(data), mode=0o600)
    except (common.WikiError, IOError, OSError):
        pass


def remove_running_marker(root):
    try:
        os.unlink(running_marker_path(root))
    except OSError:
        pass


def read_running_marker(root):
    """The marker of a live absorb, or None (missing, unreadable, or its
    process is gone)."""
    try:
        data = common.load_json_file(running_marker_path(root))
    except common.WikiError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pid"), int):
        return None
    try:
        os.kill(data["pid"], 0)
    except PermissionError:
        return data  # alive, owned by someone else
    except (OSError, OverflowError):
        return None
    return data


def _run(root, environ, paths, now, runner, rules_path, scheduled, fs_root, remote_fn):
    report = new_report()
    report["scheduled"] = bool(scheduled)
    report["rules_path"] = rules_path
    previous = read_last_absorb(root)
    try:
        prep = prepare.prepare(root, environ, paths, now, locked=True, fs_root=fs_root,
                               remote_fn=remote_fn)
    except common.WikiError as exc:
        report["status"] = STATUS_FAILED
        report["reason"] = exc.reason
        report["warnings"].append("%s:%s" % (exc.reason, str(exc)[:300]))
        report["summary_line"] = _summary_line(report)
        write_last_absorb(root, report, now)
        write_report_file(root, report)
        return report
    run = common.read_run(root)
    prep_json = prepare.load_prepare(root)
    domains_cfg = common.load_domains(root)
    settings = common.load_settings(root)
    base = run["base_sha"]
    report["run_id"] = run["run_id"]
    report["base_sha"] = base
    report["quarantined"] = run.get("quarantined", 0)
    report["unresolved"] = run.get("unresolved", 0)
    report["warnings"] += list(prep.get("warnings") or []) + obsidian_warnings(root, domains_cfg)
    try:
        wt = setup_worktree(root, base)
        ctx = {"root": root, "wt": wt, "now": now, "run_id": run["run_id"],
               "domains": domains_cfg,
               "working_sources": copy.deepcopy(prepare.load_sources(root)), "run_sources": [],
               "runner": runner, "runner_error": None, "private": {},
               "foreign_rules": foreign_user_rules(
                   environ, rules_path, root,
                   verify.Terms(domains_cfg.get("work_terms", [])))}
        if ctx["foreign_rules"]:
            report["warnings"].append("user_rules_present:%d" % ctx["foreign_rules"])
        if run["batches"]:
            ctx["template"] = read_template(PROMPT_TEMPLATE)
            schema_path = os.path.join(wt, "SCHEMA.md")
            ctx["schema_md"] = (verify.read_text(schema_path) if os.path.isfile(schema_path)
                                else read_template("SCHEMA.md"))
            if runner is None:
                try:
                    ctx["runner"] = ClaudeRunner.from_settings(settings, environ)
                except common.WikiError as exc:
                    ctx["runner_error"] = exc
        records = prep_json.get("batches") or {}
        for batch in run["batches"]:
            record = records.get(str(batch["batch_id"])) or {}
            report["batches"].append(run_batch(ctx, batch, record))
        _finish(ctx, report, prep, prep_json, run, previous, rules_path)
    finally:
        prepare.make_writable(common.staging_dir(root))
        try:
            # The redacted copies hold work text; commit_batch already took
            # what it needed (snapshots), so staging goes now (panel D-1).
            prepare.clear_staging(root)
        except (IOError, OSError):
            report["warnings"].append("staging_cleanup_failed")
        try:
            remove_worktree(root)
        except common.WikiError:
            report["warnings"].append("worktree_cleanup_failed")
    report["summary_line"] = _summary_line(report)
    report["ok"] = report["status"] in (STATUS_OK, STATUS_EMPTY, STATUS_HELD)
    write_last_absorb(root, report, now)
    write_report_file(root, report)
    return report


def _finish(ctx, report, prep, prep_json, run, previous, rules_path):
    root, wt, now = ctx["root"], ctx["wt"], ctx["now"]
    base = run["base_sha"]
    domains_cfg = ctx["domains"]
    batches = report["batches"]

    message = "wiki: absorb %s 보류 (사람 편집과 겹침)" % run["run_id"]
    merge_error = None
    deferred = []
    try:
        # Pass 1: pages main changed while the LLM ran.
        deferred += defer_conflicts(root, wt, base, batches, message)
        interval = _hours_since(previous, now)
        for _attempt in range(3):
            # Generated files are rebuilt from base each time, so a batch
            # deferred in a later pass leaves no trace in them.
            restore_in_worktree(wt, base, [name for name in GENERATED_FILES
                                           if verify.blob_at(wt, base, name) is not None])
            for code in generate_root_files(ctx, _merged_drafts(ctx, batches)):
                if code not in report["warnings"]:
                    report["warnings"].append(code)
            broken = sum(b["broken_links"] for b in batches if b["ok"] and not b["deferred"])
            _append_log(wt, _log_line(report, prep, interval, broken))
            commit_worktree(wt, "wiki: absorb %s 색인·기록" % run["run_id"])
            before = len([b for b in batches if b["deferred"]])
            # Pass 2: also covers index.md, log.md, now.md, about-me.md.
            deferred += defer_conflicts(root, wt, base, batches, message)
            if len([b for b in batches if b["deferred"]]) == before:
                break
        hits = verify.scan_tree(wt, verify.scan_allow(wt, domains_cfg),
                                verify.known_source_ids(ctx["working_sources"]["sources"],
                                                        ctx["run_sources"]))
        blocking, existing = split_tree_hits(wt, base, hits)
        if existing:
            # Bytes main already holds (committed before a stricter scan):
            # refusing the merge would not remove them, only freeze the
            # wiki. Count only; the human fixes or allows them.
            report["warnings"].append("secret_found_existing:%d" % len(existing))
        if blocking:
            report["warnings"] += ["secret_found:%s" % hit.rsplit(":", 1)[0]
                                   for hit in blocking[:20]]
            raise common.WikiError("secret_found", "secrets in %d file(s)" % len(blocking))
        merge_into_main(root, wt, base)
    except common.WikiError as exc:
        merge_error = exc
    report["deferred_files"] = sorted(set(deferred))

    merged = merge_error is None
    if merged:
        for outcome in batches:
            outcome["merged"] = outcome["ok"] and not outcome["deferred"]
    # Caches and rules always describe main's HEAD.
    reset_worktree(wt, verify.head_sha(root))
    _post_merge(ctx, report, prep_json, run, rules_path, merged)

    report["head"] = verify.head_sha(root)
    merged_batches = [b for b in batches if b["merged"]]
    report["applied"] = sum(b["sources"] for b in merged_batches)
    report["new_pages"] = sum(len([p for p in b["new_pages"] if p not in report["deferred_files"]])
                              for b in merged_batches)
    failed = [b for b in batches if not b["ok"]]
    if merge_error is not None:
        report["status"] = STATUS_FAILED
        report["reason"] = merge_error.reason
    elif not batches:
        report["status"] = STATUS_EMPTY
    elif any(b["reason"] == "budget_exceeded" for b in failed):
        report["status"] = STATUS_HELD
        report["reason"] = "budget_exceeded"
    elif failed and len(failed) == len(batches):
        report["status"] = STATUS_FAILED
        report["reason"] = failed[0]["reason"]
    else:
        report["status"] = STATUS_OK


def split_tree_hits(wt, base, hits):
    """(blocking, existing) scan_tree hits. A hit blocks the merge when its
    file is new or changed since base (this run would add the bytes);
    a file the run left exactly as base has it is only counted."""
    changed = set(verify.touched_between(wt, base, verify.head_sha(wt)))
    blocking, existing = [], []
    for hit in hits:
        path = hit.rsplit(":", 1)[0]
        if path not in changed and verify.blob_at(wt, base, path) is not None:
            existing.append(hit)
        else:
            blocking.append(hit)
    return blocking, existing


def merge_into_main(root, wt, base):
    """Fast-forward main to the worktree head. Never resets main --hard."""
    if verify.head_sha(root) != base:
        raise common.WikiError("main_moved", "main moved since prepare; nothing merged")
    final = verify.head_sha(wt)
    if final == base:
        return []
    touched = verify.touched_between(wt, base, final)
    late = [path for path in touched if main_differs(root, base, path)]
    if late:
        raise common.WikiError("main_changed_during_merge", "%d file(s) changed in main" % len(late))
    proc = common.wiki_git(root, ["merge", "--ff-only", "-q", final], check=False)
    if proc.returncode != 0:
        if verify.head_sha(root) != base:
            rollback_main(root, base, touched, merged_sha=final)
        raise common.WikiError("merge_failed", proc.stderr.decode("utf-8", "replace").strip()[:300])
    mismatched = merged_mismatches(root, final, touched)
    if mismatched:
        rollback_main(root, base, touched, merged_sha=final)
        raise common.WikiError("merge_mismatch", "%d file(s) differ after merge" % len(mismatched))
    return touched


def _post_merge(ctx, report, prep_json, run, rules_path, merged):
    root, wt, now = ctx["root"], ctx["wt"], ctx["now"]
    # Caches and rules lines may name existing pages (scan_allow).
    domains_cfg = verify.with_scan_allow(wt, ctx["domains"])
    merged_batches = [b for b in report["batches"] if b["merged"]]
    try:
        for outcome in merged_batches:
            prepare.commit_batch(root, outcome["batch_id"], run["run_id"])
        if merged_batches:
            # A fresh load: commit_batch/finalize_run save sources.json themselves.
            data = prepare.load_sources(root)
            for outcome in merged_batches:
                private = ctx["private"].get(outcome["batch_id"]) or {}
                verify.update_mentions(data, outcome["domain"], private.get("mentions") or {},
                                       private.get("merges") or [])
            prepare.save_sources(root, data)
        prepare.finalize_run(root)
    except (common.WikiError, IOError, OSError) as exc:
        report["warnings"].append("source_state_failed:%s" % getattr(exc, "reason", "io"))
    for outcome in merged_batches:
        private = ctx["private"].get(outcome["batch_id"]) or {}
        if private.get("drafts"):
            store_drafts(root, outcome["domain"], private["drafts"])
    state = common.state_dir(root)
    try:
        context = verify.build_context_cache(wt, domains_cfg, run["run_id"], now,
                                             _pending_block(report, prep_json, run, now))
        if not verify.write_cache(os.path.join(state, "context-cache.json"), context, domains_cfg):
            report["warnings"].append("context_cache_secret")
        aliases = verify.build_alias_cache(wt, now, domains_cfg)
        if not verify.write_cache(os.path.join(state, "alias-cache.json"), aliases, domains_cfg):
            report["warnings"].append("alias_cache_secret")
    except (common.WikiError, IOError, OSError) as exc:
        report["warnings"].append("cache_write_failed:%s" % getattr(exc, "reason", "io"))
    try:
        lines = verify.rules_lines(wt, domains_cfg, prepare.load_sources(root)["sources"])
        added, removed = verify.write_rules(rules_path, lines, os.path.join(state, BACKUPS_DIR),
                                            run["run_id"])
        record_rules_write(root, rules_path, lines)
        report["rules_added"], report["rules_removed"] = added, removed
    except (common.WikiError, IOError, OSError) as exc:
        report["warnings"].append("rules_write_failed:%s" % getattr(exc, "reason", "io"))
