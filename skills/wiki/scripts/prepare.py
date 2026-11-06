"""absorb prepare step (T2). Python 3.9, stdlib only.

prepare() runs under the absorb lock, before the LLM step:

  1. capture human edits in main (domain pages, root now.md/about-me.md):
     commit them and emit manual:<page> sources (D1) so base_sha includes
     them and the later ff-merge never meets a dirty file
  2. discover sources (D4): memory (MEMORY.md excluded), handoff/design
     .md, prompts from history.jsonl (display, project, timestamp; never
     pastedContents) and the Traycer chat-search DB (tier='user' AND
     inter_agent=0, read-only, schema checked), inbox/<domain>/
  3. resolve domain and date in the order of contract 2, quarantine
     personal sources whose text hits work_terms (D5)
  4. redact (D15, contract 4) and diff against the last redacted snapshot
  5. write staging/<batch>/ (one domain per batch, at most 30 sources) and
     .state/run.json (contract 1)

prepare never advances source state. snapshots/, sources.json and the
inbox change only when T3 calls commit_batch() after a batch merged, and
finalize_run() after the run; a failed batch is offered again next run.
Per-batch bookkeeping lives in .state/prepare.json, outside staging/<batch>
(the LLM's --add-dir), so the LLM never sees origin paths or hashes.

Staging layout (paths in run.json are relative to .state/):
  staging/<batch>/<safe-name>.md      redacted copy of the source
  staging/<batch>/<safe-name>.diff    unified diff against the snapshot
  staging/<batch>/context/now.md      that domain's "### <domain>" part of
  staging/<batch>/context/about-me.md root "## 내 메모" (D16), if not empty

Source ids:
  mem:<project-folder>/<relpath>   handoff:<relpath>   design:<relpath>
  prompts:<domain>/<YYYY-MM-DD>    inbox:<domain>/<relpath>
  manual:<page relpath>
Whitespace, '%' and '>' in ids are percent-encoded so ids match
^[a-z][a-z0-9_-]*:\\S+$ and never contain '-->'.

Every source location is injectable (SourcePaths, or environment variables
WIKI_SRC_PROJECTS, WIKI_SRC_HISTORY, WIKI_SRC_HANDOFF, WIKI_SRC_DESIGN,
WIKI_SRC_TRAYCER_DB, WIKI_SRC_TRAYCER_EPICS_DB; CLAUDE_CONFIG_DIR moves the
~/.claude defaults). An empty value disables that source.
"""

import collections
import datetime
import difflib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import unicodedata
import urllib.parse

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import classify  # noqa: E402
import common  # noqa: E402
import redact  # noqa: E402

PREPARE_JSON = "prepare.json"
SOURCES_JSON = "sources.json"

KIND_MEMORY = "mem"
KIND_HANDOFF = "handoff"
KIND_DESIGN = "design"
KIND_PROMPTS = "prompts"
KIND_INBOX = "inbox"
KIND_MANUAL = "manual"
KIND_NOTES = "notes"  # the '### <domain>' part of root now.md/about-me.md '## 내 메모' (D16)

# Only file-backed sources are withdrawn when they disappear. Prompt digests are
# not: history.jsonl rotates and the Traycer DB has vanished before, and missing
# data is not a retraction. A digest is withdrawn only when one of its prompts is
# seen right now in another bucket (see moved_prompts). Inbox files are consumed,
# not deleted.
DELETABLE_KINDS = (KIND_MEMORY, KIND_HANDOFF, KIND_DESIGN)

STATUS_ACTIVE = "active"
STATUS_CONSUMED = "consumed"
STATUS_DELETED = "deleted"
STATUS_UNRESOLVED = "unresolved"
STATUS_QUARANTINED = "quarantined"
STATUS_PENDING = "pending"  # manual edits not absorbed yet
STATUS_CLOSED = "closed"    # manual edits absorbed: kept so pages may cite them

DEFAULT_PROMPT_DAYS = 30
PROMPT_MAX_CHARS = 4000
JSONL_SCAN_FILES = 20
JSONL_SCAN_LINES = 400
FS_MATCH_MAX_VISITS = 5000
MASS_DELETE_MIN = 10  # hold deletions when >= this many and > half of a kind vanish

TRAYCER_DOC_COLUMNS = ("chat_key", "tier", "inter_agent", "created_at", "text")
TRAYCER_CHAT_COLUMNS = ("chat_key", "epic_id", "lifecycle_state")
TRAYCER_EPIC_COLUMNS = ("epic_id", "creation_payload")

ROOT_DRAFT_PAGES = ("now.md", "about-me.md")
_BARE_SLASH_RE = re.compile(r"^/[A-Za-z0-9:_.-]+$")
_FS_ENCODE_RE = re.compile(r"[^A-Za-z0-9]")
_DATE_PREFIX_RE = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?"
                     r"(Z|[+-]\d{2}:?\d{2})?)?$")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

class SourcePaths(object):
    """Where sources are read from. None/"" disables a source."""

    def __init__(self, projects_dir=None, history_path=None, handoff_dir=None,
                 design_dir=None, traycer_db=None, traycer_epics_db=None):
        self.projects_dir = projects_dir
        self.history_path = history_path
        self.handoff_dir = handoff_dir
        self.design_dir = design_dir
        self.traycer_db = traycer_db
        self.traycer_epics_db = traycer_epics_db

    @classmethod
    def from_environ(cls, environ=None):
        environ = os.environ if environ is None else environ
        home = environ.get("HOME") or os.path.expanduser("~")
        claude_home = environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
        traycer_host = os.path.join(home, ".traycer", "host")

        def pick(name, default):
            value = environ.get(name)
            return default if value is None else value

        return cls(
            projects_dir=pick("WIKI_SRC_PROJECTS", os.path.join(claude_home, "projects")),
            history_path=pick("WIKI_SRC_HISTORY", os.path.join(claude_home, "history.jsonl")),
            handoff_dir=pick("WIKI_SRC_HANDOFF", os.path.join(claude_home, "handoff")),
            design_dir=pick("WIKI_SRC_DESIGN", os.path.join(claude_home, "design")),
            traycer_db=pick("WIKI_SRC_TRAYCER_DB",
                            os.path.join(traycer_host, "chat-search", "chat-search.db")),
            traycer_epics_db=pick("WIKI_SRC_TRAYCER_EPICS_DB",
                                  os.path.join(traycer_host, "epic-homes", "epic-homes.db")),
        )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def encode_id_part(text):
    """Percent-encode whitespace, '%' and '>' so ids stay \\S+ without '-->'."""
    out = []
    for ch in unicodedata.normalize("NFC", text):
        if ch == "%" or ch == ">" or ch.isspace() or unicodedata.category(ch) == "Cc":
            out.append("".join("%%%02X" % b for b in ch.encode("utf-8")))
        else:
            out.append(ch)
    return "".join(out)


def make_id(kind, rest):
    source_id = "%s:%s" % (kind, encode_id_part(rest))
    if not common.is_valid_source_id(source_id):
        raise ValueError("cannot build a source id from %r" % (rest,))
    return source_id


def safe_name(source_id):
    """Staging/snapshot file stem: readable, ASCII, collision-free."""
    kind, _sep, rest = source_id.partition(":")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", rest).strip("._-")[-60:] or "src"
    return "%s__%s-%s" % (kind, stem, hashlib.sha1(source_id.encode("utf-8")).hexdigest()[:8])


def fold(text):
    """NFKC + casefold, for work_terms matching."""
    return unicodedata.normalize("NFKC", text or "").casefold()


class TermMatcher(object):
    """work_terms matcher. Texts are matched with the home folder replaced
    by '~' first (common.strip_home, fix round 1)."""

    def __init__(self, terms, home=None):
        self.terms = [fold(term) for term in terms or () if fold(term).strip()]
        self.home = home

    def hits(self, *texts):
        if not self.terms:
            return False
        for text in texts:
            if not text:
                continue
            text = text if isinstance(text, str) else " ".join(text)
            folded = fold(common.strip_home(text, self.home))
            for term in self.terms:
                if term in folded:
                    return True
        return False


def local_date_from_epoch(seconds):
    return datetime.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d")


def parse_iso_date(value):
    """'2026-11-04', '2026-11-04T03:12:44.123Z', '2026-11-04 10:00+09:00' -> local
    YYYY-MM-DD. A timezone-qualified value is converted to local time."""
    if not isinstance(value, str):
        return None
    match = _ISO_RE.match(value.strip().strip("'\""))
    if not match:
        return None
    year, month, day, hour, minute, second, zone = match.groups()
    try:
        if hour is None or zone is None:
            datetime.date(int(year), int(month), int(day))
            return "%s-%s-%s" % (year, month, day)
        moment = datetime.datetime(int(year), int(month), int(day), int(hour), int(minute),
                                   int(second or 0))
        if zone == "Z":
            offset = datetime.timedelta(0)
        else:
            sign = -1 if zone[0] == "-" else 1
            digits = zone[1:].replace(":", "")
            offset = sign * datetime.timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
        aware = moment.replace(tzinfo=datetime.timezone(offset))
        return aware.astimezone().strftime("%Y-%m-%d")
    except ValueError:
        return None


def mtime_date(path):
    try:
        return local_date_from_epoch(os.stat(path).st_mtime)
    except OSError:
        return None


def read_text(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except (IOError, OSError):
        return None
    text = data.decode("utf-8", "replace")
    return text.replace("\r\n", "\n")


def loose_frontmatter(text):
    """Top-level frontmatter fields, tolerant of what the strict parser
    rejects (memory files carry a nested 'metadata:' block). Nested keys
    are returned as 'parent.key'. Values are strings or lists of strings."""
    try:
        fm, _body = common.parse_frontmatter(text)
        return dict(fm)
    except common.FrontmatterError:
        pass
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    result = {}
    parent = None
    last_key = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[:1] in (" ", "\t")
        stripped = line.strip()
        if stripped.startswith("- ") and last_key:
            value = stripped[2:].strip().strip("'\"")
            current = result.get(last_key)
            if not isinstance(current, list):
                current = []
            current.append(value)
            result[last_key] = current
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if indented and parent:
            full = parent + "." + key
        else:
            full = key
            parent = key if not value else None
        last_key = full
        if value.startswith("[") and value.endswith("]"):
            result[full] = [item.strip().strip("'\"") for item in value[1:-1].split(",")
                            if item.strip()]
        elif value:
            result[full] = value.strip("'\"")
        else:
            result[full] = None
    return result


def first_heading(text):
    for line in (text or "").split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return None


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item.strip().strip("'\"") for item in text.split(",") if item.strip()]


def walk_files(base, suffix=None):
    """Regular files under base (relative paths, sorted), skipping hidden
    entries and symlinks."""
    found = []
    if not base or not os.path.isdir(base):
        return found
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                             and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            if suffix and not name.endswith(suffix):
                continue
            found.append(os.path.relpath(path, base).replace(os.sep, "/"))
    return found


def make_writable(path):
    """Undo T3's 0444/0555 sealing before cleanup."""
    if not os.path.lexists(path):
        return
    for dirpath, dirnames, filenames in os.walk(path):
        try:
            os.chmod(dirpath, 0o700)
        except OSError:
            pass
        for name in dirnames:
            try:
                os.chmod(os.path.join(dirpath, name), 0o700)
            except OSError:
                pass
        for name in filenames:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                try:
                    os.chmod(full, 0o600)
                except OSError:
                    pass


def write_private(path, text):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent, 0o700)
    common.atomic_write_text(path, text, mode=0o600)


# ---------------------------------------------------------------------------
# Domain resolution (contract 2)
# ---------------------------------------------------------------------------

def fs_encode(path):
    return _FS_ENCODE_RE.sub("-", path)


def fs_candidates(encoded, fs_root="/", max_visits=FS_MATCH_MAX_VISITS):
    """Existing directories whose encoded path equals `encoded`.

    Claude Code names project folders by replacing every non-alphanumeric
    character of the cwd with '-', which cannot be reversed. Walk forward
    from fs_root, descending only into entries whose encoding is a prefix of
    the remainder. Bounded by max_visits listings.
    """
    results = []
    visits = [0]
    root_enc = fs_encode(fs_root.rstrip("/"))
    if not encoded.startswith(root_enc):
        return results

    def walk(directory, remainder):
        if not remainder:
            results.append(directory)
            return
        if visits[0] >= max_visits or not remainder.startswith("-"):
            return
        visits[0] += 1
        try:
            names = os.listdir(directory)
        except OSError:
            return
        for name in sorted(names):
            piece = "-" + fs_encode(name)
            if not remainder.startswith(piece):
                continue
            rest = remainder[len(piece):]
            if rest and not rest.startswith("-"):
                continue
            child = os.path.join(directory, name)
            if os.path.isdir(child) and not os.path.islink(child):
                walk(child, rest)

    walk(fs_root.rstrip("/") or "/", encoded[len(root_enc):])
    return results


def jsonl_first_cwd(folder, max_files=JSONL_SCAN_FILES, max_lines=JSONL_SCAN_LINES):
    """First "cwd" in the session JSONL files of a Claude project folder."""
    try:
        names = sorted(name for name in os.listdir(folder) if name.endswith(".jsonl"))
    except OSError:
        return None
    for name in names[:max_files]:
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8", errors="replace") as h:
                for index, line in enumerate(h):
                    if index >= max_lines:
                        break
                    if '"cwd"' not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    cwd = row.get("cwd") if isinstance(row, dict) else None
                    if isinstance(cwd, str) and cwd:
                        return cwd
        except (IOError, OSError):
            continue
    return None


class Resolver(object):
    """Contract 2 resolution steps with per-cwd caching."""

    def __init__(self, domains, fs_root="/", remote_fn=None, home=None):
        self.domains = domains
        self.owners = dict((key.strip().lower(), value)
                           for key, value in domains.get("owners", {}).items())
        self.overrides = domains.get("overrides", {})
        self.terms = TermMatcher(domains.get("work_terms", []), home=home)
        self.fs_root = fs_root
        self.remote_fn = remote_fn or (lambda cwd: common.git_remote_urls(cwd, timeout=2.0))
        self.home = home
        self.remote_failures = 0
        self._cwd_cache = {}
        self._folder_cache = {}

    def override(self, source_id):
        return self.overrides.get(source_id)

    def owner_domain(self, owner):
        if not owner:
            return None
        return self.owners.get(owner.strip().lower())

    def cwd_domain(self, cwd):
        """All remotes of cwd, any work wins (common.domain_for_remotes)."""
        if not cwd:
            return None
        if cwd in self._cwd_cache:
            return self._cwd_cache[cwd]
        domain = None
        if os.path.isdir(cwd) and not common.undeterminable_cwd(cwd, self.home):
            urls = self.remote_fn(cwd)
            if urls:
                domain = common.domain_for_remotes(urls, self.owners)
            elif urls is None and (os.path.exists(os.path.join(cwd, ".git"))
                                   or not os.access(cwd, os.R_OK | os.X_OK)):
                # A repo whose remotes cannot be read (e.g. macOS privacy for
                # a launchd job under ~/Desktop) is not the same as no remote.
                self.remote_failures += 1
        self._cwd_cache[cwd] = domain
        return domain

    def memory_folder(self, projects_dir, folder):
        """(domain, cwd) for a Claude project folder: the sibling JSONL's
        first cwd, else filesystem candidates that agree on one domain."""
        if folder in self._folder_cache:
            return self._folder_cache[folder]
        cwd = jsonl_first_cwd(os.path.join(projects_dir, folder))
        domain = None
        if cwd and os.path.isdir(cwd):
            domain = self.cwd_domain(cwd)
        else:
            candidates = fs_candidates(folder, self.fs_root)
            domains = set(self.cwd_domain(candidate) for candidate in candidates)
            if len(domains) == 1:
                domain = domains.pop()
                if domain is not None and len(candidates) == 1:
                    cwd = candidates[0]
        result = (domain, cwd)
        self._folder_cache[folder] = result
        return result

    def handoff_domain(self, fm, extra_terms=()):
        """Handoff/design: pr_url or branch org, else work_terms on tags/topic."""
        pr_url = fm.get("pr_url")
        if isinstance(pr_url, str):
            info = common.parse_remote_url(pr_url)
            domain = self.owner_domain(info.owner if info else None)
            if domain:
                return domain, "handoff_pr"
        branch = fm.get("branch")
        if isinstance(branch, str) and branch.strip():
            info = common.parse_remote_url(branch)
            owner = info.owner if info else None
            if owner is None and ":" in branch:
                left = branch.split(":", 1)[0].strip()
                if left and "/" not in left:
                    owner = left
            domain = self.owner_domain(owner)
            if domain:
                return domain, "handoff_branch"
        fields = as_list(fm.get("tags")) + as_list(fm.get("topic")) + list(extra_terms)
        if self.terms.hits(*fields):
            return "work", "work_terms"
        return None, None


class TraycerEpics(object):
    """epic_id -> domain from the read-only epic-homes DB: the epic's single
    workspace (git remotes) or, when it has no workspace path, its single
    repo identifier."""

    def __init__(self, path, resolver, warnings):
        self.path = path
        self.resolver = resolver
        self.warnings = warnings
        self._payloads = None
        self._cache = {}

    def _load(self):
        self._payloads = {}
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            conn = open_ro(self.path)
        except sqlite3.Error:
            self.warnings.append("traycer_epics_unavailable")
            return
        try:
            if not has_columns(conn, "local_epic", TRAYCER_EPIC_COLUMNS):
                self.warnings.append("traycer_epics_schema")
                return
            for epic_id, payload in conn.execute(
                    "SELECT epic_id, creation_payload FROM local_epic"):
                try:
                    self._payloads[epic_id] = json.loads(payload) if payload else {}
                except ValueError:
                    self._payloads[epic_id] = {}
        except sqlite3.Error:
            self.warnings.append("traycer_epics_unavailable")
        finally:
            conn.close()

    def domain(self, epic_id):
        if epic_id in self._cache:
            return self._cache[epic_id]
        if self._payloads is None:
            self._load()
        payload = self._payloads.get(epic_id) or {}
        result = (None, None)
        workspaces = sorted(set(
            ws.get("workspacePath") for ws in payload.get("workspaces") or []
            if isinstance(ws, dict) and isinstance(ws.get("workspacePath"), str)))
        repos = sorted(set(
            (str(repo.get("owner") or ""), str(repo.get("repo") or ""))
            for repo in payload.get("repoIdentifiers") or [] if isinstance(repo, dict)))
        if len(workspaces) == 1:
            domain = self.resolver.cwd_domain(workspaces[0])
            if domain:
                result = (domain, workspaces[0])
        # The repo-identifier fallback applies only when the epic has no
        # workspace path: a workspace whose remotes are undetermined (mixed
        # or unknown owners) stays unresolved (contract 2).
        if result[0] is None and not workspaces and len(repos) == 1:
            domain = self.resolver.owner_domain(repos[0][0])
            if domain:
                result = (domain, workspaces[0] if len(workspaces) == 1 else None)
        self._cache[epic_id] = result
        return result


def open_ro(path):
    uri = "file:%s?mode=ro" % urllib.parse.quote(os.path.abspath(path), safe="/")
    conn = sqlite3.connect(uri, uri=True, timeout=1.0)
    conn.execute("PRAGMA query_only = 1")
    return conn


def has_columns(conn, table, columns):
    rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    names = set(row[1] for row in rows)
    return bool(rows) and all(column in names for column in columns)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _item(source_id, kind, text, date, domain, step, title, **extra):
    item = {"id": source_id, "kind": kind, "text": text, "date": date,
            "domain": domain, "step": step, "title": title}
    item.update(extra)
    return item


def discover_memory(paths, resolver):
    items = []
    base = paths.projects_dir
    if not base or not os.path.isdir(base):
        return items, False
    for folder in sorted(os.listdir(base)):
        memdir = os.path.join(base, folder, "memory")
        if folder.startswith(".") or not os.path.isdir(memdir):
            continue
        for rel in walk_files(memdir, ".md"):
            if os.path.basename(rel) == "MEMORY.md":
                continue
            path = os.path.join(memdir, rel)
            text = read_text(path)
            if text is None:
                continue
            fm = loose_frontmatter(text)
            date = parse_iso_date(fm.get("metadata.modified") or fm.get("modified")) \
                or mtime_date(path)
            title = fm.get("name") if isinstance(fm.get("name"), str) else None
            items.append(_item(make_id(KIND_MEMORY, "%s/%s" % (folder, rel)), KIND_MEMORY, text,
                               date, None, None, title or os.path.splitext(os.path.basename(rel))[0],
                               folder=folder))
    return items, True


def resolve_memory(item, paths, resolver):
    domain, cwd = resolver.memory_folder(paths.projects_dir, item["folder"])
    if domain:
        return domain, "remote"
    if resolver.terms.hits(cwd, item["folder"], item["text"]):
        return "work", "work_terms"
    return None, None


def discover_docs(base, kind):
    items = []
    if not base or not os.path.isdir(base):
        return items, False
    for rel in walk_files(base, ".md"):
        path = os.path.join(base, rel)
        text = read_text(path)
        if text is None:
            continue
        fm = loose_frontmatter(text)
        date = parse_iso_date(fm.get("date")) if isinstance(fm.get("date"), str) else None
        if date is None:
            match = _DATE_PREFIX_RE.match(os.path.basename(rel))
            if match:
                date = parse_iso_date("%s-%s-%s" % match.groups())
        date = date or mtime_date(path)
        title = fm.get("topic") if isinstance(fm.get("topic"), str) else None
        title = title or first_heading(text) or os.path.splitext(os.path.basename(rel))[0]
        folders = rel.split("/")[:-1]
        items.append(_item(make_id(kind, rel), kind, text, date, None, None, title,
                           fm=fm, folders=folders))
    return items, True


def discover_inbox(root):
    items = []
    for domain in common.DOMAINS:
        base = os.path.join(root, common.INBOX_DIRNAME, domain)
        for rel in walk_files(base):
            path = os.path.join(base, rel)
            text = read_text(path)
            if text is None:
                continue
            title = first_heading(text) or os.path.splitext(os.path.basename(rel))[0]
            items.append(_item(make_id(KIND_INBOX, "%s/%s" % (domain, rel)), KIND_INBOX, text,
                               mtime_date(path), domain, "inbox", title,
                               origin=path, origin_hash=sha256_file(path)))
    return items


def _template_lines(name):
    """Lines of the shipped root template's untagged '## 내 메모' text."""
    for base in (os.path.join(SCRIPTS_DIR, "templates"),
                 os.path.join(os.path.dirname(SCRIPTS_DIR), "templates")):
        text = read_text(os.path.join(base, "root", name))
        if text is not None:
            return set(line.strip() for line in untagged_notes(text).splitlines())
    return set()


def untagged_notes(text):
    """Text directly under root '## 내 메모', before the first level 1-3
    heading (common.atx_heading spellings, fix round 3)."""
    _before, notes = common.split_my_notes(text or "")
    out = []
    for line in notes.splitlines(True)[1:]:
        heading = common.atx_heading(line)
        if heading is not None and heading[0] <= 3:
            break
        out.append(line)
    return "".join(out)


def discover_root_notes(root, warnings):
    """One notes:<domain>/<page> source per non-empty '### <domain>' part of
    root now.md/about-me.md '## 내 메모' (D16): a notes-only edit reaches the
    next draft even when nothing else changed. Text directly under '## 내
    메모' (outside the subsections) is never staged; it only warns."""
    items = []
    for name in ROOT_DRAFT_PAGES:
        path = os.path.join(root, name)
        text = read_text(path)
        if not text:
            continue
        template = _template_lines(name)
        stray = [line for line in untagged_notes(text).splitlines()
                 if line.strip() and line.strip() not in template]
        if stray:
            warnings.append("my_notes_untagged:%s" % name)
        _before, notes = common.split_my_notes(text)
        ambiguity = common.my_notes_ambiguity(notes)
        if ambiguity is not None:
            # Fix round 2: no domain's part is staged; the source already
            # recorded stays as it was (notes are not a deletable kind).
            # Fix round 3: a domain-named heading the parser cannot place
            # ('#### work', '> ### work', setext) holds them back the same way.
            code = ("my_notes_unbalanced_fence" if ambiguity == "fence"
                    else "my_notes_misplaced_heading")
            warnings.append("%s:%s" % (code, name))
            continue
        for domain in common.DOMAINS:
            part = common.my_notes_subsection(notes, domain)
            if not part.strip():
                continue
            items.append(_item(make_id(KIND_NOTES, "%s/%s" % (domain, name)), KIND_NOTES,
                               part, mtime_date(path), domain, "notes",
                               "내 메모 (%s)" % name))
    return items


def _prompt_record(text, millis, label, cwd=None, epic=None, session=None):
    try:
        seconds = float(millis) / 1000.0
    except (TypeError, ValueError):
        return None
    if not isinstance(text, str):
        return None
    text = text.replace("\r\n", "\n").strip()
    if not text or _BARE_SLASH_RE.match(text):
        return None
    if len(text) > PROMPT_MAX_CHARS:
        text = text[:PROMPT_MAX_CHARS] + "\n…(잘림)"
    moment = datetime.datetime.fromtimestamp(seconds)
    return {"text": text, "ts": seconds, "date": moment.strftime("%Y-%m-%d"),
            "time": moment.strftime("%H:%M"), "label": label, "cwd": cwd, "epic": epic,
            "session": session}


def read_history(path, since_date, warnings):
    """history.jsonl rows: display, project, timestamp. pastedContents is
    never read into a record."""
    records = []
    if not path or not os.path.isfile(path):
        return records
    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except (IOError, OSError):
        warnings.append("history_unreadable")
        return records
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            project = row.get("project") if isinstance(row.get("project"), str) else None
            label = os.path.basename(project.rstrip("/")) if project else "?"
            session = row.get("sessionId") if isinstance(row.get("sessionId"), str) else None
            record = _prompt_record(row.get("display"), row.get("timestamp"), label, cwd=project,
                                    session=session)
            if record and record["date"] >= since_date:
                records.append(record)
    return records


def read_traycer(path, since_date, warnings):
    """Traycer chat-search DB, read-only: tier='user' AND inter_agent=0 in
    chats that are not deleted. Skipped (with a warning) when the schema is
    not the expected one or the DB cannot be opened."""
    records = []
    if not path or not os.path.isfile(path):
        return records
    try:
        conn = open_ro(path)
    except sqlite3.Error:
        warnings.append("traycer_db_unavailable")
        return records
    try:
        if not (has_columns(conn, "search_doc", TRAYCER_DOC_COLUMNS)
                and has_columns(conn, "search_chat", TRAYCER_CHAT_COLUMNS)):
            warnings.append("traycer_db_schema")
            return records
        since = datetime.datetime.strptime(since_date, "%Y-%m-%d")
        since_ms = int(since.timestamp() * 1000)
        rows = conn.execute(
            "SELECT d.text, d.created_at, c.epic_id, c.chat_key FROM search_doc d "
            "JOIN search_chat c ON c.chat_key = d.chat_key "
            "WHERE d.tier = 'user' AND d.inter_agent = 0 AND c.lifecycle_state != 'deleted' "
            "AND d.created_at >= ? ORDER BY d.created_at, d.id", (since_ms,))
        for text, created_at, epic_id, chat_key in rows:
            record = _prompt_record(text, created_at, "traycer", epic=epic_id, session=chat_key)
            if record:
                records.append(record)
    except sqlite3.Error:
        warnings.append("traycer_db_unavailable")
    finally:
        conn.close()
    return records


def render_digest(date, domain, records):
    lines = ["# 프롬프트 · %s · %s" % (date, domain), ""]
    for record in records:
        lines.append("## %s · %s" % (record["time"], record["label"]))
        lines.append("")
        lines.append(record["text"])
        lines.append("")
    return "\n".join(lines)


def resolve_prompts(records, resolver, epics, classes=None, classifier=None):
    """Entries {record, domain, sessions, via} for all prompts, deduped. A
    prompt seen twice counts as work if any copy does. A prompt its folder
    says nothing about goes to work on a work_terms hit, else classify.py
    decides (via says how)."""
    merged = collections.OrderedDict()
    for record in sorted(records, key=lambda r: (r["ts"], r["label"], r["text"])):
        if record["epic"] is not None:
            domain, cwd = epics.domain(record["epic"])
            if cwd:
                record = dict(record, label="traycer · " + os.path.basename(cwd.rstrip("/")))
        else:
            domain = resolver.cwd_domain(record["cwd"])
            if domain is None and record["cwd"] and resolver.terms.hits(record["cwd"]):
                domain = "work"
            if record["cwd"] and resolver.home and (
                    os.path.normpath(record["cwd"]) == os.path.normpath(resolver.home)):
                # The basename of home is the account name, which may be a
                # work term; in a digest it would quarantine the whole day.
                record = dict(record, label="~")
        if domain is None and resolver.terms.hits(record["text"]):
            domain = "work"
        key = (record["date"], record["time"], record["text"])
        sessions = {record["session"]} if record.get("session") else set()
        entry = merged.get(key)
        if entry is None:
            merged[key] = {"record": record, "domain": domain, "sessions": sessions,
                           "via": "folder" if domain else None}
        else:
            entry["sessions"] |= sessions
            if domain == "work" or entry["domain"] is None:
                entry["domain"] = domain or entry["domain"]
                entry["via"] = "folder" if entry["domain"] else None
    entries = list(merged.values())
    classify.resolve_sessions(entries, classes or {}, classifier)
    return entries


def build_prompt_items(records, resolver, epics, classes=None, classifier=None):
    """Daily digests per domain (D4). Personal prompts hitting work_terms are
    quarantined one by one; unresolved and quarantined prompts are tracked
    per day only for counting."""
    buckets = collections.OrderedDict()
    for entry in resolve_prompts(records, resolver, epics, classes, classifier):
        record, domain = entry["record"], entry["domain"]
        if domain == "personal" and resolver.terms.hits(record["text"]):
            bucket = STATUS_QUARANTINED
        elif domain in common.DOMAINS:
            bucket = domain
        else:
            bucket = STATUS_UNRESOLVED
        buckets.setdefault((bucket, record["date"]), []).append(record)
    items = []
    for (bucket, date), group in sorted(buckets.items()):
        if bucket in common.DOMAINS:
            text = render_digest(date, bucket, group)
            items.append(_item(make_id(KIND_PROMPTS, "%s/%s" % (bucket, date)), KIND_PROMPTS,
                               text, date, bucket, "prompt_cwd",
                               "프롬프트 %s (%d)" % (date, len(group)), prompt_count=len(group),
                               keys=sorted(classify.prompt_key(r) for r in group),
                               key_times=dict((classify.prompt_key(r), r["time"]) for r in group)))
        else:
            text = "\n".join("%s %s %s" % (r["time"], r["label"], r["text"]) for r in group)
            label = "quarantine" if bucket == STATUS_QUARANTINED else "unresolved"
            items.append(_item(make_id(KIND_PROMPTS, "%s/%s" % (label, date)), KIND_PROMPTS,
                               text, date, None, None, "프롬프트 %s" % date,
                               forced_status=bucket, prompt_count=len(group),
                               keys=sorted(classify.prompt_key(r) for r in group)))
    return items


# ---------------------------------------------------------------------------
# State files
# ---------------------------------------------------------------------------

def sources_path(root):
    return os.path.join(common.state_dir(root), SOURCES_JSON)


def prepare_json_path(root):
    return os.path.join(common.state_dir(root), PREPARE_JSON)


def snapshots_dir(root):
    return os.path.join(common.state_dir(root), "snapshots")


def load_sources(root):
    """.state/sources.json; other top-level keys (mentions, ...) are kept."""
    path = sources_path(root)
    if not os.path.exists(path):
        data = collections.OrderedDict()
        data["schema_version"] = common.SCHEMA_VERSION
        data["sources"] = collections.OrderedDict()
        return data
    data = common.load_json_file(path)
    if not isinstance(data, dict) or not isinstance(data.get("sources", {}), dict):
        raise common.WikiError("sources_json_invalid", "%s is not a sources map" % path)
    data.setdefault("sources", collections.OrderedDict())
    return data


def save_sources(root, data):
    common.ensure_private_dir(common.state_dir(root))
    common.atomic_write_text(sources_path(root), common.dumps_json(data), mode=0o600)


def read_snapshot(root, entry):
    rel = entry.get("snapshot") if entry else None
    if not rel:
        return None
    return read_text(os.path.join(common.state_dir(root), rel))


# ---------------------------------------------------------------------------
# Manual edits (D1, panel: capture before base_sha)
# ---------------------------------------------------------------------------

def _manual_scope(path):
    if path in ROOT_DRAFT_PAGES:
        return True
    head = path.split("/", 1)[0]
    if head not in common.DOMAINS or "/" not in path:
        return False
    return ("/%s/" % common.DRAFTS_DIRNAME) not in ("/" + path)


def dirty_paths(root):
    """[(status, path)] of every uncommitted change in main (ignored files
    left out)."""
    proc = common.wiki_git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all",
                                  "--no-renames"])
    out = proc.stdout.decode("utf-8", "replace")
    result = []
    for entry in out.split("\0"):
        if len(entry) < 4:
            continue
        result.append((entry[:2], entry[3:]))
    return result


def dirty_pages(root):
    """[(status, path)] of uncommitted human changes in main that absorb owns:
    domain folders and root now.md/about-me.md. Ignored files are left out."""
    return [(status, path) for status, path in dirty_paths(root) if _manual_scope(path)]


def root_untracked_notes(root):
    """Untracked .md files outside absorb's scope (Obsidian puts new and
    daily notes at the vault root by default). They are never absorbed;
    prepare only counts them (root_untracked_notes:<n>)."""
    return len([path for status, path in dirty_paths(root)
                if status == "??" and path.endswith(".md") and not _manual_scope(path)
                and not path.startswith(common.INBOX_DIRNAME + "/")])


def personal_path_term_count(root, terms):
    """Personal pages in main whose path hits work_terms. verify keeps them
    out of index.md, links and query; the human should rename them."""
    count = 0
    base = os.path.join(root, "personal")
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.endswith(".md"):
                rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
                if terms.hits(rel):
                    count += 1
    return count


GENERATED_ROOT_FILES = ("index.md", "log.md")


def restore_generated(root, now, warnings):
    """index.md and log.md are verify-owned. A human edit there would defer
    them on every run (main differs from base_sha), so it is backed up to
    .state/backups/ and the file restored to HEAD before base_sha is taken.
    A SCHEMA.md edit only warns (the LLM reads the committed copy).
    domains.json is read from the working tree and init asks the user to
    edit it, so its uncommitted state is normal and not warned about."""
    stamp = now.strftime("%Y%m%dT%H%M%S")
    for status, path in dirty_paths(root):
        if path in GENERATED_ROOT_FILES:
            if common.wiki_git(root, ["cat-file", "-e", "HEAD:%s" % path], check=False).returncode:
                continue
            full = os.path.join(root, path)
            if os.path.isfile(full) and not os.path.islink(full):
                backup = os.path.join(common.state_dir(root), "backups")
                common.ensure_private_dir(backup)
                shutil.copyfile(full, os.path.join(backup, "%s.%s" % (path, stamp)))
                os.chmod(os.path.join(backup, "%s.%s" % (path, stamp)), 0o600)
            common.wiki_git(root, ["checkout", "HEAD", "--", path])
            warnings.append("generated_restored:%s" % path)
        elif path == "SCHEMA.md" and "?" not in status:
            warnings.append("config_dirty:%s" % path)


def _dirty_secrets(root, paths, allow, known_ids=None):
    """(hits, unscanned) of dirty files. hits: contract-4 hits. unscanned:
    paths that exist but cannot be scanned (symlink, not a regular file,
    not UTF-8, unreadable). Paths that no longer exist (deletions) are
    neither: committing a deletion adds no content."""
    hits = []
    unscanned = []
    for path in paths:
        full = os.path.join(root, path)
        if not os.path.lexists(full):
            continue
        if os.path.islink(full) or not os.path.isfile(full):
            unscanned.append(path)
            continue
        try:
            with open(full, "rb") as handle:
                text = handle.read().decode("utf-8")
        except (IOError, OSError, UnicodeDecodeError):
            unscanned.append(path)
            continue
        if redact.scan(text, allow, known_ids):
            hits.append(path)
    return hits, unscanned


def capture_manual_edits(root, sources, now, allow=(), warnings=None):
    """Commit human edits in main and mark domain pages as pending manual
    sources. Returns the list of committed paths.

    The pending entries are saved to sources.json before the commit, so a
    prepare that fails later never leaves a committed edit without its
    manual:<page> entry (the next run would see a clean tree and the LLM
    could overwrite the human's ## 현재 상태). A crash between the save and
    the commit is harmless: the next run sees the same dirty page, keeps the
    existing entry and its original `since`.

    The dirty files are scanned (contract 4) before anything is committed.
    A file with a hit is held: never committed nor made a source, only
    counted in a `secret_found_manual:<n>` warning, so a token pasted into
    a page stays a working-tree fix instead of a history purge, and the
    other edits and sources are still absorbed (review round 3: one pasted
    document link used to stop the whole run). Files that cannot be
    scanned (not UTF-8, symlinks, special files) are held the same way
    with a `manual_unscanned:<n>` warning. A held file stays dirty in main,
    so a batch touching it is deferred like any other human edit.
    """
    dirty = dirty_pages(root)
    if not dirty:
        return []
    # Only ids sources.json records get the src-comment exemption (fix
    # round 1): a human page cites them, an unknown one is just text.
    secret, unscanned = _dirty_secrets(root, sorted(set(path for _status, path in dirty)), allow,
                                       set((sources or {}).get("sources") or {}))
    if warnings is not None:
        if secret:
            warnings.append("secret_found_manual:%d" % len(secret))
        if unscanned:
            warnings.append("manual_unscanned:%d" % len(unscanned))
    held = set(secret) | set(unscanned)
    if held:
        dirty = [(status, path) for status, path in dirty if path not in held]
        if not dirty:
            return []
    before = common.wiki_git(root, ["rev-parse", "--verify", "HEAD"]).stdout.decode().strip()
    paths = sorted(set(path for _status, path in dirty))
    entries = sources["sources"]
    for status, path in dirty:
        if path in ROOT_DRAFT_PAGES or not path.endswith(".md"):
            continue
        source_id = make_id(KIND_MANUAL, path)
        entry = entries.get(source_id)
        if "D" in status:
            if entry and entry.get("status") == STATUS_PENDING:
                del entries[source_id]
            continue
        if entry and entry.get("status") == STATUS_PENDING:
            continue
        new = collections.OrderedDict()
        new["kind"] = KIND_MANUAL
        new["domain"] = path.split("/", 1)[0]
        new["status"] = STATUS_PENDING
        new["since"] = before
        new["page"] = path
        new["date"] = now.strftime("%Y-%m-%d")
        new["op"] = "new" if status == "??" else "changed"
        entries[source_id] = new
    save_sources(root, sources)
    common.wiki_git(root, ["add", "-A", "--"] + paths)
    staged = common.wiki_git(root, ["diff", "--cached", "--quiet", "--"] + paths, check=False)
    if staged.returncode == 1:
        common.wiki_git(root, ["commit", "-q", "--no-verify", "-m", "wiki: 사람 편집 반영 (absorb 전)",
                               "--"] + paths)
    return paths


def manual_items(root, sources, base_sha, resolver):
    items = []
    for source_id, entry in list(sources["sources"].items()):
        if entry.get("kind") != KIND_MANUAL or entry.get("status") != STATUS_PENDING:
            continue
        page = entry.get("page")
        path = os.path.join(root, page) if page else None
        text = read_text(path) if path and os.path.isfile(path) else None
        if text is None:
            del sources["sources"][source_id]
            continue
        diff = common.wiki_git(root, ["diff", "--no-color", "--no-ext-diff",
                                      entry.get("since") or base_sha, base_sha, "--", page],
                               check=False).stdout.decode("utf-8", "replace")
        items.append(_item(source_id, KIND_MANUAL, text, entry.get("date"), entry.get("domain"),
                           "manual", first_heading(text) or page, manual_diff=diff,
                           manual_op=entry.get("op") or "changed", page=page))
    return items


# ---------------------------------------------------------------------------
# Planning (pure-ish: reads sources, no writes)
# ---------------------------------------------------------------------------

class Plan(object):
    def __init__(self):
        self.ops = []          # dicts: id, op, domain, item (None for deleted), entry
        self.unbatched = []    # dicts: id, status, hash, kind, date, title
        self.vanished = []     # unresolved/quarantined ids no longer present
        self.counts = collections.Counter()  # quarantined / unresolved, every item
        self.redactions = collections.Counter()
        self.redaction_warnings = collections.Counter()
        self.warnings = []
        self.held_deletions = collections.Counter()
        self.known_ids = set()  # src ids redact may exempt (fix round 1)

    def changed_count(self, status):
        """Items of a status that changed since the last absorb."""
        return sum(1 for rec in self.unbatched if rec["status"] == status)


def _resolve_item(item, paths, resolver):
    override = resolver.override(item["id"])
    if override:
        return override, "override"
    if item["kind"] in (KIND_INBOX, KIND_MANUAL, KIND_NOTES):
        return item["domain"], item["step"]
    if item["kind"] == KIND_PROMPTS:
        return item["domain"], item["step"]
    if item["kind"] == KIND_MEMORY:
        return resolve_memory(item, paths, resolver)
    if item["kind"] in (KIND_HANDOFF, KIND_DESIGN):
        return resolver.handoff_domain(item.get("fm") or {}, item.get("folders") or ())
    return None, None


def moved_prompts(entry, item, observed):
    """Times of prompts this digest held that are now seen in another bucket.
    A prompt that is simply gone proves nothing, so it does not count."""
    old = (entry or {}).get("keys") or {}
    here = set((item or {}).get("keys") or ())
    return sorted(time for key, time in old.items() if key not in here and key in observed)


def plan_sources(root, items, scanned_kinds, sources, paths, resolver, domains):
    plan = Plan()
    entries = sources["sources"]
    observed = set(key for item in items for key in item.get("keys") or ())
    allow = domains.get("redact_allow", [])
    # Ids prepare itself made from file and folder names (sources.json and
    # this run's items): only these keep the src-comment exemption when
    # source text is redacted; an id-shaped span in a source is redacted
    # like any other text (fix round 1).
    plan.known_ids = set(entries) | set(item["id"] for item in items)
    known = plan.known_ids
    present = set()
    id_secrets = 0
    for item in items:
        source_id = item["id"]
        present.add(source_id)
        entry = entries.get(source_id)
        forced = item.get("forced_status")
        if not forced and redact.scan("<!-- src: %s @2000-01-01 -->" % source_id, allow, known):
            # Fix round 2: a known id gets the short-parts check too, so an
            # id made from a folder with random short parts would fail every
            # batch whose pages cite it. It stays out of batches instead.
            forced = STATUS_UNRESOLVED
            id_secrets += 1
        if forced:
            domain, step = None, None
        else:
            domain, step = _resolve_item(item, paths, resolver)
            if (domain is None and entry and entry.get("status") in (STATUS_ACTIVE, STATUS_CONSUMED)
                    and entry.get("domain") in common.DOMAINS):
                domain, step = entry["domain"], "sticky"
        if item["kind"] == KIND_MANUAL:
            # The page path counts too: a personal page named after a work
            # term would fail every batch that touches or links it (D5).
            quarantine_text = "%s\n%s" % (item.get("page") or "", item.get("manual_diff") or "")
        else:
            quarantine_text = item["text"]
        if forced:
            status = forced
        elif domain == "personal" and resolver.terms.hits(quarantine_text):
            status = STATUS_QUARANTINED
        elif domain in common.DOMAINS:
            status = STATUS_ACTIVE
        else:
            status = STATUS_UNRESOLVED
        result = redact.redact(item["text"], allow, known)
        digest = sha256_text(result.text)
        prior_active = (entry is not None and entry.get("status") in (STATUS_ACTIVE, STATUS_CONSUMED)
                        and entry.get("domain") in common.DOMAINS)
        withdraw = set(entry.get("withdraw") or []) if entry else set()

        if status != STATUS_ACTIVE:
            plan.counts[status] += 1
            if prior_active:
                withdraw.add(entry["domain"])
            if not (entry and entry.get("status") == status and entry.get("hash") == digest):
                plan.unbatched.append({"id": source_id, "status": status, "hash": digest,
                                       "kind": item["kind"], "date": item["date"],
                                       "title": item.get("title")})
        else:
            plan.redactions.update(result.counts)
            plan.redaction_warnings.update(result.warnings)
            if prior_active and entry["domain"] != domain:
                withdraw.add(entry["domain"])
            withdraw.discard(domain)
            same = (prior_active and entry["domain"] == domain and entry.get("hash") == digest)
            if item["kind"] == KIND_MANUAL:
                op = item.get("manual_op") or "changed"
                old = None
                diff_text = redact.redact(item.get("manual_diff") or "", allow, known).text
            else:
                op = "changed" if prior_active and entry["domain"] == domain else "new"
                old = read_snapshot(root, entry) if op == "changed" else None
                diff_text = None
                if old is not None:
                    diff_text = "".join(difflib.unified_diff(
                        old.splitlines(True), result.text.splitlines(True),
                        fromfile="before", tofile="after", n=3))
                    moved = moved_prompts(entry, item, observed)
                    if moved:
                        diff_text = "옮겨진 프롬프트 시각: %s\n%s" % (", ".join(moved), diff_text)
            if not same:
                plan.ops.append({"id": source_id, "op": op, "domain": domain, "item": item,
                                 "text": result.text, "hash": digest, "diff": diff_text,
                                 "step": step, "entry": entry})
        for old_domain in sorted(withdraw):
            plan.ops.append({"id": source_id, "op": "deleted", "domain": old_domain, "item": None,
                             "entry": entry, "date": (entry or {}).get("date")
                             or item["date"]})

    if id_secrets:
        plan.warnings.append("source_id_secret:%d" % id_secrets)
    # Disappeared sources.
    vanished = collections.defaultdict(list)
    active_by_kind = collections.Counter()
    for source_id, entry in entries.items():
        kind = entry.get("kind") or source_id.split(":", 1)[0]
        status = entry.get("status")
        if status in (STATUS_ACTIVE,) and kind in DELETABLE_KINDS:
            active_by_kind[kind] += 1
        if source_id in present:
            continue
        if status in (STATUS_UNRESOLVED, STATUS_QUARANTINED):
            plan.vanished.append(source_id)
            continue
        if kind == KIND_MANUAL:
            continue
        withdraw = set(entry.get("withdraw") or [])
        if status == STATUS_ACTIVE and kind in DELETABLE_KINDS and kind in scanned_kinds:
            vanished[kind].append(source_id)
        if (status == STATUS_ACTIVE and kind == KIND_PROMPTS
                and moved_prompts(entry, None, observed)):
            plan.ops.append({"id": source_id, "op": "deleted", "domain": entry["domain"],
                             "item": None, "entry": entry, "date": entry.get("date")})
        for old_domain in sorted(withdraw):
            plan.ops.append({"id": source_id, "op": "deleted", "domain": old_domain, "item": None,
                             "entry": entry, "date": entry.get("date")})
    for kind, ids in sorted(vanished.items()):
        if len(ids) >= MASS_DELETE_MIN and len(ids) * 2 > active_by_kind[kind]:
            plan.held_deletions[kind] = len(ids)
            plan.warnings.append("mass_deletion_held:%s" % kind)
            continue
        for source_id in ids:
            entry = entries[source_id]
            plan.ops.append({"id": source_id, "op": "deleted", "domain": entry["domain"],
                             "item": None, "entry": entry, "date": entry.get("date")})
    return plan


def prompt_ask(root, prompt_classifier, domains, warnings, since_date):
    """The classifier callback resolve_prompts takes, or None."""
    if prompt_classifier is None:
        return None
    classes = classify.load_classes(root)

    def ask(pending):
        return prompt_classifier(root, pending, classes, domains, warnings, since_date)
    return ask


def prompt_window(settings, now):
    prompt_days = settings.get("prompt_days", DEFAULT_PROMPT_DAYS)
    if isinstance(prompt_days, bool) or not isinstance(prompt_days, int) or prompt_days < 1:
        raise common.ConfigError("settings_invalid", "settings.json: prompt_days must be >= 1")
    return (now - datetime.timedelta(days=prompt_days - 1)).strftime("%Y-%m-%d")


def prompt_entries(root, environ=None, paths=None, now=None, prompt_classifier=None):
    """Entries for `wiki prompts`: the same resolution absorb uses."""
    environ = os.environ if environ is None else environ
    now = now or datetime.datetime.now()
    paths = paths or SourcePaths.from_environ(environ)
    domains = common.load_domains(root)
    since_date = prompt_window(common.load_settings(root), now)
    resolver = Resolver(domains, home=environ.get("HOME") or os.path.expanduser("~"))
    warnings = []
    epics = TraycerEpics(paths.traycer_epics_db, resolver, warnings)
    records = read_history(paths.history_path, since_date, warnings)
    records += read_traycer(paths.traycer_db, since_date, warnings)
    entries = resolve_prompts(records, resolver, epics, classify.load_classes(root),
                              prompt_ask(root, prompt_classifier, domains, warnings, since_date))
    return entries, since_date, warnings


def gather(root, paths, resolver, domains, settings, now, warnings, prompt_classifier=None):
    """All discovered items (except manual) and the kinds that were scanned."""
    since_date = prompt_window(settings, now)
    items = []
    scanned = set()
    mem, ok = discover_memory(paths, resolver)
    items += mem
    if ok:
        scanned.add(KIND_MEMORY)
    for base, kind in ((paths.handoff_dir, KIND_HANDOFF), (paths.design_dir, KIND_DESIGN)):
        docs, ok = discover_docs(base, kind)
        items += docs
        if ok:
            scanned.add(kind)
    items += discover_inbox(root)
    items += discover_root_notes(root, warnings)
    epics = TraycerEpics(paths.traycer_epics_db, resolver, warnings)
    records = read_history(paths.history_path, since_date, warnings)
    records += read_traycer(paths.traycer_db, since_date, warnings)
    items += build_prompt_items(records, resolver, epics, classify.load_classes(root),
                                prompt_ask(root, prompt_classifier, domains, warnings, since_date))
    if resolver.remote_failures:
        warnings.append("remote_lookup_failed:%d" % resolver.remote_failures)
    return items, scanned


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------

def clear_staging(root):
    staging = common.staging_dir(root)
    if os.path.lexists(staging):
        make_writable(staging)
        for name in os.listdir(staging):
            full = os.path.join(staging, name)
            if os.path.isdir(full) and not os.path.islink(full):
                shutil.rmtree(full)
            else:
                os.unlink(full)
    common.ensure_private_dir(staging)


def batch_dir(root, batch_id):
    return os.path.join(common.staging_dir(root), str(batch_id))


def staging_manifest(root, batch_id):
    """{relpath under staging/<batch>: sha256} of every file, for verify."""
    base = batch_dir(root, batch_id)
    manifest = collections.OrderedDict()
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            manifest[os.path.relpath(full, base).replace(os.sep, "/")] = sha256_file(full)
    return manifest


def seal_batch(root, batch_id):
    """Files 0444 and directories 0555 before the LLM step (panel D-1)."""
    base = batch_dir(root, batch_id)
    for dirpath, _dirnames, filenames in os.walk(base, topdown=False):
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), 0o444)
        os.chmod(dirpath, 0o555)


def check_batch_staging(root, batch_id, expected=None):
    """Problems with staging/<batch> against the prepare manifest: extra,
    missing or changed files. Empty list when intact."""
    if expected is None:
        pending = load_prepare(root)
        expected = pending["batches"][str(batch_id)]["manifest"]
    actual = staging_manifest(root, batch_id)
    problems = []
    for rel in sorted(set(expected) | set(actual)):
        if rel not in actual:
            problems.append("missing:" + rel)
        elif rel not in expected:
            problems.append("extra:" + rel)
        elif actual[rel] != expected[rel]:
            problems.append("changed:" + rel)
    return problems


def _context_notes(root, domain, resolver, allow, plan):
    """That domain's '### <domain>' subsection of root '## 내 메모' (D16)."""
    out = []
    for name in ROOT_DRAFT_PAGES:
        text = read_text(os.path.join(root, name))
        if not text:
            continue
        _before, notes = common.split_my_notes(text)
        part = common.my_notes_subsection(notes, domain)
        if not part.strip():
            continue
        if domain == "personal" and resolver.terms.hits(part):
            # Counted once, as the notes:<domain>/<page> source (plan_sources).
            plan.warnings.append("my_notes_quarantined:%s" % name)
            continue
        out.append((name, redact.redact(part, allow, plan.known_ids).text))
    return out


def write_staging(root, plan, max_sources, resolver, domains):
    """Group ops into batches (one domain, <= max_sources) and write files.
    Returns (run batches, prepare.json batch records)."""
    allow = domains.get("redact_allow", [])
    by_domain = collections.OrderedDict((domain, []) for domain in common.DOMAINS)
    seen = set()
    for op in plan.ops:
        key = (op["id"], op["op"], op["domain"])
        if key in seen:
            continue
        seen.add(key)
        by_domain[op["domain"]].append(op)
    batches = []
    records = collections.OrderedDict()
    batch_id = 0
    for domain, ops in by_domain.items():
        ops.sort(key=lambda o: ((o.get("item") or {}).get("date") or o.get("date") or "",
                                o["id"], o["op"]))
        context = _context_notes(root, domain, resolver, allow, plan) if ops else []
        for start in range(0, len(ops), max_sources):
            chunk = ops[start:start + max_sources]
            batch_id += 1
            base = batch_dir(root, batch_id)
            common.ensure_private_dir(base)
            sources = []
            record_sources = collections.OrderedDict()
            for op in chunk:
                item = op.get("item")
                date = (item or {}).get("date") or op.get("date") or "1970-01-01"
                redacted_rel = diff_rel = None
                stem = safe_name(op["id"])
                if op["op"] != "deleted":
                    redacted_rel = "staging/%d/%s.md" % (batch_id, stem)
                    write_private(os.path.join(common.state_dir(root), redacted_rel), op["text"])
                    if op.get("diff"):
                        diff_rel = "staging/%d/%s.diff" % (batch_id, stem)
                        write_private(os.path.join(common.state_dir(root), diff_rel), op["diff"])
                sources.append(common.make_source(op["id"], domain, op["op"], date,
                                                  redacted_rel, diff_rel))
                rec = collections.OrderedDict()
                rec["op"] = op["op"]
                rec["kind"] = (item or {}).get("kind") or (op.get("entry") or {}).get("kind") \
                    or op["id"].split(":", 1)[0]
                rec["date"] = date
                if item:
                    rec["hash"] = op["hash"]
                    rec["title"] = item.get("title")
                    rec["staged"] = redacted_rel
                    if item.get("key_times"):
                        rec["keys"] = item["key_times"]
                    if item.get("origin"):
                        rec["origin"] = item["origin"]
                        rec["origin_hash"] = item["origin_hash"]
                record_sources["%s|%s" % (op["id"], op["op"])] = rec
            context_rel = []
            for name, text in context:
                rel = "staging/%d/context/%s" % (batch_id, name)
                write_private(os.path.join(common.state_dir(root), rel), text)
                context_rel.append(rel)
            batch = common.make_batch(batch_id, sources)
            batches.append(batch)
            record = collections.OrderedDict()
            record["domain"] = domain
            record["sources"] = record_sources
            record["context"] = context_rel
            record["manifest"] = staging_manifest(root, batch_id)
            records[str(batch_id)] = record
    return batches, records


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def _head(root):
    proc = common.wiki_git(root, ["rev-parse", "--verify", "-q", "HEAD"], check=False)
    sha = proc.stdout.decode("ascii", "replace").strip()
    if proc.returncode != 0 or not sha:
        raise common.WikiError("not_initialized", "%s has no commit; run wiki init" % root)
    return sha


def _summary(plan, batches):
    pending = collections.Counter()
    for batch in batches:
        for source in batch["sources"]:
            pending[source["domain"]] += 1
    summary = collections.OrderedDict()
    summary["batches"] = len(batches)
    summary["sources"] = sum(len(batch["sources"]) for batch in batches)
    summary["by_domain"] = dict((domain, pending.get(domain, 0)) for domain in common.DOMAINS)
    summary["quarantined"] = plan.changed_count(STATUS_QUARANTINED)
    summary["unresolved"] = plan.changed_count(STATUS_UNRESOLVED)
    summary["redactions"] = dict(plan.redactions)
    summary["redaction_warnings"] = dict(plan.redaction_warnings)
    summary["held_deletions"] = dict(plan.held_deletions)
    summary["warnings"] = sorted(set(plan.warnings))
    return summary


def prepare(root, environ=None, paths=None, now=None, locked=False, fs_root="/", remote_fn=None,
            prompt_classifier=None):
    """Run the prepare step. Returns a summary dict (also stored in
    prepare.json). Callers that already hold the absorb lock pass
    locked=True; a second flock on the same file in one process fails."""
    environ = os.environ if environ is None else environ
    if not locked:
        with common.wiki_lock(root):
            return prepare(root, environ, paths, now, True, fs_root, remote_fn, prompt_classifier)
    now = now or datetime.datetime.now()
    paths = paths or SourcePaths.from_environ(environ)
    if not common.is_initialized(root):
        raise common.WikiError("not_initialized", "%s is not a wiki; run wiki init" % root)
    domains = common.load_domains(root)
    guard = common.domains_guard(domains, root)
    if guard:
        raise common.WikiError(guard, "domains.json: fill in owners and work_terms before absorb")
    settings = common.load_settings(root)
    resolver = Resolver(domains, fs_root=fs_root, remote_fn=remote_fn,
                        home=environ.get("HOME") or os.path.expanduser("~"))
    sources = load_sources(root)

    warnings = []
    restore_generated(root, now, warnings)
    capture_manual_edits(root, sources, now, domains.get("redact_allow", []), warnings)
    stray = root_untracked_notes(root)
    if stray:
        # Count only: Obsidian's new-note folder should be inbox/<domain>/.
        warnings.append("root_untracked_notes:%d" % stray)
    base_sha = _head(root)
    named = personal_path_term_count(root, resolver.terms)
    if named:
        # Count only: the path itself is the leak (D5).
        warnings.append("personal_path_term:%d" % named)

    items, scanned = gather(root, paths, resolver, domains, settings, now, warnings,
                            prompt_classifier)
    items += manual_items(root, sources, base_sha, resolver)
    plan = plan_sources(root, items, scanned, sources, paths, resolver, domains)
    plan.warnings += warnings

    clear_staging(root)
    batches, records = write_staging(root, plan, settings["batch_max_sources"], resolver, domains)

    run = common.new_run(common.make_run_id(now), base_sha,
                         os.path.join(root, common.WORKTREE_DIRNAME))
    run["batches"] = batches
    # Contract 2 "반영 대기"/격리 N: only sources whose status or hash changed
    # since the last absorb (plan.unbatched), not every one in the window.
    run["quarantined"] = plan.changed_count(STATUS_QUARANTINED)
    run["unresolved"] = plan.changed_count(STATUS_UNRESOLVED)
    summary = _summary(plan, batches)

    pending = collections.OrderedDict()
    pending["schema_version"] = common.SCHEMA_VERSION
    pending["run_id"] = run["run_id"]
    pending["base_sha"] = base_sha
    pending["batches"] = records
    pending["unbatched"] = plan.unbatched
    pending["vanished"] = plan.vanished
    pending["summary"] = summary
    # sources.json may have gained pending manual entries; nothing else moves.
    save_sources(root, sources)
    write_private(prepare_json_path(root), common.dumps_json(pending))
    common.write_run(root, run)
    result = collections.OrderedDict(summary)
    result["run_id"] = run["run_id"]
    result["base_sha"] = base_sha
    return result


def load_prepare(root):
    return common.load_json_file(prepare_json_path(root), "prepare_json_missing")


def _unique_dest(directory, name):
    dest = os.path.join(directory, name)
    stem, ext = os.path.splitext(name)
    counter = 1
    while os.path.exists(dest):
        counter += 1
        dest = os.path.join(directory, "%s-%d%s" % (stem, counter, ext))
    return dest


def commit_batch(root, batch_id, run_id=None):
    """Advance source state after batch `batch_id` merged into main (T3).

    Copies each staged redacted file to snapshots/, updates sources.json,
    moves consumed inbox files to .state/inbox-done/<domain>/ (only when the
    file is unchanged since prepare) and closes pending manual sources.
    """
    pending = load_prepare(root)
    if run_id and pending.get("run_id") != run_id:
        raise common.WikiError("prepare_run_mismatch", "prepare.json is for another run")
    record = pending["batches"].get(str(batch_id))
    if record is None:
        raise common.WikiError("batch_unknown", "batch %s is not in prepare.json" % batch_id)
    domain = record["domain"]
    sources = load_sources(root)
    entries = sources["sources"]
    state = common.state_dir(root)
    common.ensure_private_dir(snapshots_dir(root))
    moved = []
    for key, rec in record["sources"].items():
        source_id, _sep, op = key.rpartition("|")
        entry = entries.get(source_id)
        if op == "deleted":
            if entry is None:
                continue
            withdraw = set(entry.get("withdraw") or [])
            withdraw.discard(domain)
            if entry.get("status") in (STATUS_ACTIVE, STATUS_CONSUMED) and entry.get("domain") == domain:
                entry["status"] = STATUS_DELETED
                snap = entry.pop("snapshot", None)
                if snap and os.path.exists(os.path.join(state, snap)):
                    os.unlink(os.path.join(state, snap))
            _set_withdraw(entry, withdraw)
            continue
        kind = rec.get("kind")
        if kind == KIND_MANUAL:
            # Kept as closed (not deleted) so verify knows the id a page
            # cites; capture_manual_edits replaces it on the next edit.
            closed = collections.OrderedDict()
            closed["kind"] = KIND_MANUAL
            closed["domain"] = domain
            closed["status"] = STATUS_CLOSED
            closed["page"] = (entry or {}).get("page") or source_id.split(":", 1)[1]
            closed["date"] = rec.get("date")
            closed["updated"] = pending.get("run_id")
            entries[source_id] = closed
            continue
        old_domain = None
        if entry and entry.get("status") in (STATUS_ACTIVE, STATUS_CONSUMED):
            old_domain = entry.get("domain")
        withdraw = set((entry or {}).get("withdraw") or [])
        if old_domain and old_domain != domain:
            withdraw.add(old_domain)
        withdraw.discard(domain)
        snap_rel = "snapshots/%s.md" % safe_name(source_id)
        shutil.copyfile(os.path.join(state, rec["staged"]), os.path.join(state, snap_rel))
        os.chmod(os.path.join(state, snap_rel), 0o600)
        status = STATUS_ACTIVE
        if kind == KIND_INBOX and rec.get("origin"):
            origin = rec["origin"]
            if os.path.isfile(origin) and sha256_file(origin) == rec.get("origin_hash"):
                done_dir = os.path.join(state, "inbox-done", domain)
                common.ensure_private_dir(os.path.join(state, "inbox-done"))
                common.ensure_private_dir(done_dir)
                dest = _unique_dest(done_dir, os.path.basename(origin))
                shutil.move(origin, dest)
                moved.append(dest)
                status = STATUS_CONSUMED
        new = collections.OrderedDict()
        new["kind"] = kind
        new["domain"] = domain
        new["status"] = status
        new["hash"] = rec.get("hash")
        new["date"] = rec.get("date")
        new["title"] = rec.get("title")
        new["snapshot"] = snap_rel
        new["updated"] = pending.get("run_id")
        if rec.get("keys"):
            # Old keys stay: a page may still rest on a prompt that rotated
            # out, and that prompt can come back in another domain.
            new["keys"] = dict((entry or {}).get("keys") or {}, **rec["keys"])
        if entry:
            for extra in entry:
                if extra not in new and extra not in ("withdraw",):
                    new[extra] = entry[extra]
        _set_withdraw(new, withdraw)
        entries[source_id] = new
    save_sources(root, sources)
    return {"batch_id": batch_id, "moved": moved}


def _set_withdraw(entry, withdraw):
    if withdraw:
        entry["withdraw"] = sorted(withdraw)
    else:
        entry.pop("withdraw", None)


def finalize_run(root):
    """Record hashes of unresolved/quarantined sources (so pending N counts
    only changes since this absorb) and drop the ones that vanished. Active
    entries are never overwritten here: their withdrawal must merge first."""
    pending = load_prepare(root)
    sources = load_sources(root)
    entries = sources["sources"]
    for rec in pending.get("unbatched", []):
        entry = entries.get(rec["id"])
        if entry and entry.get("status") in (STATUS_ACTIVE, STATUS_CONSUMED, STATUS_PENDING):
            continue
        new = collections.OrderedDict()
        new["kind"] = rec.get("kind")
        new["domain"] = None
        new["status"] = rec["status"]
        new["hash"] = rec["hash"]
        new["date"] = rec.get("date")
        new["title"] = rec.get("title")
        new["updated"] = pending.get("run_id")
        entries[rec["id"]] = new
    for rec in pending.get("unbatched", []):
        entry = entries.get(rec["id"])
        if (entry and entry.get("kind") == KIND_MANUAL and entry.get("status") == STATUS_PENDING
                and rec["status"] == STATUS_QUARANTINED):
            del entries[rec["id"]]  # a manual edit is one-shot; quarantine drops it
    for source_id in pending.get("vanished", []):
        entry = entries.get(source_id)
        if entry and entry.get("status") in (STATUS_UNRESOLVED, STATUS_QUARANTINED):
            del entries[source_id]
    save_sources(root, sources)


def pending_counts(root, environ=None, paths=None, now=None, fs_root="/", remote_fn=None):
    """Dry run for status and log.md (contract 2 "반영 대기 N"): sources whose
    hash changed since the last absorb, by domain, plus unresolved and
    quarantined counts and titles. Writes nothing and commits nothing."""
    environ = os.environ if environ is None else environ
    now = now or datetime.datetime.now()
    paths = paths or SourcePaths.from_environ(environ)
    domains = common.load_domains(root)
    settings = common.load_settings(root)
    resolver = Resolver(domains, fs_root=fs_root, remote_fn=remote_fn,
                        home=environ.get("HOME") or os.path.expanduser("~"))
    sources = load_sources(root)
    warnings = []
    items, scanned = gather(root, paths, resolver, domains, settings, now, warnings)
    plan = plan_sources(root, items, scanned, sources, paths, resolver, domains)
    counts = collections.OrderedDict((domain, 0) for domain in common.DOMAINS)
    titles = collections.OrderedDict((domain, []) for domain in common.DOMAINS)
    seen = set()
    for op in plan.ops:
        key = (op["id"], op["domain"])
        if key in seen:
            continue
        seen.add(key)
        counts[op["domain"]] += 1
        title = (op.get("item") or {}).get("title") or (op.get("entry") or {}).get("title")
        if title:
            titles[op["domain"]].append(title)
    for entry in sources["sources"].values():
        if entry.get("kind") == KIND_MANUAL and entry.get("status") == STATUS_PENDING:
            counts[entry["domain"]] += 1
    if common.is_initialized(root) and os.path.isdir(os.path.join(root, ".git")):
        for _status, path in dirty_pages(root):
            head = path.split("/", 1)[0]
            if head in common.DOMAINS:
                counts[head] += 1
    unresolved = sum(1 for rec in plan.unbatched if rec["status"] == STATUS_UNRESOLVED)
    quarantined = sum(1 for rec in plan.unbatched if rec["status"] == STATUS_QUARANTINED)
    result = collections.OrderedDict()
    result["work"] = counts["work"]
    result["personal"] = counts["personal"]
    result["unresolved"] = unresolved
    result["quarantined"] = quarantined
    result["titles"] = titles
    result["warnings"] = sorted(set(plan.warnings + warnings))
    return result


def pending_for_domain(counts, domain):
    """N for a session in `domain`: that domain's changed sources plus the
    undetermined ones (contract 2)."""
    return counts.get(domain, 0) + counts.get("unresolved", 0)
