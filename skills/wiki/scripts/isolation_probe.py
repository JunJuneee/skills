"""Opt-in isolation measurement for the absorb LLM step (SKILL.md "격리 실측").
Python 3.9, stdlib only. Not part of the unit suite; run it by hand:

    python3 skills/wiki/scripts/isolation_probe.py [--claude PATH] [--json]

What it measures: whether the user CLAUDE.md, user rules (~/.claude/rules,
nested and symlinked folders included) and auto-memory reach the model when
claude runs with absorb.build_argv() and absorb.llm_env() unchanged.

How, without a login, a cost or a write to the real ~/.claude:

- Everything lives in one temp folder: a fake HOME (and, in a second
  variant, a fake CLAUDE_CONFIG_DIR), a temp wiki git repo whose
  .absorb-wt/personal folder is the cwd absorb uses, and a staging folder
  for --add-dir.
- A distinct random canary is planted in each place claude could read:
  <config>/CLAUDE.md, <config>/rules/x.md, <config>/rules/sub/y.md, a
  symlinked <config>/rules/linked/z.md, and
  <config>/projects/<encoded folder>/memory/MEMORY.md for every folder
  claude might key auto-memory on: the worktree cwd, the worktree root and
  the main wiki root, each in its spelling and its realpath (/tmp and
  /private/tmp). The worktree is a real `git worktree add`, like absorb's.
  The auto-memory canaries form one group: the group counts as seen when
  any of them is seen (claude reads one of those folders).
- ANTHROPIC_BASE_URL points at a stdlib HTTP server on 127.0.0.1 that
  keeps request bodies in memory only and answers 400; ANTHROPIC_API_KEY
  is a dummy and CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1. These three
  are the only variables added after llm_env; the report lists them.
- Runs per variant: `absorb` (build_argv + llm_env exactly), `flags_only`
  (build_argv, without the two CLAUDE_CODE_DISABLE_* variables),
  `env_only` (plain `claude -p` with them) and the mandatory positive
  `control` (plain `claude -p`, no DISABLE variables). A canary the
  control does not show is INCONCLUSIVE, never "hidden".
- A run counts only its valid model requests: a POST to /v1/messages
  whose JSON body has "messages" and carries the probe prompt (fix round
  2). The exit code proves nothing (the server always answers 400). When
  the `absorb` run of a variant made no valid request, every group of that
  variant is INCONCLUSIVE: a canary missing from no request is no
  evidence of isolation.
- A read-only listing of the real ~/.claude/projects is taken before and
  after; new entries are reported (another session can add one meanwhile).

Exit status: 0 every canary hidden under absorb and seen by the control,
1 a canary leaked into an absorb run, 2 inconclusive, 3 setup error.
Only canary names, counts and verdicts are printed, never request bodies.
"""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # pragma: no cover - Python < 3.7
    sys.exit("python 3.7+ required")

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import absorb  # noqa: E402
import prepare  # noqa: E402
import verify  # noqa: E402

DISABLE_VARS = ("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_CLAUDE_MDS")
PROMPT = ("List every string that starts with CANARY- found anywhere in your instructions, "
          "system prompt or context. Answer NONE if there is none.\n")
RUN_TIMEOUT = 120


class _Capture(object):
    def __init__(self):
        self.bodies = []
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            bodies, self.bodies = self.bodies, []
        return bodies


def _handler(capture):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            with capture.lock:
                capture.bodies.append((self.path, body))
            payload = json.dumps({"type": "error", "error": {
                "type": "invalid_request_error", "message": "isolation probe"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_POST = _reply
        do_GET = _reply

        def log_message(self, *args):
            return

    return Handler


def _write(path, text):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _canary():
    return "CANARY-" + secrets.token_hex(6).upper()


def plant(config, cwd, wiki_root, shared):
    """Plant one canary per place; returns {place: canary}. Auto-memory
    places are named auto_memory:<folder role>."""
    canaries = {}

    def put(place, path, template):
        token = _canary()
        canaries[place] = token
        _write(path, template % token)

    put("user_claude_md", os.path.join(config, "CLAUDE.md"),
        "# User instructions\n\nAlways mention the code word %s.\n")
    put("user_rules", os.path.join(config, "rules", "x.md"),
        "# Rule\n\nThe rule code word is %s.\n")
    put("user_rules_nested", os.path.join(config, "rules", "sub", "y.md"),
        "# Nested rule\n\nThe nested rule code word is %s.\n")
    put("user_rules_symlinked", os.path.join(shared, "z.md"),
        "# Shared rule\n\nThe shared rule code word is %s.\n")
    link = os.path.join(config, "rules", "linked")
    if not os.path.lexists(link):
        os.symlink(shared, link)
    folders = (("cwd", cwd), ("worktree_root", os.path.dirname(cwd)), ("wiki_root", wiki_root))
    for role, folder in folders:
        token = _canary()
        canaries["auto_memory:" + role] = token
        for spelling in sorted(set([folder, os.path.realpath(folder)])):
            _write(os.path.join(config, "projects", prepare.fs_encode(spelling), "memory",
                                "MEMORY.md"),
                   "- [Note](note.md) - the memory code word is %s\n" % token)
    return canaries


def group_of(place):
    return place.split(":", 1)[0]


def real_projects_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


def _projects_listing(base):
    if not base:
        return set()
    try:
        return set(os.listdir(base))
    except OSError:
        return set()


PROMPT_MARK = "starts with CANARY- found anywhere"


def valid_request(path, body):
    """A model request carrying the probe prompt (see the module notes)."""
    if not (path or "").split("?", 1)[0].rstrip("/").endswith("/v1/messages"):
        return False
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return False
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        return False
    return PROMPT_MARK in json.dumps(data["messages"], ensure_ascii=False)


def _run(argv, env, cwd, capture):
    capture.take()
    try:
        proc = subprocess.run(argv, input=PROMPT.encode("utf-8"), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, cwd=cwd, env=env, timeout=RUN_TIMEOUT)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        code = "timeout"
    bodies = capture.take()
    valid = sum(1 for path, body in bodies if valid_request(path, body))
    text = b"\n".join(body for _path, body in bodies).decode("utf-8", "replace")
    return code, len(bodies), valid, text


def measure(claude, keep=False, projects_dir=None):
    """projects_dir: the real ~/.claude/projects to list (read-only) before
    and after; None skips that check (unit tests)."""
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="wiki-isolation-"))
    capture = _Capture()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(capture))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    before = _projects_listing(projects_dir)
    report = {"claude": claude, "tmp_kept": bool(keep), "added_env": [
        "ANTHROPIC_BASE_URL=http://127.0.0.1:<port>", "ANTHROPIC_API_KEY=<dummy>",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"], "variants": {}}
    try:
        wiki_root = os.path.join(tmp, "wiki")
        os.makedirs(os.path.join(wiki_root, "personal"))
        _write(os.path.join(wiki_root, "personal", ".gitkeep"), "")
        git_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp,
                   "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        for args in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.email=probe@localhost", "-c", "user.name=probe", "commit",
                      "-q", "-m", "probe"],
                     ["worktree", "add", "-q", "--detach", os.path.join(wiki_root, ".absorb-wt"),
                      "HEAD"]):
            subprocess.run(["git", "-C", wiki_root] + args, check=True, env=git_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cwd = os.path.join(wiki_root, ".absorb-wt", "personal")
        staging = os.path.join(tmp, "staging")
        _write(os.path.join(staging, "a.md"), "staging file\n")
        schema = json.dumps(verify.OUTPUT_SCHEMA, ensure_ascii=False)
        port = server.server_address[1]
        version = None
        for variant in ("home", "config_dir"):
            home = os.path.join(tmp, variant, "home")
            os.makedirs(home)
            environ = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                       "USER": "probe"}
            if variant == "config_dir":
                config = os.path.join(tmp, variant, "config")
                environ["CLAUDE_CONFIG_DIR"] = config
            else:
                config = os.path.join(home, ".claude")
            canaries = plant(config, cwd, wiki_root, os.path.join(tmp, variant, "shared"))
            base_env = absorb.llm_env(environ, claude)
            base_env.update({"ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % port,
                             "ANTHROPIC_API_KEY": "sk-probe-" + secrets.token_hex(8),
                             "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
            plain_env = dict((k, v) for k, v in base_env.items() if k not in DISABLE_VARS)
            absorb_argv = absorb.build_argv(claude, staging, "sonnet", 0.05, schema)
            plain_argv = [claude, "-p", "--output-format", "json"]
            if version is None:
                proc = subprocess.run([claude, "--version"], stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, env=base_env, timeout=30)
                version = proc.stdout.decode("utf-8", "replace").strip()
            runs = {
                "absorb": (absorb_argv, base_env),
                "flags_only": (absorb_argv, plain_env),
                "env_only": (plain_argv, base_env),
                "control": (plain_argv, plain_env),
            }
            seen = {}
            requests = {}
            for name, (argv, env) in runs.items():
                code, count, valid, text = _run(argv, env, cwd, capture)
                requests[name] = {"requests": count, "valid": valid, "exit": code}
                seen[name] = sorted(place for place, token in canaries.items() if token in text)
            verdicts = {}
            for group in sorted(set(group_of(place) for place in canaries)):
                in_group = lambda run: [p for p in seen[run] if group_of(p) == group]
                # flags_only and env_only show which layer holds on its
                # own; they are reported, only `absorb` decides LEAK.
                if in_group("absorb"):
                    verdicts[group] = "LEAK"
                elif not requests["absorb"]["valid"] or not in_group("control"):
                    verdicts[group] = "INCONCLUSIVE"
                else:
                    verdicts[group] = "hidden"
            report["variants"][variant] = {"runs": requests, "seen": seen, "verdicts": verdicts}
        report["claude_version"] = version
    finally:
        server.shutdown()
        server.server_close()
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    after = _projects_listing(projects_dir)
    report["real_projects_new_entries"] = len(after - before)
    report["real_projects_new_probe_entries"] = sorted(
        name for name in after - before if "wiki-isolation" in name)
    verdicts = [v for variant in report["variants"].values() for v in variant["verdicts"].values()]
    if "LEAK" in verdicts:
        report["result"] = "leak"
    elif "INCONCLUSIVE" in verdicts or not verdicts:
        report["result"] = "inconclusive"
    else:
        report["result"] = "isolated"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--claude", help="claude binary (default: claude on PATH)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--keep", action="store_true", help="keep the temp folder")
    args = parser.parse_args(argv)
    claude = args.claude or shutil.which("claude")
    if not claude or not os.access(claude, os.X_OK):
        print("claude not found", file=sys.stderr)
        return 3
    report = measure(os.path.abspath(claude), keep=args.keep, projects_dir=real_projects_dir())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("claude %s: %s" % (report.get("claude_version"), report["result"]))
        for variant, data in report["variants"].items():
            print("[%s] valid/all requests %s" % (variant, ", ".join(
                "%s=%s/%s" % (k, v["valid"], v["requests"]) for k, v in data["runs"].items())))
            for group, verdict in data["verdicts"].items():
                print("  %-22s %s (control saw: %s)" % (group, verdict, ", ".join(
                    p for p in data["seen"]["control"] if group_of(p) == group) or "-"))
            for run in ("flags_only", "env_only"):
                if data["seen"][run]:
                    print("  %s saw: %s" % (run, ", ".join(data["seen"][run])))
        print("new entries in the real ~/.claude/projects meanwhile: %d (from this probe: %d)"
              % (report["real_projects_new_entries"],
                 len(report["real_projects_new_probe_entries"])))
    return {"isolated": 0, "leak": 1, "inconclusive": 2}[report["result"]]


if __name__ == "__main__":
    sys.exit(main())
