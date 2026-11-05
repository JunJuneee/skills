"""schedule (T5, D7 + panel D-8): .bin copy, plist, launchctl, ledger,
the 20-hour rule and the scheduled absorb wrapper.

launchctl and the LaunchAgents folder are always fakes under the temp dir;
claude is a fake script whose --help lists (or lacks) the absorb flags."""

import datetime
import json
import os
import plistlib
import subprocess
import sys
import time
import unittest

import _helpers
import common
import schedule
import wiki

FULL_HELP = """Usage: claude [options] [command] [prompt]
  -p, --print                         Print response and exit
  --add-dir <directories...>          Additional directories
  --json-schema <schema>              JSON Schema for structured output
  --max-budget-usd <amount>           Maximum dollar amount
  --model <model>                     Model
  --no-session-persistence            Disable session persistence
  --output-format <format>            Output format
  --permission-mode <mode>            (choices: "acceptEdits", "auto")
  --permission-prompts <target>       (choices: "host", "none")
  --restricted                        Restricted mode
  --setting-sources <sources>         Setting sources
  --strict-mcp-config                 Only use MCP servers from --mcp-config
  --tools <tools...>                  Tools
"""
OLD_HELP = "\n".join(line for line in FULL_HELP.splitlines() if "--restricted" not in line)

FAKE_CLAUDE = "#!%s\nimport sys\nif sys.argv[1:] == ['--help']:\n    sys.stdout.write(%r)\n" \
              "    sys.exit(0)\nsys.exit(9)\n"
FAKE_LAUNCHCTL = "#!%s\nimport json, sys\nwith open(%r, 'a') as h:\n" \
                 "    h.write(json.dumps(sys.argv[1:]) + '\\n')\nsys.exit(%d)\n"


def local_epoch(*parts):
    return time.mktime(datetime.datetime(*parts).timetuple())


def write_exec(path, text):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o755)
    return path


class ScheduleCase(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        self.env["TZ"] = "Asia/Seoul"
        self.env["USER"] = "tester"
        wiki.init_wiki(self.root, self.env)
        with open(os.path.join(self.root, "domains.json"), "w") as handle:
            json.dump({"owners": {"MeUser": "personal", "WorkOrg": "work"},
                       "work_terms": ["AcmeCorp"]}, handle)
        self.bindir = os.path.join(self.tmp, "bin")
        self.claude = self.fake_claude("claude", FULL_HELP)
        self.agents = os.path.join(self.tmp, "LaunchAgents")
        self.launchctl_log = os.path.join(self.tmp, "launchctl.jsonl")
        self.launchctl = self.fake_launchctl(0)

    def fake_claude(self, name, help_text):
        return write_exec(os.path.join(self.bindir, name), FAKE_CLAUDE % (sys.executable, help_text))

    def fake_launchctl(self, code, name="launchctl"):
        return write_exec(os.path.join(self.tmp, "tools", name),
                          FAKE_LAUNCHCTL % (sys.executable, self.launchctl_log, code))

    def launchctl_calls(self):
        if not os.path.exists(self.launchctl_log):
            return []
        with open(self.launchctl_log) as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def install(self, **kwargs):
        kwargs.setdefault("claude", self.claude)
        kwargs.setdefault("agents_dir", self.agents)
        kwargs.setdefault("launchctl", self.launchctl)
        kwargs.setdefault("uid", 501)
        return schedule.install(self.root, self.env, **kwargs)

    def write_settings(self, data):
        with open(os.path.join(self.root, "settings.json"), "w") as handle:
            json.dump(data, handle)


class BinCopyTest(ScheduleCase):
    def test_copy_has_every_module_and_templates(self):
        version, dest = schedule.install_bin(self.root)
        self.assertEqual(dest, os.path.join(self.root, ".bin", version))
        source_files = schedule.collect_files()
        copy_files = schedule.collect_files(dest)
        self.assertEqual([rel for rel, _ in source_files], [rel for rel, _ in copy_files])
        rels = [rel for rel, _ in copy_files]
        for name in os.listdir(_helpers.SCRIPTS_DIR):
            if name.endswith(".py"):
                self.assertIn(name, rels)
        self.assertIn("templates/absorb_prompt.md", rels)
        self.assertIn("templates/SCHEMA.md", rels)
        self.assertFalse([rel for rel in rels if "__pycache__" in rel or rel.endswith(".pyc")])
        sha = schedule.content_hash(source_files)
        self.assertEqual(schedule.content_hash(copy_files), sha)
        self.assertTrue(version.endswith("-" + sha[:8]))
        manifest = schedule.read_bin_manifest(dest)
        self.assertEqual(manifest["sha256"], sha)
        self.assertEqual(manifest["version"], version)
        # Inside the copy the version is read from BIN.json.
        self.assertEqual(schedule.current_version(dest), schedule.current_version())

    def test_copy_runs_on_its_own(self):
        _version, dest = schedule.install_bin(self.root)
        python = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
        other = os.path.join(self.tmp, "other-wiki")
        proc = subprocess.run([python, "-I", os.path.join(dest, "wiki.py"), "--root", other,
                               "--json", "init"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=self.env, cwd=self.tmp, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertTrue(os.path.isfile(os.path.join(other, "SCHEMA.md")))

    def test_reuse_repair_and_prune(self):
        version, dest = schedule.install_bin(self.root)
        old = os.path.join(self.root, ".bin", "0.0.1-deadbeef")
        os.makedirs(old)
        with open(os.path.join(dest, "common.py"), "a") as handle:
            handle.write("\n# tampered\n")
        version2, dest2 = schedule.install_bin(self.root)
        self.assertEqual((version2, dest2), (version, dest))
        self.assertEqual(schedule.content_hash(schedule.collect_files(dest)),
                         schedule.content_hash(schedule.collect_files()))
        self.assertFalse(os.path.exists(old))
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, ".bin"))), [version])


class PlanTest(ScheduleCase):
    def test_label(self):
        self.assertEqual(schedule.label_for({"schedule": {"label_user": "Some User"}}, {}),
                         "io.github.some-user.wiki-absorb")
        # Never $USER (it can be an employer-issued account name).
        self.assertEqual(schedule.label_for({"schedule": {"label_user": ""}}, {"USER": "me"}),
                         "io.github.local.wiki-absorb")
        with self.assertRaises(common.WikiError) as ctx:
            schedule.label_for({"schedule": {"label_user": "@@"}}, {"USER": "me"})
        self.assertEqual(ctx.exception.reason, "label_user_missing")

    def test_detect_tz(self):
        self.assertEqual(schedule.detect_tz({"TZ": "Europe/Paris"}), "Europe/Paris")
        link = os.path.join(self.tmp, "localtime")
        os.symlink("/var/db/timezone/zoneinfo/Asia/Tokyo", link)
        self.assertEqual(schedule.detect_tz({}, link), "Asia/Tokyo")
        self.assertIsNone(schedule.detect_tz({}, os.path.join(self.tmp, "missing")))

    def test_pick_claude_skips_binaries_without_flags(self):
        old = self.fake_claude("claude-old", OLD_HELP)
        env = dict(self.env, PATH=os.path.join(self.tmp, "empty"))
        settings = common.validate_settings({})
        self.assertEqual(schedule.pick_claude(env, settings, candidates=[old, self.claude]),
                         self.claude)
        with self.assertRaises(common.WikiError) as ctx:
            schedule.pick_claude(env, settings, candidates=[old])
        self.assertEqual(ctx.exception.reason, "claude_flags_missing")
        with self.assertRaises(common.WikiError) as ctx:
            schedule.pick_claude(env, settings, candidates=[os.path.join(self.tmp, "none")])
        self.assertEqual(ctx.exception.reason, "claude_missing")
        # An explicit choice never falls back to another binary.
        with self.assertRaises(common.WikiError) as ctx:
            schedule.pick_claude(env, settings, explicit=old, candidates=[self.claude])
        self.assertEqual(ctx.exception.reason, "claude_flags_missing")
        # settings.claude_path comes before PATH and the candidates.
        other = self.fake_claude("claude-pinned", FULL_HELP)
        settings = common.validate_settings({"claude_path": other})
        self.assertEqual(schedule.pick_claude(env, settings, candidates=[self.claude]), other)
        # `claude` on PATH comes before the candidates.
        env = dict(self.env, PATH=self.bindir)
        self.assertEqual(schedule.pick_claude(env, common.validate_settings({}),
                                              candidates=[other]), self.claude)

    def test_install_writes_plist_and_pins_claude(self):
        doppler = write_exec(os.path.join(self.tmp, "dopplerbin", "doppler"), "#!/bin/sh\nexit 1\n")
        self.write_settings({"notify": {"slack_channel": "", "token_cmd": [
            "doppler", "secrets", "get", "SLACK_BOT_TOKEN", "--plain"]}})
        self.git(self.root, "commit", "-qam", "settings", env={"GIT_AUTHOR_NAME": "t",
                 "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.env["PATH"] = os.path.dirname(doppler) + ":/usr/bin:/bin"
        info = self.install(no_load=True)
        self.assertEqual(self.launchctl_calls(), [])
        self.assertFalse(info["loaded"])
        path = os.path.join(self.agents, "io.github.local.wiki-absorb.plist")
        self.assertEqual(info["plist_path"], path)
        with open(path, "rb") as handle:
            plist = plistlib.load(handle)
        self.assertEqual(plist["Label"], "io.github.local.wiki-absorb")
        self.assertEqual(plist["StartInterval"], 1800)
        self.assertIs(plist["RunAtLoad"], True)
        bin_dir = os.path.join(self.root, ".bin", info["version"])
        self.assertEqual(plist["ProgramArguments"],
                         ["/usr/bin/python3", os.path.join(bin_dir, "wiki.py"), "--root", self.root,
                          "absorb", "--scheduled"])
        self.assertTrue(os.path.isfile(os.path.join(bin_dir, "wiki.py")))
        env = plist["EnvironmentVariables"]
        self.assertEqual(sorted(env), ["HOME", "LLM_WIKI_HOOK", "PATH", "TZ", "USER", "WIKI_ROOT"])
        self.assertEqual(env["LLM_WIKI_HOOK"], "0")
        self.assertEqual(env["WIKI_ROOT"], self.root)
        self.assertEqual(env["HOME"], self.home)
        self.assertEqual(env["TZ"], "Asia/Seoul")
        dirs = env["PATH"].split(":")
        self.assertEqual(dirs[0], self.bindir)
        self.assertIn(os.path.dirname(doppler), dirs)
        self.assertIn("/usr/bin", dirs)
        log = os.path.join(self.root, ".state", "launchd.log")
        self.assertEqual(plist["StandardOutPath"], log)
        self.assertEqual(plist["StandardErrorPath"], log)
        settings = common.load_settings(self.root)
        self.assertEqual(settings["claude_path"], self.claude)
        self.assertEqual(settings["notify"]["token_cmd"][0], "doppler")
        status = self.git(self.root, "status", "--porcelain", "settings.json").stdout
        self.assertEqual(status, b"")
        message = self.git(self.root, "log", "-1", "--format=%s").stdout.decode().strip()
        self.assertEqual(message, "wiki: schedule claude_path")
        # Installing again changes nothing in git.
        head = self.git(self.root, "rev-parse", "HEAD").stdout
        again = self.install(no_load=True)
        self.assertFalse(again["claude_pinned"])
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD").stdout, head)

    def test_install_and_uninstall_call_launchctl(self):
        info = self.install(rules_path=os.path.join(self.tmp, "rules", "wiki-prefs.md"))
        self.assertTrue(info["loaded"])
        label = "io.github.local.wiki-absorb"
        self.assertEqual(self.launchctl_calls(), [
            ["bootout", "gui/501/" + label], ["bootstrap", "gui/501", info["plist_path"]]])
        with open(info["plist_path"], "rb") as handle:
            args = plistlib.load(handle)["ProgramArguments"]
        self.assertEqual(args[-2:], ["--rules-path", os.path.join(self.tmp, "rules",
                                                                  "wiki-prefs.md")])
        result = schedule.uninstall(self.root, self.env, agents_dir=self.agents,
                                    launchctl=self.launchctl, uid=501)
        self.assertTrue(result["removed"])
        self.assertFalse(os.path.exists(info["plist_path"]))
        self.assertEqual(self.launchctl_calls()[-1], ["bootout", "gui/501/" + label])
        # Nothing installed: launchctl is not called again.
        count = len(self.launchctl_calls())
        result = schedule.uninstall(self.root, self.env, agents_dir=self.agents,
                                    launchctl=self.launchctl, uid=501)
        self.assertFalse(result["removed"])
        self.assertEqual(len(self.launchctl_calls()), count)

    def test_old_versions_pruned_only_after_load(self):
        old = os.path.join(self.root, ".bin", "0.0.1-deadbeef")
        os.makedirs(old)
        info = self.install(no_load=True)
        self.assertTrue(os.path.isdir(old))
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".bin", info["version"])))
        failing = self.fake_launchctl(5, name="launchctl-fail")
        with self.assertRaises(common.WikiError):
            self.install(launchctl=failing)
        self.assertTrue(os.path.isdir(old))
        self.install()
        self.assertFalse(os.path.exists(old))
        self.assertEqual(os.listdir(os.path.join(self.root, ".bin")), [info["version"]])

    def test_launchctl_failure_is_a_reason_code(self):
        failing = self.fake_launchctl(5, name="launchctl-fail")
        with self.assertRaises(common.WikiError) as ctx:
            self.install(launchctl=failing)
        self.assertEqual(ctx.exception.reason, "launchctl_failed")

    def test_install_refuses_while_absorb_runs(self):
        with common.wiki_lock(self.root):
            with self.assertRaises(common.LockBusy):
                self.install(no_load=True)
        self.assertFalse(os.path.exists(self.agents))

    def test_install_refuses_claude_without_flags(self):
        old = self.fake_claude("claude-old", OLD_HELP)
        with self.assertRaises(common.WikiError) as ctx:
            self.install(claude=old, no_load=True)
        self.assertEqual(ctx.exception.reason, "claude_flags_missing")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".bin")))
        self.assertFalse(os.path.exists(self.agents))

    def test_print_writes_nothing(self):
        with open(os.path.join(self.root, "settings.json"), "rb") as handle:
            before = handle.read()
        env = dict(self.env, WIKI_LAUNCH_AGENTS_DIR=self.agents)
        info = schedule.print_plist(self.root, env, claude=self.claude)
        self.assertIn("io.github.local.wiki-absorb", info["xml"])
        self.assertIn("<integer>1800</integer>", info["xml"])
        self.assertEqual(plistlib.loads(info["xml"].encode())["Label"], info["label"])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".bin")))
        self.assertFalse(os.path.exists(self.agents))
        with open(os.path.join(self.root, "settings.json"), "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_installed_info_reports_stale_copy(self):
        info = self.install(no_load=True)
        status = schedule.installed_info(self.root, self.env, agents_dir=self.agents)
        self.assertTrue(status["installed"])
        self.assertFalse(status["bin_stale"])
        self.assertEqual(status["bin_version"], info["version"])
        manifest = os.path.join(self.root, ".bin", info["version"], "BIN.json")
        with open(manifest) as handle:
            data = json.load(handle)
        data["version"] = "0.0.0-00000000"
        with open(manifest, "w") as handle:
            json.dump(data, handle)
        status = schedule.installed_info(self.root, self.env, agents_dir=self.agents)
        self.assertTrue(status["bin_stale"])

    def test_cli(self):
        env = {"WIKI_LAUNCH_AGENTS_DIR": self.agents, "WIKI_LAUNCHCTL": self.launchctl}
        proc = self.run_cli("schedule", "--print", "--claude", self.claude, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertIn(b"<key>StartInterval</key>", proc.stdout)
        proc = self.run_cli("--json", "schedule", "--install", "--no-load", "--claude",
                            self.claude, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        data = json.loads(proc.stdout.decode())
        self.assertTrue(os.path.isfile(data["plist_path"]))
        self.assertEqual(self.launchctl_calls(), [])
        proc = self.run_cli("--json", "status", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        status = json.loads(proc.stdout.decode())
        self.assertTrue(status["schedule"]["installed"])
        self.assertFalse(status["schedule"]["bin_stale"])
        proc = self.run_cli("--json", "schedule", "uninstall", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertTrue(json.loads(proc.stdout.decode())["removed"])
        self.assertEqual(self.launchctl_calls()[0][0], "bootout")
        proc = self.run_cli("--json", "schedule", env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "usage")
        proc = self.run_cli("schedule", "install", "--print", env=env)
        self.assertEqual(proc.returncode, 1)


class LedgerTest(ScheduleCase):
    def entry(self, epoch, status="ok"):
        return schedule.make_entry({"status": status, "run_id": "r"}, epoch, epoch + 60, True)

    def settings(self, hours=20):
        return common.validate_settings({"schedule": {"min_hours_between_runs": hours}})

    def test_first_run_is_due(self):
        self.assertEqual(schedule.due_check(self.root, self.settings(), time.time()),
                         (True, "first_run"))

    def test_twenty_hour_and_once_a_day(self):
        schedule.record_run(self.root, self.entry(local_epoch(2026, 11, 6, 1, 0)))
        now = local_epoch(2026, 11, 6, 23, 0)
        self.assertEqual(schedule.due_check(self.root, self.settings(), now), (False, "ran_today"))
        self.assertEqual(schedule.due_check(self.root, self.settings(0), now),
                         (False, "ran_today"))
        later = local_epoch(2026, 11, 7, 0, 30)
        self.assertEqual(schedule.due_check(self.root, self.settings(), later), (True, "due"))

        schedule.record_run(self.root, self.entry(local_epoch(2026, 11, 7, 23, 30)))
        self.assertEqual(schedule.due_check(self.root, self.settings(),
                                            local_epoch(2026, 11, 8, 10, 0)), (False, "too_soon"))
        self.assertEqual(schedule.due_check(self.root, self.settings(),
                                            local_epoch(2026, 11, 8, 19, 30)), (True, "due"))
        self.assertEqual(schedule.due_check(self.root, self.settings(0),
                                            local_epoch(2026, 11, 8, 0, 1)), (True, "due"))
        nxt = schedule.next_due_epoch(self.root, self.settings())
        self.assertEqual(nxt, local_epoch(2026, 11, 8, 19, 30))

    def test_failed_runs_count(self):
        schedule.record_run(self.root, self.entry(local_epoch(2026, 11, 6, 2, 0), "failed"))
        self.assertEqual(schedule.due_check(self.root, self.settings(),
                                            local_epoch(2026, 11, 6, 2, 30)),
                         (False, "ran_today"))

    def test_clock_going_backwards_is_not_due(self):
        schedule.record_run(self.root, self.entry(local_epoch(2026, 11, 9, 2, 0)))
        self.assertEqual(schedule.due_check(self.root, self.settings(),
                                            local_epoch(2026, 11, 8, 2, 0)), (False, "too_soon"))

    def test_falls_back_to_last_absorb(self):
        moment = datetime.datetime(2026, 11, 6, 1, 0).astimezone().replace(microsecond=0)
        with open(os.path.join(self.root, ".state", "last-absorb"), "w") as handle:
            json.dump({"finished_at": moment.isoformat(), "status": "ok"}, handle)
        self.assertEqual(schedule.due_check(self.root, self.settings(),
                                            local_epoch(2026, 11, 6, 12, 0)),
                         (False, "ran_today"))

    def test_ledger_is_capped_and_private(self):
        for i in range(schedule.LEDGER_MAX + 5):
            schedule.record_run(self.root, self.entry(1000.0 + i))
        runs = schedule.read_ledger(self.root)["runs"]
        self.assertEqual(len(runs), schedule.LEDGER_MAX)
        self.assertEqual(runs[-1]["started_epoch"], 1000.0 + schedule.LEDGER_MAX + 4)
        mode = os.stat(schedule.ledger_path(self.root)).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_corrupt_ledger_reads_empty(self):
        with open(schedule.ledger_path(self.root), "w") as handle:
            handle.write("{not json")
        self.assertEqual(schedule.read_ledger(self.root), {"runs": []})


class RunAbsorbTest(ScheduleCase):
    def setUp(self):
        ScheduleCase.setUp(self)
        self.calls = []
        self.notified = []
        self.now = [local_epoch(2026, 11, 6, 9, 0)]

    def clock(self):
        return self.now[0]

    def fake_absorb(self, result=None, error=None):
        def run(root, environ, rules_path=None, scheduled=False):
            self.calls.append({"scheduled": scheduled, "rules_path": rules_path})
            if error is not None:
                raise error
            return dict(result or {"ok": True, "status": "ok", "run_id": "2026-11-06T0900",
                                   "applied": 2, "new_pages": 1, "quarantined": 0,
                                   "batches": [], "warnings": [], "summary_line": "위키: ..."})
        return run

    def fake_notify(self, root, report, environ):
        # The ledger already holds this run when the line goes out.
        runs = schedule.read_ledger(root)["runs"]
        self.notified.append((report["status"], len(runs)))
        return {"state": "success", "text": "위키: x", "mode": "log_only", "sent": False,
                "reason": "not_configured"}

    def run_absorb(self, scheduled=True, **kwargs):
        kwargs.setdefault("absorb_fn", self.fake_absorb())
        kwargs.setdefault("notify_fn", self.fake_notify)
        return schedule.run_absorb(self.root, self.env, scheduled=scheduled, clock=self.clock,
                                   **kwargs)

    def test_scheduled_run_records_then_notifies(self):
        report = self.run_absorb()
        self.assertEqual(self.calls, [{"scheduled": True, "rules_path": None}])
        self.assertEqual(self.notified, [("ok", 1)])
        runs = schedule.read_ledger(self.root)["runs"]
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0]["scheduled"])
        self.assertEqual(runs[0]["counts"]["applied"], 2)
        self.assertEqual(runs[0]["notify"]["reason"], "not_configured")
        self.assertEqual(report["notify"]["mode"], "log_only")
        # The next tick the same day is a silent skip.
        self.now[0] += 1800
        self.assertIsNone(self.run_absorb())
        self.assertEqual(len(self.calls), 1)
        # 20 hours later on the next day it runs again.
        self.now[0] = local_epoch(2026, 11, 7, 5, 0)
        self.assertIsNotNone(self.run_absorb())
        self.assertEqual(len(self.calls), 2)

    def test_manual_run_counts_for_the_day(self):
        self.run_absorb(scheduled=False)
        self.now[0] += 3600
        self.assertIsNone(self.run_absorb())
        self.assertEqual(self.calls, [{"scheduled": False, "rules_path": None}])

    def test_lock_busy(self):
        self.assertIsNone(self.run_absorb(absorb_fn=self.fake_absorb(error=common.LockBusy())))
        self.assertEqual(schedule.read_ledger(self.root)["runs"], [])
        self.assertEqual(self.notified, [])
        with self.assertRaises(common.LockBusy):
            self.run_absorb(scheduled=False, absorb_fn=self.fake_absorb(error=common.LockBusy()))

    def test_crash_is_recorded_once_a_day(self):
        boom = self.fake_absorb(error=RuntimeError("boom"))
        import io
        saved, sys.stderr = sys.stderr, io.StringIO()
        try:
            report = self.run_absorb(absorb_fn=boom)
        finally:
            sys.stderr = saved
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["reason"], "internal_error")
        self.assertEqual(self.notified, [("failed", 1)])
        self.now[0] += 1800
        self.assertIsNone(self.run_absorb(absorb_fn=boom))
        self.assertEqual(len(self.calls), 1)

    def test_wiki_error_becomes_failed_report(self):
        report = self.run_absorb(absorb_fn=self.fake_absorb(
            error=common.WikiError("settings_invalid", "bad")))
        self.assertEqual((report["status"], report["reason"]), ("failed", "settings_invalid"))
        self.assertEqual(schedule.read_ledger(self.root)["runs"][0]["reason"], "settings_invalid")

    def test_no_notify_and_notify_crash(self):
        self.run_absorb(scheduled=False, send=False)
        self.assertEqual(self.notified, [])
        self.assertIsNone(schedule.read_ledger(self.root)["runs"][0]["notify"])

        def broken(root, report, environ):
            raise RuntimeError("x")

        report = self.run_absorb(scheduled=False, notify_fn=broken)
        self.assertTrue(report["ok"])
        self.assertEqual(report["notify"]["reason"], "notify_internal_error")
        self.assertEqual(len(schedule.read_ledger(self.root)["runs"]), 2)

    def test_scheduled_without_wiki_is_silent(self):
        missing = os.path.join(self.tmp, "nowiki")
        report = schedule.run_absorb(missing, self.env, scheduled=True,
                                     absorb_fn=self.fake_absorb(), notify_fn=self.fake_notify)
        self.assertIsNone(report)
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(missing))

    def test_real_absorb_empty_run_through_cli(self):
        with open(os.path.join(self.root, "domains.json"), "w", encoding="utf-8") as handle:
            json.dump({"owners": {"SomeOrg": "work", "someuser": "personal"},
                       "work_terms": ["acmecorp"]}, handle)
        proc = self.run_cli("--json", "absorb", "--scheduled")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        report = json.loads(proc.stdout.decode())
        self.assertEqual(report["status"], "empty")
        self.assertEqual(report["notify"]["text"], "위키: 반영 0 · 격리 0")
        self.assertEqual(report["notify"]["mode"], "log_only")
        proc = self.run_cli("--json", "absorb", "--scheduled")
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(json.loads(proc.stdout.decode())["skipped"])
        self.assertEqual(len(schedule.read_ledger(self.root)["runs"]), 1)


if __name__ == "__main__":
    unittest.main()
