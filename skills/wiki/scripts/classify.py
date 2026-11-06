"""Per-prompt domain classification for prompts whose folder gives no domain.

The prepare step asks this module about prompts typed in the home folder, a
folder without a remote, and so on. work_terms are checked before it gets
here, so what arrives has no work term.

A session decides more than one prompt can: most of these prompts are follow-ups
("다음 단계 진행해") that say nothing alone. So one work signal in a session sends
all of it to work, before any LLM call. That direction is safe: work text never
reaches a public-repo session. personal is the risky answer and needs the whole
session answered with no work signal.

The LLM runs with every tool off and sees redacted prompts as JSON lines. A
prompt too long to show whole is not asked about, because an answer about part
of it would be applied to all of it. Answers land in .state/prompt-classes.json
keyed by a hash, so the file holds no prompt text and a prompt is asked about
once. A failed call never fails absorb: those prompts stay unresolved and are
asked about next run.
"""

import hashlib
import json
import os
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common  # noqa: E402
import redact  # noqa: E402
import verify  # noqa: E402

CLASSES_FILE = "prompt-classes.json"
CWD_NAME = "classify-cwd"
TEMPLATE = "classify_prompt.md"
UNKNOWN = "unknown"
VALID = frozenset(common.DOMAINS) | {UNKNOWN}
MIN_CHARS = 6        # shorter than this says nothing ("ㄱㄱ", "응")
MAX_CHARS = 500      # longer prompts are never asked about (stored as unknown)
CHUNK = 100
MAX_PER_RUN = 600    # newest first; the rest waits for the next run
SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "domain": {"type": "string", "enum": sorted(VALID)}},
        "required": ["id", "domain"]}}},
    "required": ["items"],
}


def classes_path(root):
    return os.path.join(common.state_dir(root), CLASSES_FILE)


def prompt_key(record):
    """Stable id of one prompt; the same one prompt dedup in prepare uses."""
    raw = "\0".join((record["date"], record["time"], record["text"]))
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:24]


def load_classes(root):
    """{key: {"c": class, "d": date}}; an unreadable file counts as empty."""
    path = classes_path(root)
    if not os.path.isfile(path):
        return {}
    try:
        data = common.load_json_file(path)
    except (common.WikiError, IOError, OSError, ValueError):
        return {}
    classes = data.get("classes") if isinstance(data, dict) else None
    if not isinstance(classes, dict):
        return {}
    return {key: value for key, value in classes.items()
            if isinstance(value, dict) and value.get("c") in VALID}


def save_classes(root, classes, since_date=None):
    """Atomic 0600 write. Entries older than since_date are out of the prompt
    window, so they are dropped."""
    kept = {key: value for key, value in classes.items()
            if not since_date or str(value.get("d") or "") >= since_date}
    common.ensure_private_dir(common.state_dir(root))
    common.atomic_write_text(classes_path(root),
                             common.dumps_json({"version": 1, "classes": kept}), mode=0o600)


def _is_short(record):
    return len("".join(record["text"].split())) < MIN_CHARS


def _too_long(record, allow):
    return len(redact.redact(record["text"], allow).text) > MAX_CHARS


def _spread(undecided, classes, work_sessions):
    """A duplicated prompt joins two sessions, so work has to travel across
    such joins until nothing changes. A human's personal or unknown stops it."""
    changed = True
    while changed:
        changed = False
        for entry in undecided:
            value = classes.get(prompt_key(entry["record"])) or {}
            if (value.get("by") != "human" or value.get("c") == "work") and (
                    entry["sessions"] & work_sessions and entry["sessions"] - work_sessions):
                work_sessions |= entry["sessions"]
                changed = True


def resolve_sessions(entries, classes, classifier=None):
    """Final domains for prompt entries, a list of dicts with record, domain
    (from folder and work_terms, or None) and sessions. Sets entry["domain"]
    and entry["via"] on the ones that had no domain. Returns classes.

    A human's answer (wiki prompts set) beats everything for that prompt, and
    a human's work counts as a work signal too. Any work signal in a session
    makes the whole session work; short prompts stay out because they would
    only be noise in a digest."""
    work_sessions = set()
    for entry in entries:
        if entry["domain"] == "work":
            work_sessions |= entry["sessions"]
    undecided = [entry for entry in entries if entry["domain"] is None]
    _spread(undecided, classes, work_sessions)
    if classifier is not None:
        pending = [entry["record"] for entry in undecided
                   if prompt_key(entry["record"]) not in classes
                   and not entry["sessions"] & work_sessions]
        if pending:
            classes = classifier(pending)
    for entry in undecided:
        if (classes.get(prompt_key(entry["record"])) or {}).get("c") == "work":
            work_sessions |= entry["sessions"]
    _spread(undecided, classes, work_sessions)
    waiting = set()
    for entry in undecided:
        if prompt_key(entry["record"]) not in classes and not entry["sessions"] & work_sessions:
            waiting |= entry["sessions"]
    for entry in undecided:
        value = classes.get(prompt_key(entry["record"])) or {}
        answer = value.get("c")
        if value.get("by") == "human":
            domain, via = (answer if answer in common.DOMAINS else None), "human"
        elif answer == "work":
            domain, via = "work", "llm"
        elif entry["sessions"] & work_sessions and not _is_short(entry["record"]):
            domain, via = "work", "session"
        elif answer == "personal" and not entry["sessions"] & waiting:
            domain, via = "personal", "llm"
        else:
            domain, via = None, "llm" if answer else "pending"
        entry["domain"], entry["via"] = domain, via
    return classes


def project_names(root, allow=()):
    """{domain: [project titles and aliases]}: the LLM's only hint about what
    belongs where. Pages may hold an edit prepare refused to commit, so a name
    that looks like a secret is left out."""
    names = {}
    for domain in common.DOMAINS:
        found = []
        for page in verify.live_pages(root, domain):
            if page.fm.get("type") == "project":
                found += [page.title] + list(page.aliases)
        names[domain] = sorted(name for name in set(found) if not redact.scan(name, allow))
    return names


def render_prompt(template, names, lines):
    return (template
            .replace("{{WORK_PROJECTS}}", json.dumps(names.get("work") or [], ensure_ascii=False))
            .replace("{{PERSONAL_PROJECTS}}",
                     json.dumps(names.get("personal") or [], ensure_ascii=False))
            .replace("{{PROMPTS}}", "\n".join(lines)))


def _prompt_line(item_id, text, allow):
    return json.dumps({"id": item_id, "text": redact.redact(text, allow).text},
                      ensure_ascii=False)


def _answers(items, ids):
    """{id: domain} from a structured answer. An id answered twice proves
    nothing about either answer, so it stays unanswered."""
    seen = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("id") in ids and item.get("domain") in VALID:
            seen.setdefault(item["id"], []).append(item["domain"])
    return {key: found[0] for key, found in seen.items() if len(found) == 1}


def classify(root, pending, classes, domains_cfg, runner_factory, template, warnings,
             since_date=None, stats=None):
    """Ask about `pending` prompt records. Returns classes with the answers
    added, saved after every chunk so a later failure keeps earlier answers.

    runner_factory() returns a callable taking the absorb request dict; it is
    only called when something needs the LLM."""
    allow = domains_cfg.get("redact_allow", [])
    classes = dict(classes)
    stats = {} if stats is None else stats
    asked = []
    skipped = 0
    for record in pending:
        if _is_short(record) or _too_long(record, allow):
            classes[prompt_key(record)] = {"c": UNKNOWN, "d": record["date"]}
            skipped += 1
        else:
            asked.append(record)
    asked.sort(key=lambda r: r["ts"], reverse=True)
    deferred = max(0, len(asked) - MAX_PER_RUN)
    asked = asked[:MAX_PER_RUN]
    if skipped:
        save_classes(root, classes, since_date)
    if deferred:
        warnings.append("prompt_classify_deferred:%d" % deferred)
    if not asked:
        return classes
    try:
        runner = runner_factory()
    except common.WikiError as exc:
        warnings.append("prompt_classify_failed:%s" % exc.reason)
        return classes
    names = project_names(root, allow)
    cwd = os.path.join(common.state_dir(root), CWD_NAME)
    common.ensure_private_dir(cwd)
    for name in VALID:
        stats.setdefault(name, 0)
    stats.setdefault("cost_usd", 0.0)
    for start in range(0, len(asked), CHUNK):
        chunk = asked[start:start + CHUNK]
        ids = {"p%d" % index: record for index, record in enumerate(chunk)}
        lines = [_prompt_line(item_id, record["text"], allow) for item_id, record in ids.items()]
        result = runner({"prompt": render_prompt(template, names, lines), "schema": SCHEMA,
                         "cwd": cwd, "staging_dir": cwd, "tools_off": True})
        if isinstance(result.get("cost"), (int, float)):
            stats["cost_usd"] = round(stats["cost_usd"] + result["cost"], 4)
        if not result.get("ok"):
            warnings.append("prompt_classify_failed:%s" % (result.get("reason") or "llm_error"))
            break
        # An id with no usable answer is not stored: it is asked again next run.
        answers = _answers((result.get("structured") or {}).get("items"), ids)
        for item_id, domain in answers.items():
            record = ids[item_id]
            classes[prompt_key(record)] = {"c": domain, "d": record["date"]}
            stats[domain] += 1
        save_classes(root, classes, since_date)
    return classes


def set_human(root, key, domain, date, since_date=None):
    """Store a human's answer; resolve_sessions lets nothing override it."""
    if domain not in VALID:
        raise common.WikiError("bad_class", "class must be work, personal or unknown")
    classes = load_classes(root)
    classes[key] = {"c": domain, "d": date, "by": "human"}
    save_classes(root, classes, since_date)
