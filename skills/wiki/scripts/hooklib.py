"""Shared helpers for the session hooks (session_context.py, prompt_nudge.py).

Hook rules (contract 5, D2, D11, D13, panel D-4/D-5):
  - Read only .state/context-cache.json and .state/alias-cache.json. Never
    domains.json, wiki pages or anything else (owners come from the cache).
  - The only git call is `git -C <cwd> remote -v` (common.git_remote_urls,
    1 s timeout).
  - Print nothing unless every check passes: LLM_WIKI_HOOK is not 0, a
    positive Claude Code signal is present, the cwd domain is decided and
    the caches are valid. Callers build the whole JSON in memory and print
    it once at the end; any exception means no output and exit 0.

Cache formats are documented in references/caches.md.
"""

import json
import os
import re
import sys
import unicodedata

import common

CACHE_VERSION = 1
CONTEXT_CACHE = "context-cache.json"
ALIAS_CACHE = "alias-cache.json"
MAX_STDIN_BYTES = 1024 * 1024
MAX_CACHE_BYTES = 2 * 1024 * 1024
GIT_TIMEOUT = 1.0

_CONTROL_RE = re.compile(u"[\u0000-\u0008\u000b-\u001f\u007f  ]")
_PAGE_SEGMENT_RE = re.compile(r"^[^/\\\x00]+$")


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def read_stdin_json(stream=None):
    """Hook input as a dict, or None (TTY, too large, not JSON, not object)."""
    stream = sys.stdin if stream is None else stream
    try:
        if stream.isatty():
            return None
    except (AttributeError, ValueError, OSError):
        pass
    raw = getattr(stream, "buffer", stream).read(MAX_STDIN_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    if not raw or len(raw) > MAX_STDIN_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def hook_disabled(environ):
    return (environ.get("LLM_WIKI_HOOK") or "").strip() == "0"


def _within(path, directory):
    try:
        path = os.path.realpath(path)
        directory = os.path.realpath(directory)
        return os.path.commonpath([path, directory]) == directory and path != directory
    except (ValueError, TypeError, OSError):
        return False


def claude_config_dir(environ):
    value = environ.get("CLAUDE_CONFIG_DIR") or ""
    if value:
        return os.path.expanduser(value)
    home = environ.get("HOME") or ""
    if not home:
        return None
    return os.path.join(home, ".claude")


def is_claude_session(payload, environ):
    """Positive Claude Code signal (panel D-4), measured on 2.1.318.

    Both must hold:
      - CLAUDECODE=1 in the hook environment (Claude Code sets it for hook
        processes even when started from an empty environment);
      - stdin transcript_path lies inside the Claude config directory
        (CLAUDE_CONFIG_DIR, else ~/.claude). Codex also loads plugin
        hooks.json (it sets CLAUDE_PLUGIN_ROOT), but its transcripts live
        elsewhere, and a Codex started from a Claude shell inherits
        CLAUDECODE=1, so the env var alone is not enough.
    """
    if (environ.get("CLAUDECODE") or "") != "1":
        return False
    transcript = payload.get("transcript_path") if isinstance(payload, dict) else None
    if not isinstance(transcript, str) or not os.path.isabs(transcript):
        return False
    config_dir = claude_config_dir(environ)
    return bool(config_dir) and _within(transcript, config_dir)


def event_matches(payload, event):
    name = payload.get("hook_event_name")
    return name is None or name == event


def payload_cwd(payload):
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and os.path.isabs(cwd):
        return cwd
    return None


def undeterminable_cwd(cwd, environ):
    """Path-only guards (no git): home folder itself and Traycer epic folders.

    D2: sessions in the home folder or an epic folder get nothing, even if
    the home folder happens to be a dotfiles repo with a remote. v1 does not
    resolve an epic folder to its workspace repo (contract 5 allows no git
    call other than remote -v). Shared with prepare and `wiki query`.
    """
    return common.undeterminable_cwd(cwd, environ.get("HOME") or "")


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

def load_cache(root, name):
    """A validated cache dict, or None. Never raises."""
    path = os.path.join(root, common.STATE_DIRNAME, name)
    try:
        if os.path.getsize(path) > MAX_CACHE_BYTES:
            return None
        with open(path, "rb") as handle:
            data = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None
    if not isinstance(data.get("domains"), dict):
        return None
    return data


def cache_owners(context_cache):
    owners = context_cache.get("owners") if isinstance(context_cache, dict) else None
    if not isinstance(owners, dict) or not owners:
        return None
    clean = {}
    for owner, domain in owners.items():
        if isinstance(owner, str) and owner.strip() and domain in common.DOMAINS:
            clean[owner] = domain
    return clean or None


def valid_page(page, domain):
    """A cache page path must stay inside its own domain folder."""
    if not isinstance(page, str) or not page.endswith(".md"):
        return False
    parts = page.split("/")
    if len(parts) < 2 or parts[0] != domain:
        return False
    for part in parts:
        if part in ("", ".", "..") or not _PAGE_SEGMENT_RE.match(part):
            return False
    return True


def domain_block(cache, domain):
    block = cache.get("domains", {}).get(domain)
    return block if isinstance(block, (dict, list)) else None


# ---------------------------------------------------------------------------
# Domain of the session cwd
# ---------------------------------------------------------------------------

def cwd_remotes(cwd):
    """(owner/repo keys, urls) for cwd, or (None, None) when git fails."""
    urls = common.git_remote_urls(cwd, timeout=GIT_TIMEOUT)
    if urls is None:
        return None, None
    keys = []
    for url in urls:
        info = common.parse_remote_url(url)
        if info:
            key = "%s/%s" % (info.owner, info.repo)
            if key not in keys:
                keys.append(key)
    return keys, urls


def resolve_session(payload, environ, root):
    """(domain, repo_keys, context_cache) or None when the hook stays silent."""
    if hook_disabled(environ) or not is_claude_session(payload, environ):
        return None
    cwd = payload_cwd(payload)
    if cwd is None or undeterminable_cwd(cwd, environ):
        return None
    if not os.path.isdir(root):
        return None
    context_cache = load_cache(root, CONTEXT_CACHE)
    owners = cache_owners(context_cache)
    if owners is None:
        return None
    keys, urls = cwd_remotes(cwd)
    if urls is None:
        return None
    domain = common.domain_for_remotes(urls, owners)
    if domain not in common.DOMAINS:
        return None
    return domain, keys, context_cache


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def normalize(text):
    """NFKC + casefold, used for alias matching and repo keys."""
    return unicodedata.normalize("NFKC", text).casefold()


def clean_text(value):
    """Cache strings as safe text (NFC, no control characters)."""
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", text).strip()


def one_line(value):
    return " ".join(clean_text(value).split())


def cap(text, limit):
    """Cut text to at most limit characters, marking the cut with '…'."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return u"…"
    return text[:limit - 1].rstrip() + u"…"


def display_path(root, page, environ):
    path = os.path.join(root, *page.split("/"))
    home = environ.get("HOME") or ""
    if home:
        home_real = os.path.realpath(home)
        if _within(path, home_real):
            return "~/" + os.path.relpath(os.path.realpath(path), home_real).replace(os.sep, "/")
    return path


def hook_output(event, text):
    """The single JSON document a hook prints (ASCII-safe for any locale)."""
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": text,
    }}, ensure_ascii=True)


def write_stdout(document):
    data = (document + "\n").encode("ascii")
    out = getattr(sys.stdout, "buffer", None)
    if out is not None:
        out.write(data)
        out.flush()
    else:
        sys.stdout.write(document + "\n")
        sys.stdout.flush()


def parse_event_arg(argv, allowed):
    """--event <E> from argv; None unless E is one of allowed."""
    args = list(argv)
    for index, arg in enumerate(args):
        if arg == "--event" and index + 1 < len(args):
            value = args[index + 1]
            return value if value in allowed else None
        if arg.startswith("--event="):
            value = arg.split("=", 1)[1]
            return value if value in allowed else None
    return None


def run_hook(build, argv, allowed, environ=None, stdin=None):
    """Shared main(): never raises, prints at most one JSON document.

    build(event, payload, environ) returns the full JSON text or None; it
    runs to completion before anything is written, so a failure part-way
    leaves stdout empty.
    """
    try:
        environ = os.environ if environ is None else environ
        event = parse_event_arg(argv, allowed)
        if event is None or hook_disabled(environ):
            return 0
        payload = read_stdin_json(stdin)
        if payload is None or not event_matches(payload, event):
            return 0
        document = build(event, payload, environ)
        if document:
            write_stdout(document)
    except BaseException:  # hooks must never fail or slow the session
        return 0
    return 0
