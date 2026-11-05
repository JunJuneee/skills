"""UserPromptSubmit hook: point at wiki pages whose names appear in the prompt.

    /usr/bin/python3 prompt_nudge.py --event UserPromptSubmit

Reads hook JSON on stdin, .state/context-cache.json (owners only) and
.state/alias-cache.json under WIKI_ROOT (default ~/wiki), plus
`git -C <cwd> remote -v`. Only the session domain's aliases are matched, so
another domain's names in the prompt never surface a path (D13).

Matching (D13), after NFKC normalization and casefold of both sides:
  - names of 2 characters or fewer are ignored;
  - a name containing Hangul matches as a substring (particles may follow);
  - a Latin name matches on word boundaries (letters, digits and '_' around
    it break the match; Hangul and punctuation do not);
  - other scripts match as a substring.
At most 3 pages, in order of first appearance. Always exits 0.
"""

import re
import sys

import common
import hooklib

EVENTS = ("UserPromptSubmit",)
MAX_NUDGES = 3
MIN_NAME_LENGTH = 3
MAX_PROMPT_CHARS = 20000
MAX_NAMES = 5000

_HANGUL_RE = re.compile(u"[ᄀ-ᇿ㄰-㆏ꥠ-꥿가-힯ힰ-퟿]")
_LATIN_RE = re.compile(u"[0-9a-zÀ-ɏ]")
_WORD = u"0-9a-z_À-ɏ"


def compile_name(name):
    """(normalized name, matcher) or None when the name is too short."""
    if not isinstance(name, str):
        return None
    norm = hooklib.normalize(" ".join(name.split()))
    if len(norm) < MIN_NAME_LENGTH:
        return None
    if _HANGUL_RE.search(norm) or not _LATIN_RE.search(norm):
        return norm, None
    pattern = re.compile(u"(?<![%s])%s(?![%s])" % (_WORD, re.escape(norm), _WORD))
    return norm, pattern


def find_position(prompt_norm, compiled):
    norm, pattern = compiled
    if pattern is None:
        return prompt_norm.find(norm)
    match = pattern.search(prompt_norm)
    return match.start() if match else -1


def match_pages(prompt, entries, domain, limit=MAX_NUDGES):
    """[(page, title)] for alias-cache entries of domain named in prompt."""
    prompt_norm = hooklib.normalize(prompt[:MAX_PROMPT_CHARS])
    hits = {}
    titles = {}
    budget = MAX_NAMES
    for entry in entries:
        if budget <= 0:
            break
        if not isinstance(entry, dict):
            continue
        page = entry.get("page")
        if not hooklib.valid_page(page, domain):
            continue
        title = hooklib.one_line(entry.get("title"))
        aliases = entry.get("aliases")
        names = [entry.get("title")] + (aliases if isinstance(aliases, list) else [])
        for name in names[:budget]:
            budget -= 1
            compiled = compile_name(name)
            if compiled is None:
                continue
            position = find_position(prompt_norm, compiled)
            if position >= 0 and (page not in hits or position < hits[page]):
                hits[page] = position
                titles[page] = title or hooklib.one_line(name)
    ordered = sorted(hits, key=lambda page: (hits[page], page))
    return [(page, titles[page]) for page in ordered[:limit]]


def build_nudge(event, payload, environ, root=None):
    """The additionalContext text, or None (stay silent)."""
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    root = common.resolve_root(root, environ)
    resolved = hooklib.resolve_session(payload, environ, root)
    if resolved is None:
        return None
    domain = resolved[0]
    alias_cache = hooklib.load_cache(root, hooklib.ALIAS_CACHE)
    if alias_cache is None:
        return None
    entries = hooklib.domain_block(alias_cache, domain)
    if not isinstance(entries, list):
        return None
    matches = match_pages(prompt, entries, domain)
    if not matches:
        return None
    lines = []
    for page, title in matches:
        line = u"관련 위키: " + hooklib.display_path(root, page, environ)
        if title:
            line += u" (%s)" % hooklib.cap(title, 80)
        lines.append(line)
    return "\n".join(lines)


def build(event, payload, environ):
    text = build_nudge(event, payload, environ)
    if not text:
        return None
    return hooklib.hook_output(event, text)


def main(argv=None, environ=None, stdin=None):
    return hooklib.run_hook(build, sys.argv[1:] if argv is None else argv, EVENTS,
                            environ=environ, stdin=stdin)


if __name__ == "__main__":
    sys.exit(main())
