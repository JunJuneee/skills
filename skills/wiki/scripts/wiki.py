#!/usr/bin/env python3
"""wiki: personal context wiki CLI (Python 3.9, stdlib only).

Usage:
  wiki.py [--root DIR] [--json] init
  wiki.py absorb [--scheduled] [--rules-path FILE] [--no-notify] [--verbose]
  wiki.py note --domain work|personal TEXT
  wiki.py query [--domain work|personal] [--limit N] TEXT
  wiki.py status
  wiki.py schedule install|uninstall|print [--no-load] [--claude PATH] [--rules-path FILE]
  wiki.py schedule --install|--uninstall|--print ...

The root is --root, else $WIKI_ROOT, else ~/wiki. `init` creates the layout
and a local git repository only; it never touches ~/.claude or launchd.
`schedule install` is the only command that touches launchd (opt-in).
"""

import argparse
import collections
import datetime
import errno
import json
import os
import sys
import time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import common  # noqa: E402

SKILL_DIR = os.path.dirname(SCRIPTS_DIR)


def templates_dir():
    """templates/ next to the scripts (flat .bin/<ver>/ copy) or in the skill."""
    for candidate in (os.path.join(SCRIPTS_DIR, "templates"), os.path.join(SKILL_DIR, "templates")):
        if os.path.isdir(candidate):
            return candidate
    raise common.WikiError("templates_missing", "templates/ not found next to %s" % SCRIPTS_DIR)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

# (path in the wiki, template path or None for generated content)
INIT_FILES = (
    ("SCHEMA.md", "SCHEMA.md"),
    ("domains.json", "domains.example.json"),
    ("settings.json", None),
    ("index.md", os.path.join("root", "index.md")),
    ("log.md", os.path.join("root", "log.md")),
    ("now.md", os.path.join("root", "now.md")),
    ("about-me.md", os.path.join("root", "about-me.md")),
)


def _read_template(name):
    with open(os.path.join(templates_dir(), name), "r", encoding="utf-8") as handle:
        return handle.read()


def _gitignore_lines():
    return [line for line in _read_template("wiki-gitignore.txt").splitlines()]


def _check_root_allowed(root, environ):
    home = os.path.realpath(environ.get("HOME") or os.path.expanduser("~"))
    if root in ("/", home):
        raise common.WikiError("root_not_allowed", "refusing to use %s as the wiki root" % root)
    if os.path.exists(root) and not os.path.isdir(root):
        raise common.WikiError("root_not_directory", "%s exists and is not a directory" % root)
    if os.path.isdir(root) and not common.is_initialized(root):
        entries = [name for name in os.listdir(root) if name not in (".DS_Store",)]
        if entries:
            raise common.WikiError(
                "root_not_empty",
                "%s is not empty and is not a wiki; choose another WIKI_ROOT" % root)


def init_wiki(root, environ=None, now=None):
    """Create the wiki layout. Idempotent: never overwrites existing files.

    Returns a summary dict with created paths and the commit sha (if any).
    """
    environ = os.environ if environ is None else environ
    now = now or datetime.datetime.now()
    _check_root_allowed(root, environ)
    created = []

    if not os.path.isdir(root):
        os.makedirs(root, 0o700)
        created.append(".")
    # work/ pages and the root now.md/about-me.md (both domains' fragments)
    # must not be readable by other local accounts: closing the root is
    # enough, since nothing below it can be reached without it.
    os.chmod(root, 0o700)

    # .state/ first, with the marker, so an interrupted init can be resumed.
    state = common.state_dir(root)
    existed = os.path.isdir(state)
    common.ensure_private_dir(state)
    if not existed:
        created.append(common.STATE_DIRNAME + "/")
    marker = os.path.join(state, common.STATE_MARKER)
    if not os.path.exists(marker):
        info = {"schema_version": common.SCHEMA_VERSION,
                "created": now.strftime("%Y-%m-%dT%H:%M:%S")}
        common.atomic_write_text(marker, common.dumps_json(info), mode=0o600)
    for name in common.STATE_SUBDIRS:
        path = os.path.join(state, name)
        if not os.path.isdir(path):
            created.append("%s/%s/" % (common.STATE_DIRNAME, name))
        common.ensure_private_dir(path)

    tracked = []
    managed = [rel for rel, _template in INIT_FILES] + [".gitignore"]
    for domain, subdirs in common.DOMAIN_SUBDIRS.items():
        for sub in subdirs:
            rel = "%s/%s" % (domain, sub)
            path = os.path.join(root, domain, sub)
            if not os.path.isdir(path):
                os.makedirs(path, 0o755)
                created.append(rel + "/")
            keep = os.path.join(path, ".gitkeep")
            managed.append(rel + "/.gitkeep")
            if not os.path.exists(keep):
                open(keep, "w").close()
                tracked.append(rel + "/.gitkeep")

    for domain in common.DOMAINS:
        path = os.path.join(root, common.INBOX_DIRNAME, domain)
        if not os.path.isdir(path):
            os.makedirs(path, 0o700)
            created.append("%s/%s/" % (common.INBOX_DIRNAME, domain))
        os.chmod(os.path.join(root, common.INBOX_DIRNAME), 0o700)
        os.chmod(path, 0o700)

    for rel, template in INIT_FILES:
        path = os.path.join(root, rel)
        if os.path.exists(path):
            continue
        if template is None:
            content = common.dumps_json(common.SETTINGS_DEFAULTS)
        else:
            content = _read_template(template)
        common.atomic_write_text(path, content, mode=0o644)
        created.append(rel)
        tracked.append(rel)

    gitignore = os.path.join(root, ".gitignore")
    wanted = _gitignore_lines()
    if os.path.exists(gitignore):
        with open(gitignore, "r", encoding="utf-8") as handle:
            current = handle.read()
        have = set(line.strip() for line in current.splitlines())
        missing = [line for line in wanted if line.strip() and not line.startswith("#")
                   and line.strip() not in have]
        if missing:
            text = current if current.endswith("\n") or not current else current + "\n"
            common.atomic_write_text(gitignore, text + "\n".join(missing) + "\n", mode=0o644)
            tracked.append(".gitignore")
    else:
        common.atomic_write_text(gitignore, "\n".join(wanted) + "\n", mode=0o644)
        created.append(".gitignore")
        tracked.append(".gitignore")

    if not os.path.isdir(os.path.join(root, ".git")):
        common.wiki_git(root, ["init", "-q"])
        common.wiki_git(root, ["symbolic-ref", "HEAD", "refs/heads/main"])
        created.append(".git/")

    def head_sha():
        head = common.wiki_git(root, ["rev-parse", "--verify", "-q", "HEAD"], check=False)
        return head.stdout.decode("ascii", "replace").strip() if head.returncode == 0 else None

    if head_sha() is None:
        # No commit yet (first run, an interrupted run, or .git was recreated):
        # commit every init-managed file that exists, not only new ones.
        tracked = [rel for rel in managed if os.path.exists(os.path.join(root, rel))]
    if tracked:
        common.wiki_git(root, ["add", "--"] + sorted(set(tracked)))
        staged = common.wiki_git(root, ["diff", "--cached", "--quiet"], check=False)
        if staged.returncode == 1:
            common.wiki_git(root, ["commit", "-q", "--no-verify", "-m", "wiki: init"])
    sha = head_sha()
    if sha is None:
        raise common.WikiError("git_commit_failed", "the wiki repository has no commit")

    placeholders = common.domains_placeholders(common.load_domains(root))
    return {
        "ok": True,
        "root": root,
        "created": created,
        "head": sha,
        "domains_placeholders": placeholders,
    }


def cmd_init(args, environ):
    root = common.resolve_root(args.root, environ)
    summary = init_wiki(root, environ)
    if args.json:
        sys.stdout.write(common.dumps_json(summary))
    else:
        if summary["created"]:
            print("wiki init: %s (%d개 생성)" % (root, len(summary["created"])))
        else:
            print("wiki init: %s (이미 초기화됨, 바뀐 것 없음)" % root)
        if summary["domains_placeholders"]:
            print("domains.json에 아직 플레이스홀더가 있습니다: %d개. owners와 work_terms를 채우세요."
                  % len(summary["domains_placeholders"]))
    return EXIT_OK


def _require_wiki(root):
    if not common.is_initialized(root) or not os.path.isdir(os.path.join(root, ".git")):
        raise common.WikiError("not_initialized", "%s is not a wiki; run wiki init" % root)


def cmd_absorb(args, environ):
    import schedule  # the ledger, the 20-hour rule and the Slack line

    root = common.resolve_root(args.root, environ)
    rules_path = os.path.abspath(os.path.expanduser(args.rules_path)) if args.rules_path else None
    report = schedule.run_absorb(root, environ, scheduled=args.scheduled, rules_path=rules_path,
                                 send=not args.no_notify)
    if report is None:
        # Scheduled tick that is not due (20-hour rule), lock busy or no
        # wiki: silent, so launchd.log does not grow 48 lines a day.
        if args.json:
            sys.stdout.write(common.dumps_json({"ok": True, "skipped": True}))
        return EXIT_OK
    import absorb

    # The full report (page paths, source ids) stays in .state; the session
    # (possibly a public-repo or shared one) gets codes and counts only.
    report_path = absorb.write_report_file(root, report)
    if args.verbose:
        shown = report
    else:
        shown = absorb.public_report(report, report_path)
    if args.json:
        sys.stdout.write(common.dumps_json(shown))
    else:
        line = report.get("summary_line") or ""
        if args.scheduled:
            line = "%s %s" % (datetime.datetime.now().astimezone().replace(
                microsecond=0).isoformat(), line)
        print(line)
        if args.verbose:
            for warning in report.get("warnings") or []:
                sys.stderr.write("경고: %s\n" % warning)
        else:
            for code, count in absorb.warning_codes(report.get("warnings")).items():
                sys.stderr.write("경고: %s%s\n" % (code, " ×%d" % count if count > 1 else ""))
            if report_path and (report.get("warnings") or not report.get("ok")):
                sys.stderr.write("자세한 결과: %s\n" % report_path)
        sent = report.get("notify") or {}
        if sent.get("mode") == "slack" and not sent.get("sent"):
            sys.stderr.write("알림 실패: %s\n" % sent.get("reason"))
    return EXIT_OK if report.get("ok") else EXIT_ERROR


def cmd_prompts(args, environ):
    """Prompts whose folder gives no domain: list them with what decided
    them, correct one, or classify without running absorb. Prints prompt text,
    so it is for the user's own terminal."""
    import absorb
    import classify
    import prepare
    import redact

    root = common.resolve_root(args.root, environ)
    if args.action == "classify":
        ask = absorb.prompt_classifier(environ)
        with common.wiki_lock(root):
            _entries, _since, warnings = prepare.prompt_entries(root, environ,
                                                                prompt_classifier=ask)
        print(common.dumps_json(ask.stats).strip())
        for warning in warnings:
            sys.stderr.write("경고: %s\n" % warning)
        return EXIT_OK
    entries, since_date, _warnings = prepare.prompt_entries(root, environ)
    entries = [entry for entry in entries if entry["via"] != "folder"]
    wanted = args.key if args.action == "list" else None
    if wanted and wanted not in classify.VALID:
        sys.stderr.write("사용법: wiki prompts list [work|personal|unknown]\n")
        return EXIT_ERROR
    if args.action == "list":
        # A personal (public-repo) session holds zero work text, and unknown
        # may be work: the same rule as query.
        owners = common.load_domains(root).get("owners") or {}
        home = environ.get("HOME") or os.path.expanduser("~")
        cwd = os.getcwd()
        cwd_domain = None if common.undeterminable_cwd(cwd, home) else common.repo_domain(cwd, owners)
        if cwd_domain == "personal":
            if wanted and wanted != "personal":
                raise common.WikiError("domain_conflict",
                                       "이 폴더는 personal 도메인입니다. work와 unknown은 회사 레포나 "
                                       "판정되지 않는 폴더에서 보세요")
            wanted = "personal"
    if args.action == "set":
        if not args.key or args.key_class not in classify.VALID:
            sys.stderr.write("사용법: wiki prompts set <key> work|personal|unknown\n")
            return EXIT_ERROR
        found = [e for e in entries if classify.prompt_key(e["record"]).startswith(args.key)]
        if len(found) != 1:
            sys.stderr.write("key가 프롬프트 하나를 가리키지 않습니다 (%d건)\n" % len(found))
            return EXIT_ERROR
        record = found[0]["record"]
        with common.wiki_lock(root):
            classify.set_human(root, classify.prompt_key(record), args.key_class, record["date"],
                               since_date)
        print("%s → %s. 다음 absorb에 반영됩니다." % (classify.prompt_key(record)[:10], args.key_class))
        return EXIT_OK
    allow = common.load_domains(root).get("redact_allow", [])
    for entry in entries:
        shown = entry["domain"] or "unknown"
        if wanted and shown != wanted:
            continue
        record = entry["record"]
        text = redact.redact(record["text"], allow).text
        print("%s %s %-8s %-7s %s" % (classify.prompt_key(record)[:10], record["date"], shown,
                                      entry["via"], " ".join(text.split())[:100]))
    return EXIT_OK


NOTE_MAX_CHARS = 20000


def write_note(root, domain, text, now=None):
    """A new inbox/<domain>/<timestamp>.md (0600, never overwrites)."""
    _require_wiki(root)
    if domain not in common.DOMAINS:
        raise common.WikiError("domain_invalid", "domain must be work or personal")
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        raise common.WikiError("note_empty", "the note is empty")
    if len(text) > NOTE_MAX_CHARS:
        raise common.WikiError("note_too_long", "a note is at most %d characters" % NOTE_MAX_CHARS)
    now = now or datetime.datetime.now()
    inbox = os.path.join(root, common.INBOX_DIRNAME)
    base = os.path.join(inbox, domain)
    for path in (inbox, base):
        if not os.path.isdir(path):
            os.makedirs(path, 0o700)
        os.chmod(path, 0o700)
    content = "# 메모 %s\n\n%s\n" % (now.strftime("%Y-%m-%d %H:%M"), text)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    for attempt in range(1, 1000):
        name = "%s.md" % stamp if attempt == 1 else "%s-%d.md" % (stamp, attempt)
        path = os.path.join(base, name)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                continue
            raise
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        return "%s/%s/%s" % (common.INBOX_DIRNAME, domain, name)
    raise common.WikiError("note_name_taken", "too many notes in the same second")


def cmd_note(args, environ):
    root = common.resolve_root(args.root, environ)
    rel = write_note(root, args.domain, " ".join(args.text))
    if args.json:
        sys.stdout.write(common.dumps_json({"ok": True, "path": rel, "domain": args.domain}))
    else:
        print("wiki note: %s (다음 absorb가 반영)" % rel)
    return EXIT_OK


QUERY_SNIPPETS = 2
QUERY_SNIPPET_CHARS = 160


def query_pages(root, domain, text, limit=10):
    """Pages of one domain whose title, aliases, summary or body contain
    every word of text (NFKC, case-insensitive). Never reads the other
    domain, inbox/ or .state/."""
    import verify

    terms = [verify.fold(word) for word in (text or "").split() if verify.fold(word).strip()]
    if not terms:
        raise common.WikiError("query_empty", "the query is empty")
    work_terms = None
    if domain == "personal":
        try:
            work_terms = verify.Terms(common.load_domains(root).get("work_terms", []))
        except common.WikiError:
            work_terms = None
    results = []
    for page in verify.load_pages(root, domain):
        summary = page.fm.get("summary") if isinstance(page.fm.get("summary"), str) else ""
        if work_terms is not None and work_terms.hits("\n".join([page.path, summary]
                                                                + page.names)):
            # D5: a personal page named after a work term stays out of
            # personal sessions (it may be a public-repo session).
            continue
        names = verify.fold(" ".join(page.names))
        hay = "\n".join([names, verify.fold(summary), verify.fold(page.body)])
        if not all(term in hay for term in terms):
            continue
        score = sum(5 for term in terms if term in names) + sum(hay.count(term) for term in terms)
        snippets = []
        for line in page.body.splitlines():
            stripped = common.SRC_COMMENT_RE.sub("", line).strip()
            if work_terms is not None and work_terms.hits(stripped):
                continue
            if stripped and not stripped.startswith("<!--") and any(
                    term in verify.fold(stripped) for term in terms):
                snippets.append(stripped[:QUERY_SNIPPET_CHARS])
                if len(snippets) >= QUERY_SNIPPETS:
                    break
        item = collections.OrderedDict()
        item["path"] = page.path
        item["title"] = page.title
        item["summary"] = verify.first_text_line(summary) if summary else ""
        item["snippets"] = snippets
        item["score"] = score
        results.append(item)
    results.sort(key=lambda item: (-item["score"], item["path"]))
    return results[:limit]


def cmd_query(args, environ):
    root = common.resolve_root(args.root, environ)
    _require_wiki(root)
    owners = common.load_domains(root).get("owners") or {}
    cwd = os.getcwd()
    home = environ.get("HOME") or os.path.expanduser("~")
    cwd_domain = None
    if not common.undeterminable_cwd(cwd, home):
        cwd_domain = common.repo_domain(cwd, owners)
    domain = args.domain or cwd_domain
    if args.domain and cwd_domain in common.DOMAINS and cwd_domain != args.domain:
        # A decided session of one domain never prints the other's pages
        # (a personal public-repo session must hold zero work text).
        raise common.WikiError("domain_conflict",
                               "이 폴더는 %s 도메인입니다. 다른 도메인은 그 도메인 레포나 "
                               "판정되지 않는 폴더에서 찾으세요" % cwd_domain)
    if domain not in common.DOMAINS:
        raise common.WikiError("domain_unresolved",
                               "이 폴더의 도메인을 판정할 수 없습니다. --domain work|personal로 정하세요")
    results = query_pages(root, domain, " ".join(args.text), args.limit)
    if args.json:
        sys.stdout.write(common.dumps_json({"ok": True, "domain": domain, "results": results}))
        return EXIT_OK
    if not results:
        print("wiki query (%s): 찾은 페이지 없음" % domain)
        return EXIT_OK
    print("wiki query (%s): %d개" % (domain, len(results)))
    for item in results:
        line = "- %s — %s" % (item["path"], item["title"])
        if item["summary"]:
            line += ": " + item["summary"]
        print(line)
        for snippet in item["snippets"]:
            print("    %s" % snippet)
    return EXIT_OK


def status_info(root, environ, now_epoch=None):
    """Counts only (no titles: status may run in any session)."""
    import schedule

    _require_wiki(root)
    now_epoch = time.time() if now_epoch is None else now_epoch
    info = collections.OrderedDict()
    warnings = []
    try:
        settings = common.load_settings(root)
    except common.WikiError as exc:
        warnings.append(exc.reason)
        settings = common.validate_settings({})
    try:
        last = common.load_json_file(os.path.join(common.state_dir(root), "last-absorb"))
    except common.WikiError:
        last = None
    info["last_absorb"] = None
    if isinstance(last, dict):
        info["last_absorb"] = collections.OrderedDict(
            (key, last.get(key)) for key in ("run_id", "finished_at", "status", "reason",
                                             "summary_line"))
    import absorb

    running = absorb.read_running_marker(root)
    info["running"] = (collections.OrderedDict([("started_at", running.get("started_at"))])
                       if running else None)
    runs = schedule.read_ledger(root)["runs"]
    info["last_run"] = runs[-1] if runs else None
    notified = (runs[-1].get("notify") or {}) if runs else {}
    if notified.get("mode") == "slack" and not notified.get("sent"):
        warnings.append("notify_failed:%s" % notified.get("reason"))
        if notified.get("reason") == "token_cmd_missing" and runs[-1].get("scheduled"):
            # The launchd PATH comes from schedule install time.
            warnings.append("hint:schedule_install_again_or_absolute_token_cmd")
    due, why = schedule.due_check(root, settings, now_epoch)
    nxt = schedule.next_due_epoch(root, settings)
    info["scheduled_due"] = due
    info["scheduled_why"] = why
    info["next_due"] = schedule._iso(nxt) if nxt else None
    info["schedule"] = schedule.installed_info(root, environ)
    if info["schedule"].get("bin_stale"):
        warnings.append("bin_stale")
    if info["schedule"].get("installed"):
        try:
            import notify

            if not notify.load_config(root, settings)["enabled"]:
                warnings.append("notify_not_configured")
        except common.WikiError as exc:
            warnings.append(exc.reason)
    try:
        placeholders = common.domains_placeholders(common.load_domains(root))
    except common.WikiError as exc:
        placeholders = []
        warnings.append(exc.reason)
    try:
        if os.stat(root).st_mode & 0o077:
            warnings.append("root_permissions_open")
    except OSError:
        pass
    info["domains_placeholders"] = len(placeholders)
    if placeholders:
        warnings.append("domains_placeholders")
    try:
        import prepare

        counts = prepare.pending_counts(root, environ)
        info["pending"] = collections.OrderedDict(
            (key, counts.get(key, 0)) for key in ("work", "personal", "unresolved", "quarantined"))
    except Exception:
        info["pending"] = None
        warnings.append("pending_unavailable")
    info["warnings"] = warnings
    return info


def cmd_status(args, environ):
    root = common.resolve_root(args.root, environ)
    info = status_info(root, environ)
    if args.json:
        sys.stdout.write(common.dumps_json(dict(info, ok=True)))
        return EXIT_OK
    if info.get("running"):
        print("absorb: 실행 중 (%s 시작). 아래 줄은 이전 실행 결과다" % info["running"]["started_at"])
    last = info["last_absorb"]
    if last:
        print("마지막 absorb: %s · %s" % (last.get("finished_at"), last.get("summary_line")))
    else:
        print("마지막 absorb: 없음")
    run = info.get("last_run")
    if run:
        # The ledger also records runs that ended before last-absorb was
        # written (a crash, a setup failure).
        print("장부의 마지막 실행: %s · %s%s" % (
            run.get("finished_at"), run.get("status"),
            " (%s)" % run["reason"] if run.get("reason") else ""))
    pending = info["pending"]
    if pending:
        print("반영 대기: work %d · personal %d · 판정 불가 %d · 격리 %d" % (
            pending["work"], pending["personal"], pending["unresolved"], pending["quarantined"]))
    sched = info["schedule"]
    if sched.get("installed"):
        print("자동 실행: 설치됨 (%s, 고정 스크립트 %s)" % (sched.get("label"),
                                                    sched.get("bin_version")))
    else:
        print("자동 실행: 설치 안 됨 (wiki schedule install)")
    if sched.get("installed"):
        print("다음 자동 실행: %s" % ("지금" if info["scheduled_due"] else info["next_due"]))
    for warning in info["warnings"]:
        print("경고: %s" % warning)
    return EXIT_OK


def cmd_schedule(args, environ):
    import schedule

    action = args.action or args.flag_action
    if args.action and args.flag_action and args.action != args.flag_action:
        raise common.WikiError("usage", "give one of install, uninstall, print")
    if not action:
        raise common.WikiError("usage", "give one of install, uninstall, print")
    root = common.resolve_root(args.root, environ)
    rules_path = os.path.abspath(os.path.expanduser(args.rules_path)) if args.rules_path else None
    if action == "print":
        info = schedule.print_plist(root, environ, claude=args.claude, rules_path=rules_path)
        if args.json:
            info = dict(info)
            info.pop("plist", None)
            sys.stdout.write(common.dumps_json(dict(info, ok=True)))
        else:
            sys.stdout.write(info["xml"])
            for warning in info["warnings"]:
                sys.stderr.write("경고: %s\n" % warning)
        return EXIT_OK
    if action == "install":
        info = schedule.install(root, environ, claude=args.claude, rules_path=rules_path,
                                no_load=args.no_load)
        info = dict(info)
        info.pop("plist", None)
        if args.json:
            sys.stdout.write(common.dumps_json(dict(info, ok=True)))
        else:
            print("wiki schedule: %s 설치 (%s, 고정 스크립트 %s%s)" % (
                info["label"], info["plist_path"], info["version"],
                ", 로드함" if info["loaded"] else ", 로드 안 함"))
            print("claude: %s" % info["claude_path"])
            for warning in info.get("warnings") or []:
                sys.stderr.write("경고: %s\n" % warning)
        return EXIT_OK
    info = schedule.uninstall(root, environ, no_load=args.no_load)
    if args.json:
        sys.stdout.write(common.dumps_json(dict(info, ok=True)))
    else:
        print("wiki schedule: %s 제거 (%s)" % (
            info["label"], "plist 지움" if info["removed"] else "plist 없음"))
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(prog="wiki", description="personal context wiki")
    parser.add_argument("--root", default=None, help="wiki root (default: $WIKI_ROOT or ~/wiki)")
    parser.add_argument("--json", action="store_true", default=False, help="print a JSON result")
    # The same options after the command (wiki.py init --json). SUPPRESS keeps a
    # value given before the command from being reset by the subparser.
    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("--root", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    opts.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                      help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p_init = sub.add_parser("init", parents=[opts],
                            help="create the wiki layout and local git repo")
    p_init.set_defaults(func=cmd_init)

    p_absorb = sub.add_parser("absorb", parents=[opts], help="run the isolated absorb pipeline")
    p_absorb.add_argument("--scheduled", action="store_true",
                          help="launchd mode: run only if due (20h rule)")
    p_absorb.add_argument("--rules-path", default=None,
                          help="where to write the domain-neutral rules file "
                               "(default: $WIKI_RULES_PATH, else ~/.claude/rules/wiki-prefs.md)")
    p_absorb.add_argument("--no-notify", action="store_true",
                          help="do not send the Slack line (the ledger still records the run)")
    p_absorb.add_argument("--verbose", action="store_true",
                          help="print the full report (page paths, source ids); local "
                               "debugging only, never in a shared or public-repo session")
    p_absorb.set_defaults(func=cmd_absorb)

    p_note = sub.add_parser("note", parents=[opts], help="drop a human note into inbox/<domain>/")
    p_note.add_argument("--domain", required=True, choices=common.DOMAINS)
    p_note.add_argument("text", nargs="+")
    p_note.set_defaults(func=cmd_note)

    p_query = sub.add_parser("query", parents=[opts],
                             help="search the pages of the current repo's domain")
    p_query.add_argument("--domain", default=None, choices=common.DOMAINS,
                         help="search this domain instead of the cwd repo's domain")
    p_query.add_argument("--limit", type=int, default=10)
    p_query.add_argument("text", nargs="+")
    p_query.set_defaults(func=cmd_query)

    p_status = sub.add_parser("status", parents=[opts],
                              help="show last run, pending sources, warnings")
    p_status.set_defaults(func=cmd_status)

    p_prompts = sub.add_parser("prompts", parents=[opts],
                               help="list, correct or classify prompts with no folder domain")
    p_prompts.add_argument("action", nargs="?", default="list", choices=("list", "set", "classify"))
    p_prompts.add_argument("key", nargs="?",
                           help="list: only this class; set: a key (or its start) from the list")
    p_prompts.add_argument("key_class", nargs="?", metavar="class", help="set: the new class")
    p_prompts.set_defaults(func=cmd_prompts)

    p_schedule = sub.add_parser("schedule", parents=[opts],
                                help="install, remove or print the launchd job (opt-in)")
    p_schedule.add_argument("action", nargs="?", choices=("install", "uninstall", "print"))
    for flag in ("install", "uninstall", "print"):
        p_schedule.add_argument("--" + flag, dest="flag_action", action="store_const",
                                const=flag, default=None, help=argparse.SUPPRESS)
    p_schedule.add_argument("--no-load", action="store_true",
                            help="write the plist but do not call launchctl")
    p_schedule.add_argument("--claude", default=None,
                            help="absolute claude to pin (default: probe candidates)")
    p_schedule.add_argument("--rules-path", default=None,
                            help="pass --rules-path to the scheduled absorb")
    p_schedule.set_defaults(func=cmd_schedule)
    return parser


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args, environ)
    except common.WikiError as exc:
        if args.json:
            sys.stdout.write(common.dumps_json({"ok": False, "reason": exc.reason,
                                                "message": str(exc)}))
        else:
            sys.stderr.write("wiki %s: %s (reason: %s)\n" % (args.command, exc, exc.reason))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
