"""SessionStart / SubagentStart hook: inject the session domain's wiki context.

    /usr/bin/python3 session_context.py --event SessionStart|SubagentStart

Reads hook JSON on stdin, .state/context-cache.json under WIKI_ROOT (default
~/wiki) and `git -C <cwd> remote -v`. Prints one JSON document with
hookSpecificOutput.additionalContext, or nothing. Always exits 0.

Sections (D11), each with its own cap; total 6000 chars, 2000 for
SubagentStart:
  1. header: as of, domain
  2. project page(s) whose repos match the cwd remotes: summary, 이번 주
  3. prefs of that domain: scope "domain", and scope "repo" for this repo
  4. titles of the domain's other projects
  5. sources changed since the last absorb (titles for this domain, count
     only for undetermined ones), when the cache carries a pending block
"""

import sys

import common
import hooklib

EVENTS = ("SessionStart", "SubagentStart")

# Per-section caps in characters. Totals stay under the D11 limits even
# after the newlines that join sections.
SECTION_CAPS = {
    "SessionStart": {"total": 6000, "header": 200, "project": 2000, "prefs": 2400,
                     "others": 600, "pending": 600},
    "SubagentStart": {"total": 2000, "header": 150, "project": 700, "prefs": 800,
                      "others": 150, "pending": 150},
}


def _repo_key(value):
    """'owner/repo' (lowercase) from a repos entry such as Org/Repo or
    github.com/Org/Repo.git; None when it has fewer than two segments."""
    if not isinstance(value, str):
        return None
    text = value.strip().strip("/")
    if text.lower().endswith(".git"):
        text = text[:-4]
    parts = [part for part in text.split("/") if part]
    if len(parts) < 2:
        return None
    return ("%s/%s" % (parts[-2], parts[-1])).lower()


def _repo_keys(values):
    if not isinstance(values, list):
        return set()
    return set(key for key in (_repo_key(value) for value in values) if key)


def _entries(block, key, domain):
    """Valid dict entries of block[key] whose page stays inside domain."""
    items = block.get(key) if isinstance(block, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if isinstance(item, dict) and hooklib.valid_page(item.get("page"), domain):
            out.append(item)
    return out


def join_capped(lines, limit):
    """Join lines with newlines, stopping (with a cut marker) at limit."""
    out = []
    used = 0
    for line in lines:
        if not line:
            continue
        extra = len(line) + (1 if out else 0)
        if used + extra <= limit:
            out.append(line)
            used += extra
            continue
        room = limit - used - (1 if out else 0)
        if room >= 16:
            out.append(hooklib.cap(line, room))
        break
    return "\n".join(out)


def _header(cache, domain, limit):
    as_of = hooklib.one_line(cache.get("as_of") or cache.get("generated_at") or "")
    head = "wiki as of %s · domain: %s" % (as_of or "?", domain)
    note = " (위키는 읽기만 한다. 쓰기는 /wiki absorb)"
    return hooklib.cap(head + note, limit)


def _project_section(projects, repo_keys, root, environ, limit):
    lines = []
    for project in projects:
        title = hooklib.one_line(project.get("title"))
        if not title:
            continue
        lines.append("%s — %s" % (title, hooklib.display_path(root, project["page"], environ)))
        summary = hooklib.clean_text(project.get("summary"))
        if summary:
            lines.extend(summary.split("\n"))
        this_week = hooklib.one_line(project.get("this_week"))
        if this_week:
            lines.append("이번 주: " + this_week)
    return join_capped(lines, limit)


def _prefs_section(prefs, repo_keys, limit):
    repo_lines = []
    domain_lines = []
    for pref in prefs:
        scope = pref.get("scope")
        text = hooklib.one_line(pref.get("text") or pref.get("summary") or pref.get("title"))
        if not text:
            continue
        if scope == "repo":
            if _repo_keys(pref.get("repos")) & repo_keys:
                repo_lines.append("- " + text)
        elif scope == "domain":
            domain_lines.append("- " + text)
    lines = repo_lines + domain_lines
    if not lines:
        return ""
    return join_capped(["선호:"] + lines, limit)


def _others_section(projects, limit):
    titles = []
    for project in projects:
        title = hooklib.one_line(project.get("title"))
        if title and title not in titles:
            titles.append(title)
    if not titles:
        return ""
    return hooklib.cap("같은 도메인 다른 프로젝트: " + ", ".join(titles), limit)


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _pending_section(cache, domain, limit):
    pending = cache.get("pending")
    if not isinstance(pending, dict):
        return ""
    domains = pending.get("domains") if isinstance(pending.get("domains"), dict) else {}
    mine = domains.get(domain) if isinstance(domains.get(domain), dict) else {}
    titles = [hooklib.one_line(t) for t in mine.get("titles") or [] if isinstance(t, str)]
    titles = [t for t in titles if t]
    count = max(_count(mine.get("count")), len(titles))
    unresolved = _count(pending.get("unresolved"))
    if count + unresolved == 0:
        return ""
    line = "지난 absorb에서 반영되지 못한 원본 %d건 (판정 안 된 것 %d건)" % (
        count + unresolved, unresolved)
    if titles:
        line += ": " + ", ".join(titles)
    return hooklib.cap(line, limit)


def build_context(event, payload, environ, root=None):
    """The additionalContext text for this session, or None (stay silent)."""
    root = common.resolve_root(root, environ)
    resolved = hooklib.resolve_session(payload, environ, root)
    if resolved is None:
        return None
    domain, repo_keys, cache = resolved
    block = hooklib.domain_block(cache, domain)
    if not isinstance(block, dict):
        return None
    caps = SECTION_CAPS[event]
    repo_keys = set(repo_keys or [])
    projects = _entries(block, "projects", domain)
    mine = [p for p in projects if _repo_keys(p.get("repos")) & repo_keys]
    others = [p for p in projects if p not in mine]
    sections = [
        _header(cache, domain, caps["header"]),
        _project_section(mine, repo_keys, root, environ, caps["project"]),
        _prefs_section(_entries(block, "prefs", domain), repo_keys, caps["prefs"]),
        _others_section(others, caps["others"]),
        _pending_section(cache, domain, caps["pending"]),
    ]
    text = "\n".join(section for section in sections if section)
    return hooklib.cap(text, caps["total"])


def build(event, payload, environ):
    text = build_context(event, payload, environ)
    if not text:
        return None
    return hooklib.hook_output(event, text)


def main(argv=None, environ=None, stdin=None):
    return hooklib.run_hook(build, sys.argv[1:] if argv is None else argv, EVENTS,
                            environ=environ, stdin=stdin)


if __name__ == "__main__":
    sys.exit(main())
