"""schedule (T5, D7 + panel D-8): launchd job, pinned scripts, run ledger.
Python 3.9, stdlib only.

  install    copies scripts/*.py and templates/ to WIKI_ROOT/.bin/<ver>/,
             pins an absolute claude that supports every absorb flag in
             settings.json (claude_path), generates the plist with plistlib
             and loads it with launchctl (unless --no-load). Opt-in: nothing
             is installed by init or absorb.
  uninstall  unloads and removes the plist (the .bin copy stays; it is
             gitignored and harmless).
  print      the plist that install would write; writes nothing.

The job: Label io.github.<user>.wiki-absorb (<user> from
settings.schedule.label_user, else the neutral "local"; never $USER, which
can be an employer-issued account name, nor anything else), StartInterval
settings.schedule.interval_seconds (1800), RunAtLoad, ProgramArguments
/usr/bin/python3 WIKI_ROOT/.bin/<ver>/wiki.py --root WIKI_ROOT absorb
--scheduled, EnvironmentVariables HOME, USER, PATH (claude's and token_cmd's
folders plus the system folders), TZ, WIKI_ROOT, LLM_WIKI_HOOK=0, and the
log WIKI_ROOT/.state/launchd.log.

<ver> is "<plugin version>-<first 8 hex of sha256 over the copied files>".
The copy carries BIN.json (version, plugin version, hash) because the plugin
manifest is not reachable from inside .bin.

The 20-hour rule (D7): a scheduled tick runs absorb only when no run is
recorded today (local date) and the last recorded run started at least
settings.schedule.min_hours_between_runs (20) hours ago. Every run that
reaches a result, manual or scheduled, ok/empty/failed/held, is appended to
the ledger .state/absorb-ledger.json, so a failure is retried tomorrow, not
every 30 minutes. A busy lock or a missing wiki is a silent skip.

LaunchAgents and launchctl are injectable (arguments, or WIKI_LAUNCH_AGENTS_DIR
and WIKI_LAUNCHCTL); every path is resolved from the environ passed in.
"""

import collections
import contextlib
import datetime
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import traceback

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import common  # noqa: E402

SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
PLUGIN_DIR = os.path.dirname(os.path.dirname(SKILL_DIR))
PLUGIN_MANIFESTS = (os.path.join(".codex-plugin", "plugin.json"),
                    os.path.join(".claude-plugin", "plugin.json"))

BIN_MANIFEST = "BIN.json"
LEDGER_NAME = "absorb-ledger.json"
LAUNCHD_LOG = "launchd.log"
LEDGER_MAX = 200
PYTHON = "/usr/bin/python3"
LAUNCHCTL = "/bin/launchctl"
LABEL_FORMAT = "io.github.%s.wiki-absorb"
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
LOCALTIME = "/etc/localtime"
ENV_LAUNCH_AGENTS = "WIKI_LAUNCH_AGENTS_DIR"
ENV_LAUNCHCTL = "WIKI_LAUNCHCTL"

# Tried in order after an explicit --claude, settings.claude_path and PATH.
# ~ is the HOME of the environ passed in.
CLAUDE_CANDIDATES = ("~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude")

_VERSION_RE = re.compile(r"[^0-9A-Za-z.]+")
_LABEL_USER_RE = re.compile(r"[^a-z0-9-]+")


# ---------------------------------------------------------------------------
# The pinned copy (.bin/<ver>/)
# ---------------------------------------------------------------------------

def source_templates_dir(scripts_dir=SCRIPTS_DIR):
    """templates/ next to the scripts (inside a .bin copy) or in the skill."""
    for candidate in (os.path.join(scripts_dir, "templates"),
                      os.path.join(os.path.dirname(scripts_dir), "templates")):
        if os.path.isdir(candidate):
            return candidate
    raise common.WikiError("templates_missing", "templates/ not found next to %s" % scripts_dir)


def collect_files(scripts_dir=SCRIPTS_DIR, templates_dir=None):
    """[(relpath in the copy, absolute source path)], sorted. Every top-level
    *.py of scripts/ (so every imported module comes along) and all of
    templates/ under templates/. Caches and dotfiles are left out."""
    templates_dir = templates_dir or source_templates_dir(scripts_dir)
    files = []
    for name in sorted(os.listdir(scripts_dir)):
        full = os.path.join(scripts_dir, name)
        if name.endswith(".py") and not name.startswith(".") and os.path.isfile(full):
            files.append((name, full))
    for dirpath, dirnames, filenames in os.walk(templates_dir):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "__pycache__")
        for name in sorted(filenames):
            if name.startswith(".") or name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, templates_dir).replace(os.sep, "/")
            files.append(("templates/" + rel, full))
    return sorted(files)


def _file_sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_hash(files):
    """One sha256 over (relpath, file sha256) pairs; the same function is used
    for the plugin's scripts and for a .bin copy."""
    digest = hashlib.sha256()
    for rel, path in sorted(files):
        digest.update(rel.encode("utf-8") + b"\0" + _file_sha(path).encode("ascii") + b"\n")
    return digest.hexdigest()


def read_bin_manifest(bin_dir):
    try:
        data = common.load_json_file(os.path.join(bin_dir, BIN_MANIFEST))
    except common.WikiError:
        return None
    return data if isinstance(data, dict) else None


def plugin_version(scripts_dir=SCRIPTS_DIR):
    """The plugin manifest's version, or BIN.json's inside a .bin copy."""
    manifest = read_bin_manifest(scripts_dir)
    if manifest and isinstance(manifest.get("plugin_version"), str):
        return manifest["plugin_version"]
    plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(scripts_dir)))
    for rel in PLUGIN_MANIFESTS:
        try:
            data = common.load_json_file(os.path.join(plugin_dir, rel))
        except common.WikiError:
            continue
        if isinstance(data, dict) and isinstance(data.get("version"), str) and data["version"]:
            return data["version"]
    return "0"


def current_version(scripts_dir=SCRIPTS_DIR):
    """(version, sha256) of the scripts this process runs from."""
    sha = content_hash(collect_files(scripts_dir))
    version = _VERSION_RE.sub("-", plugin_version(scripts_dir)).strip("-") or "0"
    return "%s-%s" % (version, sha[:8]), sha


def bin_root(root):
    return os.path.join(root, common.BIN_DIRNAME)


def _copy_tree(files, dest):
    os.makedirs(dest, 0o755)
    for rel, src in files:
        target = os.path.join(dest, *rel.split("/"))
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            os.makedirs(parent, 0o755)
        shutil.copyfile(src, target)
        os.chmod(target, 0o755 if rel == "wiki.py" else 0o644)


def install_bin(root, scripts_dir=SCRIPTS_DIR, now=None, prune=True):
    """Copy the scripts to .bin/<ver>/ (atomic rename) and return
    (version, bin_dir). An existing copy is reused only when its content
    hash still matches. Other versions are removed when prune is set."""
    files = collect_files(scripts_dir)
    sha = content_hash(files)
    plugin = plugin_version(scripts_dir)
    version = "%s-%s" % (_VERSION_RE.sub("-", plugin).strip("-") or "0", sha[:8])
    base = bin_root(root)
    if not os.path.isdir(base):
        os.makedirs(base, 0o755)
    dest = os.path.join(base, version)
    copied = [(rel, os.path.join(dest, *rel.split("/"))) for rel, _src in files]
    if os.path.isdir(dest):
        manifest = read_bin_manifest(dest)
        intact = all(os.path.isfile(path) for _rel, path in copied)
        if not (manifest and manifest.get("sha256") == sha and intact
                and content_hash(copied) == sha):
            stale = os.path.join(base, ".stale-%s-%d" % (version, os.getpid()))
            os.rename(dest, stale)
            shutil.rmtree(stale, ignore_errors=True)
    if not os.path.isdir(dest):
        tmp = os.path.join(base, ".tmp-%s-%d" % (version, os.getpid()))
        if os.path.lexists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        _copy_tree(files, tmp)
        manifest = collections.OrderedDict()
        manifest["version"] = version
        manifest["plugin_version"] = plugin
        manifest["sha256"] = sha
        manifest["files"] = [rel for rel, _src in files]
        manifest["created"] = _iso(now or time.time())
        common.atomic_write_text(os.path.join(tmp, BIN_MANIFEST), common.dumps_json(manifest),
                                 mode=0o644)
        os.rename(tmp, dest)
    if prune:
        prune_bin(root, version)
    return version, dest


def prune_bin(root, keep):
    """Remove every .bin/ version except keep."""
    base = bin_root(root)
    for name in os.listdir(base):
        path = os.path.join(base, name)
        if name != keep and os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# claude binary, label, environment
# ---------------------------------------------------------------------------

def _home(environ):
    home = environ.get("HOME")
    if not home:
        raise common.WikiError("home_missing", "HOME is not set")
    return home


def _expand(path, environ):
    if path.startswith("~/"):
        return os.path.join(_home(environ), path[2:])
    return path


def pick_claude(environ, settings, explicit=None, candidates=None, probe=None):
    """The first absolute claude that passes absorb's flag probe.

    An explicit path that fails is an error (no silent fallback). The order
    is explicit, settings.claude_path, `claude` on PATH, then
    CLAUDE_CANDIDATES. Raises claude_missing when nothing executable was
    found, claude_flags_missing when every candidate lacked a flag."""
    import absorb

    probe = probe or (lambda path: absorb.probe_claude(path, absorb.llm_env(environ, path)))
    order = []
    if explicit:
        path = os.path.abspath(_expand(explicit, environ))
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            raise common.WikiError("claude_missing", "%s is not an executable file" % path)
        probe(path)
        return path
    if settings.get("claude_path"):
        order.append(settings["claude_path"])
    found = shutil.which("claude", path=environ.get("PATH") or os.defpath)
    if found:
        order.append(os.path.abspath(found))
    for candidate in (CLAUDE_CANDIDATES if candidates is None else candidates):
        order.append(_expand(candidate, environ))
    seen = set()
    tried = []
    for path in order:
        if path in seen:
            continue
        seen.add(path)
        if not (os.path.isabs(path) and os.path.isfile(path) and os.access(path, os.X_OK)):
            continue
        try:
            probe(path)
            return path
        except common.WikiError as exc:
            tried.append("%s (%s)" % (path, exc.reason))
    if tried:
        raise common.WikiError("claude_flags_missing",
                               "no claude supports the absorb flags: %s" % "; ".join(tried))
    raise common.WikiError("claude_missing", "no executable claude found")


DEFAULT_LABEL_USER = "local"


def label_for(settings, environ=None):
    """io.github.<label_user>.wiki-absorb. Without label_user the neutral
    default `local` is used, never $USER (panel D-8: no company name)."""
    raw = (settings.get("schedule") or {}).get("label_user") or DEFAULT_LABEL_USER
    user = _LABEL_USER_RE.sub("-", raw.strip().lower()).strip("-")
    if not user:
        raise common.WikiError("label_user_missing",
                               "settings.json schedule.label_user has no usable characters")
    return LABEL_FORMAT % user


def detect_tz(environ, localtime=LOCALTIME):
    if environ.get("TZ"):
        return environ["TZ"]
    try:
        target = os.readlink(localtime)
    except OSError:
        return None
    marker = "zoneinfo/"
    return target.split(marker, 1)[1] if marker in target else None


def job_path(claude_path, environ, settings, root):
    """PATH for the job: claude's folder, token_cmd's folder (doppler), then
    the system folders."""
    import notify

    dirs = []
    if claude_path:
        dirs.append(os.path.dirname(claude_path))
    try:
        config = notify.load_config(root, settings)
    except common.WikiError:
        config = None
    if config and config["token_cmd"]:
        program = notify.resolve_program(config["token_cmd"][0], environ)
        if program:
            dirs.append(os.path.dirname(program))
    dirs += list(SYSTEM_PATH)
    result = []
    for item in dirs:
        if item and item not in result:
            result.append(item)
    return ":".join(result)


def job_environment(root, environ, settings, claude_path, localtime=LOCALTIME):
    env = collections.OrderedDict()
    env["HOME"] = _home(environ)
    env["USER"] = environ.get("USER") or os.path.basename(env["HOME"].rstrip("/"))
    env["PATH"] = job_path(claude_path, environ, settings, root)
    tz = detect_tz(environ, localtime)
    if tz:
        env["TZ"] = tz
    env["WIKI_ROOT"] = root
    env["LLM_WIKI_HOOK"] = "0"
    if environ.get("CLAUDE_CONFIG_DIR"):
        env["CLAUDE_CONFIG_DIR"] = environ["CLAUDE_CONFIG_DIR"]
    if environ.get("WIKI_RULES_PATH"):
        env["WIKI_RULES_PATH"] = environ["WIKI_RULES_PATH"]
    return env


def build_plist(label, bin_dir, root, env, interval, rules_path=None, python=PYTHON):
    args = [python, os.path.join(bin_dir, "wiki.py"), "--root", root, "absorb", "--scheduled"]
    if rules_path:
        args += ["--rules-path", rules_path]
    log = os.path.join(common.state_dir(root), LAUNCHD_LOG)
    plist = collections.OrderedDict()
    plist["Label"] = label
    plist["ProgramArguments"] = args
    plist["StartInterval"] = int(interval)
    plist["RunAtLoad"] = True
    plist["ProcessType"] = "Background"
    plist["EnvironmentVariables"] = dict(env)
    plist["StandardOutPath"] = log
    plist["StandardErrorPath"] = log
    return plist


def plist_bytes(plist):
    return plistlib.dumps(dict(plist), fmt=plistlib.FMT_XML, sort_keys=True)


def launch_agents_dir(environ, override=None):
    return override or environ.get(ENV_LAUNCH_AGENTS) or os.path.join(
        _home(environ), "Library", "LaunchAgents")


def launchctl_path(environ, override=None):
    return override or environ.get(ENV_LAUNCHCTL) or LAUNCHCTL


def _launchctl(launchctl, args, check=True):
    try:
        proc = subprocess.run([launchctl] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise common.WikiError("launchctl_failed", "cannot run launchctl: %s" % exc)
    if check and proc.returncode != 0:
        raise common.WikiError("launchctl_failed", "launchctl %s exited %d: %s" % (
            args[0], proc.returncode, proc.stderr.decode("utf-8", "replace").strip()[:200]))
    return proc


BOOTSTRAP_ATTEMPTS = 5
BOOTSTRAP_DELAY = 0.5


def bootstrap(tool, domain, plist_path, attempts=BOOTSTRAP_ATTEMPTS, delay=BOOTSTRAP_DELAY,
              sleep=time.sleep):
    """`launchctl bootstrap`, retried: bootout finishes asynchronously, so a
    bootstrap right after it often fails with 'Input/output error'."""
    last = None
    for attempt in range(attempts):
        proc = _launchctl(tool, ["bootstrap", domain, plist_path], check=False)
        if proc.returncode == 0:
            return proc
        last = proc
        if attempt + 1 < attempts:
            sleep(delay)
    raise common.WikiError("launchctl_failed", "launchctl bootstrap exited %d (job not loaded; "
                           "the plist is written, run schedule install again): %s" % (
                               last.returncode,
                               last.stderr.decode("utf-8", "replace").strip()[:200]))


def pin_claude_path(root, claude_path):
    """Write claude_path into settings.json (raw keys kept, defaults not
    added) and commit only that file. Returns True when it changed."""
    path = os.path.join(root, "settings.json")
    if os.path.exists(path):
        raw = common.load_json_file(path)
        if not isinstance(raw, dict):
            raise common.ConfigError("settings_invalid", "settings.json must be a JSON object")
    else:
        raw = collections.OrderedDict()
    if raw.get("claude_path") == claude_path:
        return False
    raw["claude_path"] = claude_path
    common.validate_settings(raw)
    common.atomic_write_text(path, common.dumps_json(raw), mode=0o644)
    common.wiki_git(root, ["add", "--", "settings.json"])
    staged = common.wiki_git(root, ["diff", "--cached", "--quiet", "--", "settings.json"],
                             check=False)
    if staged.returncode == 1:
        common.wiki_git(root, ["commit", "-q", "--no-verify", "-m",
                               "wiki: schedule claude_path", "--", "settings.json"])
    return True


def _require_wiki(root):
    if not common.is_initialized(root) or not os.path.isdir(os.path.join(root, ".git")):
        raise common.WikiError("not_initialized", "%s is not a wiki; run wiki init" % root)


def plan(root, environ, claude=None, rules_path=None, candidates=None, probe=None,
         localtime=LOCALTIME, strict=True):
    """Everything install needs, computed without writing anything."""
    settings = common.load_settings(root)
    warnings = []
    try:
        claude_path = pick_claude(environ, settings, claude, candidates, probe)
    except common.WikiError as exc:
        if strict:
            raise
        claude_path = None
        warnings.append(exc.reason)
    label = label_for(settings, environ)
    version, _sha = current_version()
    bin_dir = os.path.join(bin_root(root), version)
    env = job_environment(root, environ, settings, claude_path, localtime)
    plist = build_plist(label, bin_dir, root, env, settings["schedule"]["interval_seconds"],
                        rules_path)
    agents = launch_agents_dir(environ)
    result = collections.OrderedDict()
    result["label"] = label
    result["plist_path"] = os.path.join(agents, label + ".plist")
    result["version"] = version
    result["bin_dir"] = bin_dir
    result["claude_path"] = claude_path
    result["plist"] = plist
    try:
        import notify

        if not notify.load_config(root, settings)["enabled"]:
            # Slack is the only feedback of a scheduled run.
            warnings.append("notify_not_configured")
    except common.WikiError as exc:
        warnings.append(exc.reason)
    guard = common.domains_guard(common.load_domains(root), root)
    if guard:
        warnings.append(guard)
    result["warnings"] = warnings
    return result


def print_plist(root, environ, claude=None, rules_path=None, candidates=None, probe=None,
                localtime=LOCALTIME):
    _require_wiki(root)
    info = plan(root, environ, claude, rules_path, candidates, probe, localtime, strict=False)
    info["xml"] = plist_bytes(info["plist"]).decode("utf-8")
    return info


def install(root, environ, claude=None, rules_path=None, no_load=False, agents_dir=None,
            launchctl=None, candidates=None, probe=None, localtime=LOCALTIME, uid=None):
    _require_wiki(root)
    # RunAtLoad fires an absorb at once: with domains.json still holding
    # template placeholders it would fail (owners_unset) and use up the
    # day's run, so install refuses with the same reason code.
    guard = common.domains_guard(common.load_domains(root), root)
    if guard:
        raise common.WikiError(guard, "domains.json: fill in owners and work_terms before "
                                      "schedule install")
    with common.wiki_lock(root):
        info = plan(root, environ, claude, rules_path, candidates, probe, localtime)
        info["claude_pinned"] = pin_claude_path(root, info["claude_path"])
        # Old versions stay until the new job is loaded: with --no-load a
        # job loaded earlier still runs from its own .bin/<ver>/.
        version, bin_dir = install_bin(root, prune=False)
        if version != info["version"]:
            raise common.WikiError("bin_version_mismatch", "scripts changed during install")
        common.ensure_private_dir(common.state_dir(root))
        agents = launch_agents_dir(environ, agents_dir)
        if not os.path.isdir(agents):
            os.makedirs(agents, 0o755)
        info["plist_path"] = os.path.join(agents, info["label"] + ".plist")
        data = plist_bytes(info["plist"])
        tmp = info["plist_path"] + ".tmp-%d" % os.getpid()
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o644)
        os.rename(tmp, info["plist_path"])
        info["loaded"] = False
        if not no_load:
            tool = launchctl_path(environ, launchctl)
            domain = "gui/%d" % (os.getuid() if uid is None else uid)
            _launchctl(tool, ["bootout", "%s/%s" % (domain, info["label"])], check=False)
            bootstrap(tool, domain, info["plist_path"])
            info["loaded"] = True
            prune_bin(root, version)
    return info


def uninstall(root, environ, no_load=False, agents_dir=None, launchctl=None, uid=None):
    settings = (common.load_settings(root) if os.path.isdir(root)
                else common.validate_settings({}))
    label = label_for(settings, environ)
    path = os.path.join(launch_agents_dir(environ, agents_dir), label + ".plist")
    result = collections.OrderedDict()
    result["label"] = label
    result["plist_path"] = path
    result["unloaded"] = False
    result["removed"] = False
    if not os.path.lexists(path):
        # Nothing installed by us: launchctl is not called at all.
        return result
    guard = common.wiki_lock(root) if common.is_initialized(root) else contextlib.nullcontext()
    with guard:
        if not no_load:
            tool = launchctl_path(environ, launchctl)
            domain = "gui/%d" % (os.getuid() if uid is None else uid)
            proc = _launchctl(tool, ["bootout", "%s/%s" % (domain, label)], check=False)
            result["unloaded"] = proc.returncode == 0
        result["removed"] = os.path.lexists(path)
        if result["removed"]:
            os.unlink(path)
    return result


def installed_info(root, environ, agents_dir=None):
    """What the installed plist points at, and whether that .bin copy is
    behind the scripts this process runs from (status warning bin_stale)."""
    result = collections.OrderedDict()
    try:
        settings = common.load_settings(root)
        label = label_for(settings, environ)
    except common.WikiError as exc:
        result["installed"] = False
        result["reason"] = exc.reason
        return result
    path = os.path.join(launch_agents_dir(environ, agents_dir), label + ".plist")
    result["label"] = label
    result["plist_path"] = path
    result["installed"] = os.path.isfile(path)
    version, _sha = current_version()
    result["current_version"] = version
    result["bin_version"] = None
    result["bin_stale"] = False
    if not result["installed"]:
        return result
    try:
        with open(path, "rb") as handle:
            plist = plistlib.load(handle)
        program = plist["ProgramArguments"][1]
    except (IOError, OSError, KeyError, IndexError, TypeError, ValueError,
            plistlib.InvalidFileException):
        result["bin_stale"] = True
        result["reason"] = "plist_unreadable"
        return result
    bin_dir = os.path.dirname(program)
    manifest = read_bin_manifest(bin_dir)
    result["bin_version"] = manifest.get("version") if manifest else None
    result["bin_stale"] = result["bin_version"] != version
    return result


# ---------------------------------------------------------------------------
# The ledger and the 20-hour rule
# ---------------------------------------------------------------------------

def ledger_path(root):
    return os.path.join(common.state_dir(root), LEDGER_NAME)


def _iso(epoch):
    return datetime.datetime.fromtimestamp(epoch).astimezone().replace(microsecond=0).isoformat()


def read_ledger(root):
    try:
        data = common.load_json_file(ledger_path(root))
    except common.WikiError:
        return {"runs": []}
    if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
        return {"runs": []}
    data["runs"] = [entry for entry in data["runs"] if isinstance(entry, dict)]
    return data


def _write_ledger(root, data):
    data["runs"] = data["runs"][-LEDGER_MAX:]
    common.ensure_private_dir(common.state_dir(root))
    common.atomic_write_text(ledger_path(root), common.dumps_json(data), mode=0o600)


def make_entry(report, started, finished, scheduled):
    entry = collections.OrderedDict()
    entry["started_at"] = _iso(started)
    entry["started_epoch"] = round(started, 3)
    entry["finished_at"] = _iso(finished)
    entry["scheduled"] = bool(scheduled)
    entry["run_id"] = report.get("run_id")
    entry["status"] = report.get("status")
    entry["reason"] = report.get("reason")
    entry["counts"] = collections.OrderedDict(
        (key, report.get(key, 0) if isinstance(report.get(key, 0), int) else 0)
        for key in ("applied", "new_pages", "quarantined", "unresolved",
                    "rules_added", "rules_removed"))
    entry["notify"] = None
    return entry


def record_run(root, entry):
    data = read_ledger(root)
    data["runs"].append(entry)
    _write_ledger(root, data)


def record_notify(root, started_epoch, result):
    data = read_ledger(root)
    for entry in reversed(data["runs"]):
        if entry.get("started_epoch") == started_epoch:
            entry["notify"] = result
            _write_ledger(root, data)
            return True
    return False


def last_run_epoch(root):
    """Start time of the last recorded run; falls back to .state/last-absorb
    (finished_at) for runs made before the ledger existed."""
    runs = read_ledger(root)["runs"]
    for entry in reversed(runs):
        value = entry.get("started_epoch")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    try:
        data = common.load_json_file(os.path.join(common.state_dir(root), "last-absorb"))
        moment = datetime.datetime.fromisoformat(data["finished_at"])
    except (common.WikiError, KeyError, TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return time.mktime(moment.timetuple())
    return moment.timestamp()


def due_check(root, settings, now_epoch):
    """(due, why): why is first_run, due, ran_today or too_soon."""
    last = last_run_epoch(root)
    if last is None:
        return True, "first_run"
    if time.localtime(last)[:3] == time.localtime(now_epoch)[:3]:
        return False, "ran_today"
    hours = (settings.get("schedule") or {}).get("min_hours_between_runs", 20)
    if now_epoch - last < float(hours) * 3600.0:
        return False, "too_soon"
    return True, "due"


def next_due_epoch(root, settings):
    last = last_run_epoch(root)
    if last is None:
        return None
    hours = (settings.get("schedule") or {}).get("min_hours_between_runs", 20)
    by_hours = last + float(hours) * 3600.0
    day = datetime.datetime.fromtimestamp(last).date() + datetime.timedelta(days=1)
    midnight = time.mktime(datetime.datetime(day.year, day.month, day.day).timetuple())
    return max(by_hours, midnight)


def _failed_report(reason):
    report = collections.OrderedDict()
    report["ok"] = False
    report["status"] = "failed"
    report["reason"] = reason
    report["run_id"] = None
    report["applied"] = 0
    report["new_pages"] = 0
    report["quarantined"] = 0
    report["unresolved"] = 0
    report["rules_added"] = 0
    report["rules_removed"] = 0
    report["batches"] = []
    report["warnings"] = []
    report["summary_line"] = "위키: 실패 (%s)" % reason
    return report


def run_absorb(root, environ, scheduled=False, rules_path=None, send=True, absorb_fn=None,
               notify_fn=None, clock=None):
    """absorb with the ledger and the Slack line around it.

    Returns the report, or None for a silent scheduled skip (not due, lock
    busy, no wiki). Order: run, ledger, notify, ledger notify field, so a
    crash in notify never makes the run count twice or run again."""
    clock = clock or time.time
    if scheduled:
        if not common.is_initialized(root) or not os.path.isdir(os.path.join(root, ".git")):
            return None
        try:
            settings = common.load_settings(root)
        except common.WikiError:
            settings = common.validate_settings({})
        due, _why = due_check(root, settings, clock())
        if not due:
            return None
    if absorb_fn is None:
        import absorb
        absorb_fn = absorb.absorb
    started = clock()
    try:
        report = absorb_fn(root, environ, rules_path=rules_path, scheduled=scheduled)
    except common.LockBusy:
        if scheduled:
            return None
        raise
    except common.WikiError as exc:
        if exc.reason == "not_initialized":
            if scheduled:
                return None
            raise
        report = _failed_report(exc.reason)
    except Exception:
        # The traceback may name work pages or source ids (D2): it goes to
        # .state/last-report.json (0600) only, and to stderr only for
        # --scheduled, whose stderr is .state/launchd.log.
        trace = traceback.format_exc()
        if scheduled:
            sys.stderr.write(trace)
        report = _failed_report("internal_error")
        report["traceback"] = trace
    report.setdefault("warnings", [])
    entry = make_entry(report, started, clock(), scheduled)
    try:
        record_run(root, entry)
    except (common.WikiError, IOError, OSError):
        report["warnings"].append("ledger_write_failed")
    if send:
        if notify_fn is None:
            import notify
            notify_fn = notify.notify
        try:
            result = notify_fn(root, report, environ)
        except Exception:
            result = {"state": None, "text": None, "mode": None, "sent": False,
                      "reason": "notify_internal_error"}
        report["notify"] = result
        try:
            record_notify(root, entry["started_epoch"], result)
        except (common.WikiError, IOError, OSError):
            report["warnings"].append("ledger_write_failed")
    return report
