"""Shared contracts for the wiki skill (Python 3.9, stdlib only).

This module is imported by the CLI (wiki.py), the absorb pipeline and the
session hooks. Keep it import-light: no file I/O, environment reads, logging
setup or subprocess calls at import time.

Contracts implemented here (see SKILL.md and templates/SCHEMA.md):
  - WIKI_ROOT resolution
  - frontmatter subset parser/dumper (contract 3)
  - domains.json / settings.json loaders (contract 3, panel D-9)
  - git remote owner normalization and repo domain decision (D2, contract 2)
  - .state/run.json schema helpers and allowed_globs matching (contract 1)
  - absorb lock (D6, fcntl.flock)
"""

import collections
import datetime
import errno
import json
import os
import re
import subprocess
import unicodedata

SCHEMA_VERSION = 1

DOMAINS = ("work", "personal")

# Page folders per domain (plan "폴더"). personal has no people/.
DOMAIN_SUBDIRS = collections.OrderedDict([
    ("work", ("projects", "decisions", "people", "topics", "notes", "prefs")),
    ("personal", ("projects", "decisions", "topics", "notes", "prefs")),
])

ROOT_PAGES = ("index.md", "log.md", "now.md", "about-me.md")
STATE_DIRNAME = ".state"
STATE_SUBDIRS = ("snapshots", "inbox-done", "staging")
WORKTREE_DIRNAME = ".absorb-wt"
BIN_DIRNAME = ".bin"
INBOX_DIRNAME = "inbox"
DRAFTS_DIRNAME = "_drafts"  # <domain>/_drafts/ fragments (panel D-2)
STATE_MARKER = "wiki.json"  # .state/wiki.json marks an initialized root

MY_NOTES_HEADING = "## 내 메모"
CURRENT_STATE_HEADING = "## 현재 상태"

PAGE_TYPES = ("project", "decision", "person", "topic", "pref", "note")
PREF_SCOPES = ("global", "domain", "repo")
PAGE_LIST_FIELDS = ("aliases", "repos", "supersedes")
PAGE_SCALAR_FIELDS = (
    "title", "type", "domain", "status", "summary", "scope",
    "decided", "as_of", "updated",
)
PAGE_DATE_FIELDS = ("decided", "as_of", "updated")
PAGE_REQUIRED_FIELDS = ("title", "type", "domain")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:?\d{2}(:?\d{2})?)?$")


class WikiError(Exception):
    """Error with a stable reason code (used in log.md and the Slack line)."""

    def __init__(self, reason, message=""):
        Exception.__init__(self, message or reason)
        self.reason = reason


class FrontmatterError(WikiError):
    def __init__(self, message):
        WikiError.__init__(self, "frontmatter_invalid", message)


class ConfigError(WikiError):
    pass


class LockBusy(WikiError):
    def __init__(self, message="absorb lock is held by another process"):
        WikiError.__init__(self, "lock_busy", message)


# ---------------------------------------------------------------------------
# WIKI_ROOT and layout
# ---------------------------------------------------------------------------

def resolve_root(arg=None, environ=None):
    """Return the wiki root as a realpath.

    Precedence: explicit argument, then WIKI_ROOT, then ~/wiki. An empty
    value counts as unset, matching the hook guard ${WIKI_ROOT:-$HOME/wiki}.
    realpath is used everywhere because git reports realpaths
    (/tmp -> /private/tmp on macOS).
    """
    if environ is None:
        environ = os.environ
    value = arg or environ.get("WIKI_ROOT") or ""
    if not value:
        home = environ.get("HOME") or os.path.expanduser("~")
        value = os.path.join(home, "wiki")
    value = os.path.expanduser(value)
    return os.path.realpath(value)


def state_dir(root):
    return os.path.join(root, STATE_DIRNAME)


def staging_dir(root):
    """Staging lives under .state/; run.json paths are relative to .state/."""
    return os.path.join(root, STATE_DIRNAME, "staging")


def run_json_path(root):
    return os.path.join(root, STATE_DIRNAME, "run.json")


def lock_path(root):
    return os.path.join(root, STATE_DIRNAME, "absorb.lock")


def is_initialized(root):
    """True for a wiki root: the .state marker, or SCHEMA.md plus .git
    (so a root whose gitignored .state/ was deleted is still recognized)."""
    if os.path.isfile(os.path.join(root, STATE_DIRNAME, STATE_MARKER)):
        return True
    return (os.path.isfile(os.path.join(root, "SCHEMA.md"))
            and os.path.isdir(os.path.join(root, ".git")))


def atomic_write_text(path, text, mode=None):
    """Write text via a temp file and os.replace. mode applies to the file."""
    directory = os.path.dirname(path) or "."
    tmp = os.path.join(directory, ".%s.tmp-%d" % (os.path.basename(path), os.getpid()))
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def ensure_private_dir(path):
    """mkdir -p with 0700 on the leaf (staging/snapshots hold work text)."""
    if not os.path.isdir(path):
        os.makedirs(path, 0o700)
    os.chmod(path, 0o700)


# ---------------------------------------------------------------------------
# Frontmatter subset (contract 3)
#
# Supported: scalars (plain, "double", 'single'), flow lists [a, b],
# block lists (- a, any consistent indent, Obsidian writes "  - a"),
# block strings (key: | and key: |-). Every scalar stays a string; no bool,
# number or date coercion. A bare "key:" is None. Anything else raises.
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(r"^([^\s:#\-?\[\]{}&*!|>'\"%@`,][^:]*?):(?:( .*))?$")
_ITEM_RE = re.compile(r"^( *)-(?: (.*))?$")
_PLAIN_FORBIDDEN_START = set("-?:,[]{}#&*!|>'\"%@`")
_DQ_ESCAPES = {
    '"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t", "r": "\r",
    "0": "\0", "b": "\b", "f": "\f", " ": " ",
}


def split_frontmatter(text):
    """Split text into (frontmatter_text or None, body, newline).

    The body is returned byte-identical (CRLF, trailing newline). The
    frontmatter must start on the first line with '---' and end with a line
    that is exactly '---'.
    """
    if text.startswith("---\r\n"):
        newline = "\r\n"
    elif text.startswith("---\n"):
        newline = "\n"
    else:
        return None, text, "\n"
    lines = text.splitlines(True)
    offset = len(lines[0])
    collected = []
    for line in lines[1:]:
        if line.rstrip("\r\n") == "---":
            return "".join(collected), text[offset + len(line):], newline
        collected.append(line)
        offset += len(line)
    raise FrontmatterError("frontmatter is not closed with ---")


def _strip_comment(value):
    """Remove a ' #comment' tail from a plain scalar."""
    index = value.find(" #")
    if index >= 0:
        value = value[:index]
    return value.rstrip()


def _parse_double_quoted(value, where):
    out = []
    i = 1
    n = len(value)
    while i < n:
        ch = value[i]
        if ch == '"':
            rest = value[i + 1:].strip()
            if rest and not rest.startswith("#"):
                raise FrontmatterError("%s: text after closing quote" % where)
            return "".join(out)
        if ch == "\\":
            i += 1
            if i >= n:
                break
            esc = value[i]
            if esc in _DQ_ESCAPES:
                out.append(_DQ_ESCAPES[esc])
            elif esc in ("u", "x", "U"):
                width = {"x": 2, "u": 4, "U": 8}[esc]
                digits = value[i + 1:i + 1 + width]
                if len(digits) != width or not re.match(r"^[0-9A-Fa-f]+$", digits):
                    raise FrontmatterError("%s: bad \\%s escape" % (where, esc))
                out.append(chr(int(digits, 16)))
                i += width
            else:
                raise FrontmatterError("%s: unsupported escape \\%s" % (where, esc))
            i += 1
            continue
        out.append(ch)
        i += 1
    raise FrontmatterError("%s: unterminated double quote" % where)


def _parse_single_quoted(value, where):
    out = []
    i = 1
    n = len(value)
    while i < n:
        ch = value[i]
        if ch == "'":
            if i + 1 < n and value[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            rest = value[i + 1:].strip()
            if rest and not rest.startswith("#"):
                raise FrontmatterError("%s: text after closing quote" % where)
            return "".join(out)
        out.append(ch)
        i += 1
    raise FrontmatterError("%s: unterminated single quote" % where)


def _parse_scalar(raw, where):
    value = raw.strip()
    if not value or value.startswith("#"):
        return None
    if value[0] == '"':
        return _parse_double_quoted(value, where)
    if value[0] == "'":
        return _parse_single_quoted(value, where)
    if value[0] in "{&*!%@`>|[":
        raise FrontmatterError("%s: unsupported YAML syntax %r" % (where, value[:20]))
    if value.startswith("- ") or value == "-" or value.startswith("? "):
        raise FrontmatterError("%s: unsupported YAML syntax %r" % (where, value[:20]))
    value = _strip_comment(value)
    if ": " in value or value.endswith(":"):
        raise FrontmatterError("%s: nested mappings are not supported" % where)
    return value


def _split_flow_items(inner, where):
    items = []
    current = []
    quote = None
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            current.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(inner):
                current.append(inner[i + 1])
                i += 2
                continue
            if ch == quote:
                if quote == "'" and i + 1 < len(inner) and inner[i + 1] == "'":
                    current.append("'")
                    i += 2
                    continue
                quote = None
        elif ch in ("'", '"') and not "".join(current).strip():
            quote = ch
            current.append(ch)
        elif ch == ",":
            items.append("".join(current))
            current = []
        elif ch in "[]{}":
            raise FrontmatterError("%s: nested flow collections are not supported" % where)
        else:
            current.append(ch)
        i += 1
    if quote:
        raise FrontmatterError("%s: unterminated quote in flow list" % where)
    items.append("".join(current))
    if len(items) == 1 and not items[0].strip():
        return []
    if len(items) > 1 and not items[-1].strip():
        items.pop()  # trailing comma
    result = []
    for item in items:
        if not item.strip():
            raise FrontmatterError("%s: empty flow list item" % where)
        result.append(_parse_scalar(item, where))
    return result


def _parse_flow_list(value, where):
    value = value.strip()
    end = value.rfind("]")
    if end < 0:
        raise FrontmatterError("%s: unterminated flow list" % where)
    tail = value[end + 1:].strip()
    if tail and not tail.startswith("#"):
        raise FrontmatterError("%s: text after flow list" % where)
    return _split_flow_items(value[1:end], where)


def _leading_ws(line):
    return line[:len(line) - len(line.lstrip(" \t"))]


def parse_frontmatter_block(fm_text):
    """Parse the text between the --- lines into an ordered dict."""
    result = collections.OrderedDict()
    lines = [line.rstrip("\r\n") for line in fm_text.splitlines(True)]
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        where = "frontmatter line %d" % (i + 2)  # 1-based, after the opening ---
        if not line.strip() or line.startswith("#"):
            i += 1
            continue
        if "\t" in _leading_ws(line):
            raise FrontmatterError("%s: tabs are not supported" % where)
        if line[0] == " ":
            raise FrontmatterError("%s: unexpected indentation" % where)
        match = _KEY_RE.match(line)
        if not match:
            raise FrontmatterError("%s: expected 'key: value'" % where)
        key = match.group(1).rstrip()
        if key in result:
            raise FrontmatterError("%s: duplicate key %r" % (where, key))
        stripped = (match.group(2) or "").strip()
        i += 1
        if not stripped or stripped.startswith("#"):
            # Bare key: a block list follows, or the value is None.
            items = []
            indent = None
            while i < n:
                item_line = lines[i]
                item_where = "frontmatter line %d" % (i + 2)
                if not item_line.strip():
                    j = i + 1
                    while j < n and not lines[j].strip():
                        j += 1
                    following = _ITEM_RE.match(lines[j]) if j < n else None
                    if indent is not None and following and len(following.group(1)) == indent:
                        i = j
                        continue
                    break
                if "\t" in _leading_ws(item_line):
                    raise FrontmatterError("%s: tabs are not supported" % item_where)
                item = _ITEM_RE.match(item_line)
                if not item:
                    if item_line.startswith(" "):
                        raise FrontmatterError("%s: nested mappings are not supported" % item_where)
                    break
                item_indent = len(item.group(1))
                if indent is None:
                    indent = item_indent
                elif item_indent != indent:
                    raise FrontmatterError("%s: inconsistent list indentation" % item_where)
                item_value = item.group(2) or ""
                if item_value.strip().startswith("[") or item_value.strip().startswith("- "):
                    raise FrontmatterError("%s: nested lists are not supported" % item_where)
                parsed = _parse_scalar(item_value, item_where)
                items.append("" if parsed is None else parsed)
                i += 1
            result[key] = items if indent is not None else None
            continue
        if stripped[0] == "|":
            indicator = _strip_comment(stripped)
            if indicator not in ("|", "|-"):
                raise FrontmatterError("%s: only '|' and '|-' block strings are supported" % where)
            block = []
            block_indent = None
            while i < n:
                block_line = lines[i]
                if not block_line.strip():
                    block.append("")
                    i += 1
                    continue
                if "\t" in _leading_ws(block_line):
                    raise FrontmatterError("frontmatter line %d: tabs are not supported" % (i + 2))
                line_indent = len(block_line) - len(block_line.lstrip(" "))
                if line_indent == 0:
                    break
                if block_indent is None:
                    block_indent = line_indent
                elif line_indent < block_indent:
                    raise FrontmatterError(
                        "frontmatter line %d: block string is under-indented" % (i + 2))
                block.append(block_line[block_indent:])
                i += 1
            while block and block[-1] == "":
                block.pop()
            text = "\n".join(block)
            if indicator == "|" and block:
                text += "\n"
            result[key] = text
            continue
        if stripped[0] == "[":
            result[key] = _parse_flow_list(stripped, where)
            continue
        result[key] = _parse_scalar(stripped, where)
    return result


def parse_frontmatter(text):
    """Return (ordered dict, body). A page without frontmatter gives ({}, text)."""
    fm_text, body, _newline = split_frontmatter(text)
    if fm_text is None:
        return collections.OrderedDict(), body
    return parse_frontmatter_block(fm_text), body


def _has_control(value, allow=""):
    for ch in value:
        if ch in allow:
            continue
        if unicodedata.category(ch) == "Cc":
            return True
    return False


def _needs_quotes(value):
    if value == "":
        return True
    if value != value.strip():
        return True
    if value[0] in _PLAIN_FORBIDDEN_START:
        return True
    if ": " in value or " #" in value or value.endswith(":"):
        return True
    # Words such as true/false/null stay plain: the parser never coerces, and
    # quoting would turn an Obsidian checkbox (done: true) into text.
    return _has_control(value)


def _double_quote(value):
    out = ['"']
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif unicodedata.category(ch) == "Cc":
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def dump_scalar(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("frontmatter values must be str, list of str or None")
    return _double_quote(value) if _needs_quotes(value) else value


def _block_string_ok(value):
    if value in ("", "\n") or value.endswith("\n\n") or _has_control(value, allow="\n"):
        return False
    first = value.split("\n", 1)[0]
    return bool(first) and not first.startswith(" ")


def dump_frontmatter(fm, newline="\n"):
    """Render an ordered mapping back to frontmatter lines (without ---).

    Lists are written in Obsidian's block form ("  - a"); empty lists as [].
    Multi-line strings use '|' (ends with one newline) or '|-'.
    """
    lines = []
    for key, value in fm.items():
        if not isinstance(key, str) or key != key.strip() or not _KEY_RE.match(key + ":"):
            raise TypeError("unsupported frontmatter key %r" % (key,))
        if isinstance(value, (list, tuple)):
            if not value:
                lines.append("%s: []" % key)
                continue
            lines.append("%s:" % key)
            for item in value:
                if not isinstance(item, str):
                    raise TypeError("list items must be str (key %r)" % key)
                lines.append("  - %s" % dump_scalar(item))
            continue
        if value is None:
            lines.append("%s:" % key)
            continue
        if isinstance(value, str) and "\n" in value and _block_string_ok(value):
            indicator = "|" if value.endswith("\n") else "|-"
            lines.append("%s: %s" % (key, indicator))
            body = value[:-1] if value.endswith("\n") else value
            for part in body.split("\n"):
                lines.append(("  " + part) if part else "")
            continue
        lines.append("%s: %s" % (key, dump_scalar(value)))
    return "".join(line + newline for line in lines)


def render_page(fm, body, newline="\n"):
    """Join frontmatter and body. An empty mapping returns the body as is."""
    if not fm:
        return body
    return "---" + newline + dump_frontmatter(fm, newline) + "---" + newline + body


def validate_page_frontmatter(fm):
    """Check page fields from contract 3. Returns a list of error strings."""
    errors = []
    for key in PAGE_REQUIRED_FIELDS:
        if not fm.get(key):
            errors.append("missing %s" % key)
    for key in PAGE_SCALAR_FIELDS:
        if key in fm and fm[key] is not None and not isinstance(fm[key], str):
            errors.append("%s must be a scalar" % key)
    for key in PAGE_LIST_FIELDS:
        if key in fm and fm[key] is not None and not isinstance(fm[key], list):
            errors.append("%s must be a list" % key)
    if fm.get("type") and fm.get("type") not in PAGE_TYPES:
        errors.append("type must be one of %s" % ", ".join(PAGE_TYPES))
    if fm.get("domain") and fm.get("domain") not in DOMAINS:
        errors.append("domain must be work or personal")
    if fm.get("scope") is not None:
        if fm.get("type") != "pref":
            errors.append("scope is only valid on pref pages")
        elif fm.get("scope") not in PREF_SCOPES:
            errors.append("scope must be one of %s" % ", ".join(PREF_SCOPES))
    for key in ("decided", "supersedes"):
        if fm.get(key) and fm.get("type") != "decision":
            errors.append("%s is only valid on decision pages" % key)
    for key in PAGE_DATE_FIELDS:
        value = fm.get(key)
        if isinstance(value, str) and value and not DATETIME_RE.match(value):
            errors.append("%s must be YYYY-MM-DD" % key)
    return errors


# ---------------------------------------------------------------------------
# Section helpers (D1, D10)
# ---------------------------------------------------------------------------

SRC_COMMENT_RE = re.compile(r"<!--\s*src:\s*(\S+)\s+@(\d{4}-\d{2}-\d{2})\s*-->")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def fence_step(fence, line):
    """Fenced-code tracking for one line (CommonMark rules), shared by every
    code-aware scan. fence is the open fence's marker ('```', '~~~~', ...)
    or None. Returns (fence_after, is_fence_line). A closing fence uses the
    opening character, is at least as long and has nothing after it, so a
    ``` line inside a ```` block is code (fix round 1); a backtick opener's
    info string holds no backtick."""
    match = _FENCE_RE.match(line.rstrip("\r\n"))
    if not match:
        return fence, False
    marker, rest = match.group(1), match.group(2)
    if fence is None:
        if marker[0] == "`" and "`" in rest:
            return None, False
        return marker, True
    if marker[0] == fence[0] and len(marker) >= len(fence) and not rest.strip():
        return None, True
    return fence, False


def format_src(source_id, date):
    """Section provenance marker: <!-- src: <id> @<date> -->."""
    if not is_valid_source_id(source_id):
        raise ValueError("invalid source id %r" % (source_id,))
    if not DATE_RE.match(date or ""):
        raise ValueError("invalid source date %r" % (date,))
    return "<!-- src: %s @%s -->" % (source_id, date)


def split_my_notes(body, heading=MY_NOTES_HEADING):
    """Split a page body at '## 내 메모' (outside code fences).

    Returns (before, notes) where notes runs from the heading line to the end
    of the file, byte-for-byte. notes is "" when the heading is missing.
    """
    offset = 0
    fence = None
    for line in body.splitlines(True):
        fence, is_fence = fence_step(fence, line)
        if not is_fence and fence is None and line.rstrip("\r\n").rstrip() == heading:
            return body[:offset], body[offset:]
        offset += len(line)
    return body, ""


def _structural_heading(stripped):
    """'## <x>' or '### <domain>': a line that ends or starts a root notes
    subsection when it is outside code."""
    if stripped.startswith("## ") and not stripped.startswith("### "):
        return True
    return stripped in ["### " + domain for domain in DOMAINS]


def my_notes_ambiguous(notes):
    """True when the subsections of a '## 내 메모' tail cannot be told apart
    safely (fix round 2): its fences do not balance, or a '## ' or
    '### <domain>' line sits inside a fence. Either way a fence opened in
    one domain's subsection may run into the next one (an unclosed ``` in
    '### personal' swallowing '### work'), or a '### <domain>' line in code
    may really be a heading after a fence left open: no reading is safe."""
    fence = None
    for line in notes.splitlines(True):
        before = fence
        fence, is_fence = fence_step(fence, line)
        if before is not None and not is_fence and _structural_heading(
                line.rstrip("\r\n").rstrip()):
            return True
    return fence is not None


def my_notes_subsection(notes, domain):
    """Text of '### <domain>' inside a '## 내 메모' tail (root now/about-me).

    Root pages keep one subsection per domain so a batch only ever sees its
    own domain's notes. Text directly under '## 내 메모' is never staged.
    Fenced code is tracked (fix round 1), and when that tracking leaves the
    subsection borders in doubt (my_notes_ambiguous: fences that do not
    balance, or a '## '/'### <domain>' line inside a fence) every domain
    gets "" (fix round 2): no domain's notes reach another domain's batch.
    """
    if my_notes_ambiguous(notes):
        return ""
    wanted = "### " + domain
    out = []
    inside = False
    fence = None
    for line in notes.splitlines(True):
        before = fence
        fence, is_fence = fence_step(fence, line)
        if is_fence or before is not None:
            if inside:
                out.append(line)
            continue
        stripped = line.rstrip("\r\n").rstrip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            if inside:
                break
            continue
        if stripped.startswith("### "):
            inside = stripped == wanted
            continue
        if inside:
            out.append(line)
    return "".join(out)


# ---------------------------------------------------------------------------
# Config loaders (contract 3, panel D-9)
# ---------------------------------------------------------------------------

DOMAINS_KEYS = ("owners", "work_terms", "overrides", "redact_allow", "obsidian_plugins_allow")
MAX_SOURCES_PER_BATCH = 30

SETTINGS_DEFAULTS = collections.OrderedDict([
    ("model", "sonnet"),
    ("max_budget_usd", 2.0),
    ("claude_path", ""),
    ("batch_max_sources", MAX_SOURCES_PER_BATCH),
    ("notify", collections.OrderedDict([
        ("slack_channel", ""),
        ("token_cmd", []),
    ])),
    ("schedule", collections.OrderedDict([
        ("label_user", ""),
        ("interval_seconds", 1800),
        ("min_hours_between_runs", 20),
    ])),
])

_PLACEHOLDER_RE = re.compile(r"<[^<>]+>")


def load_json_file(path, missing_reason="config_missing"):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (IOError, OSError) as exc:
        if getattr(exc, "errno", None) == errno.ENOENT:
            raise ConfigError(missing_reason, "%s does not exist" % path)
        raise ConfigError("config_unreadable", "%s: %s" % (path, exc))
    try:
        return json.loads(text, object_pairs_hook=collections.OrderedDict)
    except ValueError as exc:
        raise ConfigError("config_invalid_json", "%s: %s" % (path, exc))


def _is_str_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_domains(data, where="domains.json"):
    """Validate domains.json. Keys starting with '_' are free-form comments."""
    if not isinstance(data, dict):
        raise ConfigError("domains_invalid", "%s must be a JSON object" % where)
    for key in data:
        if key not in DOMAINS_KEYS and not key.startswith("_"):
            raise ConfigError("domains_invalid", "%s: unknown key %r" % (where, key))
    out = collections.OrderedDict()
    owners = data.get("owners", {})
    if not isinstance(owners, dict):
        raise ConfigError("domains_invalid", "%s: owners must be an object" % where)
    seen = {}
    for owner, domain in owners.items():
        if domain not in DOMAINS:
            raise ConfigError("domains_invalid",
                              "%s: owners[%r] must be work or personal" % (where, owner))
        folded = owner.strip().lower()
        if not folded:
            raise ConfigError("domains_invalid", "%s: empty owner" % where)
        if folded in seen and seen[folded] != domain:
            raise ConfigError("domains_invalid",
                              "%s: owner %r maps to both domains" % (where, owner))
        seen[folded] = domain
    out["owners"] = collections.OrderedDict(owners)
    overrides = data.get("overrides", {})
    if not isinstance(overrides, dict):
        raise ConfigError("domains_invalid", "%s: overrides must be an object" % where)
    for source_id, domain in overrides.items():
        if domain not in DOMAINS:
            raise ConfigError("domains_invalid",
                              "%s: overrides[%r] must be work or personal" % (where, source_id))
    out["overrides"] = collections.OrderedDict(overrides)
    for key in ("work_terms", "redact_allow", "obsidian_plugins_allow"):
        value = data.get(key, [])
        if not _is_str_list(value):
            raise ConfigError("domains_invalid", "%s: %s must be a list of strings" % (where, key))
        out[key] = list(value)
    return out


def load_domains(root):
    path = os.path.join(root, "domains.json")
    return validate_domains(load_json_file(path, "domains_missing"), path)


def domains_placeholders(domains):
    """Entries still holding <placeholder> text from the template."""
    found = []
    for owner in domains.get("owners", {}):
        if _PLACEHOLDER_RE.search(owner):
            found.append("owners:" + owner)
    for term in domains.get("work_terms", []):
        if _PLACEHOLDER_RE.search(term):
            found.append("work_terms:" + term)
    for source_id in domains.get("overrides", {}):
        if _PLACEHOLDER_RE.search(source_id):
            found.append("overrides:" + source_id)
    for value in domains.get("redact_allow", []):
        if _PLACEHOLDER_RE.search(value):
            found.append("redact_allow:" + value)
    return found


def _has_work_content(root):
    """True when work content can enter without a work owner: a file in
    inbox/work/ or a page under work/ (.gitkeep does not count)."""
    for base, suffix in ((os.path.join(root, INBOX_DIRNAME, "work"), None),
                         (os.path.join(root, "work"), ".md")):
        for _dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.startswith("."):
                    continue
                if suffix is None or name.endswith(suffix):
                    return True
    return False


def domains_guard(domains, root=None):
    """Reason code when domains.json is not safe to absorb with, else None.

    With work content possible (a work owner, an override to work, a work
    inbox note or a work page), an empty or placeholder work_terms list
    silently switches off D5 quarantine, the personal-page check and the
    cache filter, so absorb refuses to run (panel review). Placeholder
    owners mean the template was never filled in.
    """
    owners = domains.get("owners") or {}
    if any(_PLACEHOLDER_RE.search(owner) for owner in owners):
        return "owners_unset"
    terms = [term for term in domains.get("work_terms") or [] if term.strip()]
    if any(_PLACEHOLDER_RE.search(term) for term in terms):
        return "work_terms_unset"
    if terms:
        return None
    if "work" in owners.values() or "work" in (domains.get("overrides") or {}).values():
        return "work_terms_unset"
    if root is not None and _has_work_content(root):
        return "work_terms_unset"
    return None


def _check_number(value, name, minimum=None, integer=False):
    ok = isinstance(value, int) if integer else isinstance(value, (int, float))
    if isinstance(value, bool) or not ok:
        raise ConfigError("settings_invalid", "settings.json: %s must be a number" % name)
    if minimum is not None and value < minimum:
        raise ConfigError("settings_invalid", "settings.json: %s must be >= %s" % (name, minimum))


def validate_settings(data):
    """Merge settings.json over SETTINGS_DEFAULTS and type-check known keys.

    Unknown keys are kept so later tickets can add settings. settings.json
    holds no secrets: Slack tokens come from notify.token_cmd at send time.
    """
    if not isinstance(data, dict):
        raise ConfigError("settings_invalid", "settings.json must be a JSON object")
    merged = json.loads(json.dumps(SETTINGS_DEFAULTS), object_pairs_hook=collections.OrderedDict)
    for key, value in data.items():
        if key in ("notify", "schedule"):
            if not isinstance(value, dict):
                raise ConfigError("settings_invalid", "settings.json: %s must be an object" % key)
            merged[key].update(value)
        else:
            merged[key] = value
    for key in ("model", "claude_path"):
        if not isinstance(merged[key], str):
            raise ConfigError("settings_invalid", "settings.json: %s must be a string" % key)
    if not merged["model"]:
        raise ConfigError("settings_invalid", "settings.json: model must not be empty")
    if merged["claude_path"] and not os.path.isabs(merged["claude_path"]):
        raise ConfigError("settings_invalid", "settings.json: claude_path must be absolute")
    _check_number(merged["max_budget_usd"], "max_budget_usd", 0)
    if merged["max_budget_usd"] <= 0:
        raise ConfigError("settings_invalid", "settings.json: max_budget_usd must be > 0")
    _check_number(merged["batch_max_sources"], "batch_max_sources", 1, integer=True)
    if merged["batch_max_sources"] > MAX_SOURCES_PER_BATCH:
        raise ConfigError("settings_invalid",
                          "settings.json: batch_max_sources must be <= %d" % MAX_SOURCES_PER_BATCH)
    if not isinstance(merged["notify"].get("slack_channel"), str):
        raise ConfigError("settings_invalid", "settings.json: notify.slack_channel must be a string")
    if not _is_str_list(merged["notify"].get("token_cmd")):
        raise ConfigError("settings_invalid",
                          "settings.json: notify.token_cmd must be an argv list of strings")
    if not isinstance(merged["schedule"].get("label_user"), str):
        raise ConfigError("settings_invalid", "settings.json: schedule.label_user must be a string")
    _check_number(merged["schedule"].get("interval_seconds"), "schedule.interval_seconds", 60,
                  integer=True)
    _check_number(merged["schedule"].get("min_hours_between_runs"),
                  "schedule.min_hours_between_runs", 0)
    return merged


def load_settings(root):
    """settings.json is optional; defaults apply when it is missing."""
    path = os.path.join(root, "settings.json")
    if not os.path.exists(path):
        return validate_settings({})
    return validate_settings(load_json_file(path))


def dumps_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Git remotes (D2, contract 2 step 3, contract 5)
# ---------------------------------------------------------------------------

RemoteInfo = collections.namedtuple("RemoteInfo", "host owner repo")

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$")


def parse_remote_url(url):
    """Normalize a git remote URL to RemoteInfo(host, owner, repo), lowercased.

    Handles https/http/git/ssh URLs, scp-like 'user@host:Org/repo' and ssh
    host aliases such as 'github-work:Org/repo'; strips credentials, ports,
    '.git' and trailing '/'. Following git, a URL without a scheme is
    scp-like only when ':' appears before any '/'; otherwise it is a local
    path and the result is None. The owner is the first path segment.
    """
    if not isinstance(url, str):
        return None
    text = url.strip()
    if not text:
        return None
    match = _SCHEME_RE.match(text)
    if match:
        scheme = match.group(1).lower()
        if scheme == "file":
            return None
        hostpart, _sep, path = match.group(2).partition("/")
        hostpart = hostpart.rpartition("@")[2]
        if hostpart.startswith("["):
            host = hostpart.split("]", 1)[0] + "]"
        else:
            host = hostpart.split(":", 1)[0]
    else:
        colon = text.find(":")
        slash = text.find("/")
        if colon <= 0 or (0 <= slash < colon):
            return None
        hostpart, path = text[:colon], text[colon + 1:]
        host = hostpart.rpartition("@")[2]
        if len(host) == 1 and path[:1] in ("/", "\\"):
            return None  # Windows drive letter
    path = path.strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if not host or len(segments) < 2:
        return None
    owner = segments[0]
    if owner.startswith("~"):
        owner = owner[1:]
    if not owner:
        return None
    return RemoteInfo(host.lower(), owner.lower(), segments[-1].lower())


def parse_remote_v(output):
    """URLs from `git remote -v` output, both (fetch) and (push), in order."""
    urls = []
    for line in (output or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] not in urls:
            urls.append(parts[1])
    return urls


def domain_for_remotes(urls, owners):
    """Decide a repo's domain from all of its remote URLs.

    - any remote whose owner maps to work -> "work"
    - every remote parses and maps to personal -> "personal"
    - otherwise (no remotes, unparseable/local remote, unlisted owner) -> None

    None means "undetermined": hooks print nothing and absorb skips the
    source. A repo mixing a personal owner with an unlisted one stays
    undetermined until the unlisted owner is added to domains.json owners.
    """
    folded = dict((key.strip().lower(), value) for key, value in (owners or {}).items())
    if not urls:
        return None
    decided = []
    for url in urls:
        info = parse_remote_url(url)
        domain = folded.get(info.owner) if info else None
        if domain == "work":
            return "work"
        decided.append(domain)
    if decided and all(domain == "personal" for domain in decided):
        return "personal"
    return None


_HOME_PATTERNS = {}


def home_dir(environ=None):
    environ = os.environ if environ is None else environ
    return environ.get("HOME") or os.path.expanduser("~")


def _home_patterns(home):
    """Regexes for the home folder in text: the absolute path (and its
    realpath) and Claude Code's encoded folder form, where every
    non-alphanumeric character becomes '-' (a slash or dot of the path
    turns into '-').
    Each must end on a name boundary, so a home named acme never matches
    inside a sibling folder named acmecorp."""
    if home in _HOME_PATTERNS:
        return _HOME_PATTERNS[home]
    patterns = []
    clean = (home or "").rstrip("/")
    if len(clean) > 1:
        spellings = set([clean])
        try:
            spellings.add(os.path.realpath(clean).rstrip("/"))
        except (OSError, ValueError):
            pass
        encoded = set(re.sub(r"[^A-Za-z0-9]", "-", item) for item in spellings)
        for item in sorted(spellings, key=len, reverse=True):
            patterns.append(re.compile(re.escape(item) + r"(?![A-Za-z0-9_.-])", re.IGNORECASE))
        for item in sorted(encoded, key=len, reverse=True):
            patterns.append(re.compile(re.escape(item) + r"(?![A-Za-z0-9_.])", re.IGNORECASE))
    _HOME_PATTERNS[home] = patterns
    return patterns


def strip_home(text, home=None):
    """text with the user's home folder replaced by '~' (fix round 1).

    Every work_terms match runs on this, in prepare and verify alike: the
    home folder's name is the account name, which may be the employer's
    word, and matching it would send every no-remote memory folder and
    prompt under home to work, and quarantine any personal text that
    quotes a home path. The rest of the path still counts."""
    if not text:
        return text
    if home is None:
        home = home_dir()
    for pattern in _home_patterns(home):
        text = pattern.sub("~", text)
    return text


def git_remote_urls(cwd, timeout=1.0):
    """Run `git -C <cwd> remote -v` (the only git call hooks may make).

    Returns a list of URLs, or None on any error or timeout.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "remote", "-v"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    return parse_remote_v(proc.stdout.decode("utf-8", "replace"))


def undeterminable_cwd(cwd, home=None):
    """Path-only guards (no git): '/', the home folder itself and Traycer
    epic folders are undeterminable (D2), even if the home folder happens
    to be a dotfiles repo with a remote. v1 does not resolve an epic folder
    to its workspace repo (contract 5 allows no git call other than
    remote -v)."""
    real = os.path.realpath(cwd)
    if home and real == os.path.realpath(home):
        return True
    if real == os.path.sep:
        return True
    marker = os.sep + os.path.join(".traycer", "epics") + os.sep
    return marker in real + os.sep


def repo_domain(cwd, owners, timeout=1.0):
    urls = git_remote_urls(cwd, timeout=timeout)
    if urls is None:
        return None
    return domain_for_remotes(urls, owners)


# ---------------------------------------------------------------------------
# Git calls on the wiki repository itself
# ---------------------------------------------------------------------------

WIKI_GIT_NAME = "wiki"
WIKI_GIT_EMAIL = "wiki@localhost"


def wiki_git(cwd, args, check=True, timeout=60, env=None):
    """Run git on the wiki repo with the user's hooks and signing disabled.

    core.hooksPath=/dev/null keeps the user's global hooks (including
    post-commit, which --no-verify does not skip) away from wiki commits.
    An identity is supplied only when user.email is unset.
    """
    base = ["git", "-C", cwd, "-c", "core.hooksPath=/dev/null",
            "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    # No optional locks: `status` (run by `wiki status` while a background
    # absorb commits in main) must never take .git/index.lock for its
    # opportunistic index refresh.
    env = dict(os.environ if env is None else env)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        if args and args[0] == "commit":
            probe = subprocess.run(["git", "-C", cwd, "config", "user.email"],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   stdin=subprocess.DEVNULL, env=env, timeout=timeout)
            if not probe.stdout.strip():
                base += ["-c", "user.name=" + WIKI_GIT_NAME, "-c", "user.email=" + WIKI_GIT_EMAIL]
        proc = subprocess.run(base + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, env=env, timeout=timeout)
    except OSError as exc:
        raise WikiError("git_missing", "cannot run git: %s" % exc)
    except subprocess.TimeoutExpired:
        raise WikiError("git_timeout", "git %s timed out" % " ".join(args[:2]))
    if check and proc.returncode != 0:
        raise WikiError("git_failed", "git %s: %s" % (
            " ".join(args[:2]), proc.stderr.decode("utf-8", "replace").strip()))
    return proc


# ---------------------------------------------------------------------------
# run.json (contract 1, panel D-2/D-3)
# ---------------------------------------------------------------------------

SOURCE_OPS = ("new", "changed", "deleted")
RUN_TOP_KEYS = ("run_id", "base_sha", "worktree", "batches", "quarantined", "unresolved")
SOURCE_KEYS = ("id", "domain", "op", "date", "redacted_path", "diff_path")
_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*:\S+$")
_RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{4}(\d{2})?(-\d+)?$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

# Deviations from the plan text, recorded in every run.json (panel request).
# One "<code>:<short text>" per bullet of SKILL.md "계획과 달라진 점"; each
# bullet ends with the same `dev:<code>` tag (tests/test_repo_hygiene.py).
PLAN_DEVIATIONS = (
    "claude_p_flags:restricted,acceptEdits,permission_prompts_none,"
    "no_session_persistence,output_format_json,json_schema; prompt on stdin",
    "allowed_globs:<domain>/** only (index.md,log.md,now.md,about-me.md,settings.json,"
    "domains.json written by verify)",
    "llm_cwd:.absorb-wt/<domain>",
    "now_about_me:<domain>/_drafts fragments assembled by verify; root 내 메모 split into "
    "### work/### personal, a batch sees its domain's part only",
    "settings:settings.json for non-domain settings",
    "state_relpaths:staging and run.json paths relative to .state/",
    "llm_env:+CLAUDE_CODE_DISABLE_AUTO_MEMORY=1,CLAUDE_CODE_DISABLE_CLAUDE_MDS=1,"
    "CLAUDE_CONFIG_DIR passthrough; PATH claude folder+system",
    "add_dir_staging_only:--add-dir gets staging/<batch> only (the worktree is the cwd)",
    "json_schema_mentions:--json-schema result adds mentions; pages realpath'ed",
    "prompt_template:templates/absorb_prompt.md shipped with the .bin copy",
    "promotions:names with >=3 sources listed in the next prompt; Python syncs aliases",
    "drafts_store:merged fragments kept in .state/drafts/<domain>/",
    "worktree_commits:one worktree commit per batch; .absorb-wt removed after the run",
    "schedule_ledger:.state/absorb-ledger.json counts every finished run (failed, held too)",
    "notify_failures:reason codes in the ledger, not log.md (log.md is merged from the worktree)",
    "notify_config:optional gitignored notify.json before settings.json notify",
    "scheduled_silent_skip:scheduled run exits 0 silently when not due, lock busy or no wiki",
    "schedule_print:schedule print added",
    "plist_extras:ProcessType=Background, CLAUDE_CONFIG_DIR and WIKI_RULES_PATH when set",
    "epic_home_undeterminable:home folder and Traycer epic folders undeterminable in v1 "
    "(hooks, prepare, query)",
    "batch_deferral:a batch touching a human-edited file is deferred whole, not per file",
    "manual_closed:merged manual:<page> sources kept as status closed so pages can cite them",
    "notes_source:notes:<domain>/<page> source for root 내 메모 subsections",
    "generated_restore:human edits to index.md/log.md backed up to .state/backups and restored",
    "manual_secret_scan:human edits scanned before the prepare commit; a file with a hit is "
    "held, never committed (secret_found_manual:<n> warning), the run goes on",
    "domains_guard:absorb refuses empty/placeholder work_terms or owners (work_terms_unset, "
    "owners_unset); also with a work override, a work inbox note or a work page",
    "session_output_codes:absorb prints codes and counts only; full report in "
    ".state/last-report.json",
    "staging_cleanup:staging/ emptied after every run",
    "handoff_expiry:Python drops 현재 상태 items (or the whole section) resting only on "
    "handoff srcs older than 14 days; a src-only block and deeper-indented children go with "
    "the item before them",
    "bare_wikilinks:bare [[name]] rejected when the other domain has that file name",
    "traycer_repo_fallback:repoIdentifiers fallback only for epics without a workspace path",
    "token_cmd_lookup:token_cmd program also looked up in ~/.local/bin, /opt/homebrew/bin, "
    "/usr/local/bin",
    "pending_scope:context-cache pending written only by absorb; unresolved/quarantined count "
    "changed sources only",
    "manual_unscanned_held:human edits that cannot be scanned (not UTF-8, symlink) are held, "
    "never committed",
    "personal_path_terms:personal page paths are work_terms-checked; such pages are left out of "
    "index, links and query, and their manual edits quarantined",
    "label_default:launchd label user defaults to local, never $USER",
    "absorb_running_marker:.state/absorb-running.json while absorb runs; status shows it",
    "redact_path_rules:contract-4 file-path exception made concrete: path-like segments only, "
    "src-comment source ids the caller knows (sources.json, this run), existing page file "
    "names and Claude Code project folders after projects/; short parts rechecked together "
    "first (words cut out only when their letter pairs read like English, the macOS temp "
    "folder cut out, known ids included; an id that is itself a hit keeps its source out of "
    "batches, source_id_secret:<n>); no bare-slug exemption; redact_allow also matches a "
    "containing or contained entry",
    "root_assembly_guard:a draft with an open code fence fails its batch "
    "(draft_unbalanced_fence); a root file that cannot be reassembled safely is left as it is "
    "(root_file_skipped:<name>), never a failed run",
    "user_rules_guard:personal batches refuse to run while the user rules folder (symlinked "
    "folders followed) holds .md files other than the wiki rules file, recognised by shape, "
    "by the sha256 absorb recorded when it wrote it (.state/rules-written.json) and by no "
    "work_terms hit (user_rules_unisolated); kept after the 2.1.318 measurement as "
    "belt-and-braces",
    "home_terms:work_terms are matched after the home folder (absolute and Claude Code "
    "encoded form) is replaced by ~",
    "query_domain_conflict:query --domain cannot name the other domain in a decided cwd "
    "(domain_conflict)",
    "schedule_install_guard:schedule install refuses domains.json placeholders "
    "(owners_unset, work_terms_unset)",
    "root_untracked_notes:untracked .md files outside the domain folders are counted "
    "(root_untracked_notes:<n>), never absorbed",
    "scan_existing_hits:the pre-merge whole-tree scan blocks only on files new or changed since "
    "base_sha; unchanged hits are counted (secret_found_existing:<n>)",
)


def is_valid_source_id(source_id):
    return (isinstance(source_id, str) and bool(_SOURCE_ID_RE.match(source_id))
            and "-->" not in source_id)


def make_run_id(now=None):
    now = now or datetime.datetime.now()
    return now.strftime("%Y-%m-%dT%H%M")


def allowed_globs_for(domain):
    """LLM write scope for a batch: its domain folder only (panel D-2/D-3)."""
    if domain not in DOMAINS:
        raise ValueError("unknown domain %r" % (domain,))
    return ["%s/**" % domain]


def new_run(run_id, base_sha, worktree):
    run = collections.OrderedDict()
    run["schema_version"] = SCHEMA_VERSION
    run["run_id"] = run_id
    run["base_sha"] = base_sha
    run["worktree"] = worktree
    run["batches"] = []
    run["quarantined"] = 0
    run["unresolved"] = 0
    run["deviations"] = list(PLAN_DEVIATIONS)
    return run


def make_source(source_id, domain, op, date, redacted_path, diff_path=None):
    source = collections.OrderedDict()
    source["id"] = source_id
    source["domain"] = domain
    source["op"] = op
    source["date"] = date
    source["redacted_path"] = redacted_path
    source["diff_path"] = diff_path
    return source


def batch_domain(sources):
    domains = set(source.get("domain") for source in sources)
    if len(domains) != 1:
        raise ValueError("a batch must hold exactly one domain, got %s"
                         % sorted(str(domain) for domain in domains))
    domain = domains.pop()
    if domain not in DOMAINS:
        raise ValueError("unknown domain %r" % (domain,))
    return domain


def make_batch(batch_id, sources):
    """Build a batch; allowed_globs is derived from the sources' one domain."""
    if not sources:
        raise ValueError("a batch needs at least one source")
    if len(sources) > MAX_SOURCES_PER_BATCH:
        raise ValueError("a batch holds at most %d sources" % MAX_SOURCES_PER_BATCH)
    batch = collections.OrderedDict()
    batch["batch_id"] = batch_id
    batch["sources"] = list(sources)
    batch["allowed_globs"] = allowed_globs_for(batch_domain(sources))
    return batch


def _valid_state_relpath(path):
    parts = _normalize_relpath(path)
    return parts is not None and len(parts) >= 2 and parts[0] == "staging"


def validate_run(run):
    """Return a list of contract-1 violations (empty when valid)."""
    if not isinstance(run, dict):
        return ["run.json must be an object"]
    errors = ["missing %s" % key for key in RUN_TOP_KEYS if key not in run]
    if errors:
        return errors
    if not isinstance(run["run_id"], str) or not _RUN_ID_RE.match(run["run_id"]):
        errors.append("run_id must look like YYYY-MM-DDTHHMM")
    if not isinstance(run["base_sha"], str) or not _SHA_RE.match(run["base_sha"]):
        errors.append("base_sha must be a full commit sha")
    if not isinstance(run["worktree"], str) or not run["worktree"]:
        errors.append("worktree must be a path")
    for key in ("quarantined", "unresolved"):
        value = run[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append("%s must be a non-negative integer" % key)
    if not isinstance(run["batches"], list):
        return errors + ["batches must be a list"]
    seen_batches = set()
    for index, batch in enumerate(run["batches"]):
        where = "batches[%d]" % index
        if not isinstance(batch, dict):
            errors.append("%s must be an object" % where)
            continue
        batch_id = batch.get("batch_id")
        if isinstance(batch_id, bool) or not isinstance(batch_id, int) or batch_id < 1:
            errors.append("%s.batch_id must be a positive integer" % where)
        elif batch_id in seen_batches:
            errors.append("%s.batch_id %d is duplicated" % (where, batch_id))
        else:
            seen_batches.add(batch_id)
        sources = batch.get("sources")
        if not isinstance(sources, list) or not sources:
            errors.append("%s.sources must be a non-empty list" % where)
            continue
        if len(sources) > MAX_SOURCES_PER_BATCH:
            errors.append("%s holds more than %d sources" % (where, MAX_SOURCES_PER_BATCH))
        for s_index, source in enumerate(sources):
            s_where = "%s.sources[%d]" % (where, s_index)
            if not isinstance(source, dict):
                errors.append("%s must be an object" % s_where)
                continue
            if not is_valid_source_id(source.get("id")):
                errors.append("%s.id must look like kind:rest without spaces" % s_where)
            if source.get("domain") not in DOMAINS:
                errors.append("%s.domain must be work or personal" % s_where)
            op = source.get("op")
            if op not in SOURCE_OPS:
                errors.append("%s.op must be one of %s" % (s_where, "|".join(SOURCE_OPS)))
            date = source.get("date")
            if not isinstance(date, str) or not DATE_RE.match(date):
                errors.append("%s.date must be YYYY-MM-DD" % s_where)
            redacted = source.get("redacted_path")
            if redacted is None:
                if op != "deleted":
                    errors.append("%s.redacted_path is required unless op is deleted" % s_where)
            elif not _valid_state_relpath(redacted):
                errors.append("%s.redacted_path must be a staging/ relative path" % s_where)
            diff = source.get("diff_path")
            if diff is not None and not _valid_state_relpath(diff):
                errors.append("%s.diff_path must be a staging/ relative path" % s_where)
        try:
            domain = batch_domain([s for s in sources if isinstance(s, dict)])
        except ValueError as exc:
            errors.append("%s: %s" % (where, exc))
            continue
        if batch.get("allowed_globs") != allowed_globs_for(domain):
            errors.append("%s.allowed_globs must be %s" % (where, allowed_globs_for(domain)))
    return errors


def write_run(root, run):
    errors = validate_run(run)
    if errors:
        raise WikiError("run_json_invalid", "; ".join(errors))
    ensure_private_dir(state_dir(root))
    atomic_write_text(run_json_path(root), dumps_json(run), mode=0o600)


def read_run(root):
    run = load_json_file(run_json_path(root), "run_json_missing")
    errors = validate_run(run)
    if errors:
        raise WikiError("run_json_invalid", "; ".join(errors))
    return run


def _normalize_relpath(path):
    if (not isinstance(path, str) or not path or path.startswith("/")
            or "\\" in path or "\0" in path):
        return None
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return parts


def _segment_regex(segment):
    pieces = []
    for ch in segment:
        if ch == "*":
            pieces.append("[^/]*")
        elif ch == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(ch))
    return re.compile("^" + "".join(pieces) + "$", re.DOTALL)


def _match_segments(parts, pattern):
    if not pattern:
        return not parts
    head = pattern[0]
    if head == "**":
        return any(_match_segments(parts[i:], pattern[1:]) for i in range(len(parts) + 1))
    if not parts or not _segment_regex(head).match(parts[0]):
        return False
    return _match_segments(parts[1:], pattern[1:])


def glob_match(path, pattern):
    """Case-sensitive, segment-wise glob: '*' never crosses '/', '**' spans
    zero or more segments, and 'personal/**' matches files below personal/
    only (not 'personal-x/a', 'Personal/a', or the folder itself).

    Callers must pass repository-relative paths taken from `git ... -z`
    output; without -z git octal-quotes non-ASCII (Korean) names.
    """
    parts = _normalize_relpath(path)
    pattern_parts = _normalize_relpath(pattern)
    if parts is None or pattern_parts is None:
        return False
    if pattern_parts[-1] == "**" and len(parts) < len(pattern_parts):
        return False
    return _match_segments(parts, pattern_parts)


def path_allowed(path, globs):
    return any(glob_match(path, pattern) for pattern in globs)


# ---------------------------------------------------------------------------
# Lock (D6)
# ---------------------------------------------------------------------------

class WikiLock(object):
    """Exclusive, non-blocking fcntl.flock on .state/absorb.lock.

    The file is opened without truncation and the pid is written only after
    the lock is held, so a losing contender never clobbers the holder's pid.
    """

    def __init__(self, path):
        self.path = path
        self.fd = None

    def acquire(self, blocking=False):
        import fcntl

        parent = os.path.dirname(self.path)
        if parent and not os.path.isdir(parent):
            ensure_private_dir(parent)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except (IOError, OSError) as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise LockBusy()
            raise
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, ("%d\n" % os.getpid()).encode("ascii"))
        self.fd = fd
        return self

    def release(self):
        if self.fd is None:
            return
        import fcntl

        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        if self.fd is None:
            self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def wiki_lock(root):
    return WikiLock(lock_path(root))
