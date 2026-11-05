"""Session hooks: hooks.json, session_context.py, prompt_nudge.py (T4).

Everything runs against a temp HOME/WIKI_ROOT with synthetic caches and
throwaway git repos. The real ~/wiki and ~/.claude are never read.
"""

import io
import json
import os
import shutil
import subprocess
import time
import unicodedata
import unittest
from unittest import mock

import _helpers
import hooklib
import prompt_nudge
import session_context

HOOKS_JSON = os.path.join(_helpers.REPO_ROOT, "hooks", "hooks.json")
SYSTEM_PYTHON = "/usr/bin/python3"

PERSONAL_OWNER = "SomeUser"
WORK_OWNER = "Example-Corp"
WORK_MARK = "WORKONLY"  # must never reach a personal session


def personal_url(repo):
    return "git@github.com:%s/%s.git" % (PERSONAL_OWNER, repo)


def work_url(repo):
    return "https://github.com/%s/%s" % (WORK_OWNER, repo)


def make_context_cache(**overrides):
    cache = {
        "version": 1,
        "generated_at": "2026-01-02T02:15:00+09:00",
        "as_of": "2026-01-02 02:15",
        "run_id": "2026-01-02T0215",
        "owners": {PERSONAL_OWNER: "personal", WORK_OWNER: "work"},
        "domains": {
            "personal": {
                "projects": [
                    {"title": "radar-app", "page": "personal/projects/radar-app.md",
                     "repos": ["someuser/Radar-App"], "status": "active",
                     "summary": "line one\nline two\nline three", "this_week": "ship the hooks"},
                    {"title": "side-tool", "page": "personal/projects/side-tool.md",
                     "repos": ["github.com/SomeUser/side-tool.git"], "summary": "other summary"},
                    {"title": "leaky", "page": "work/projects/leaky.md", "repos": []},
                    {"title": "escape", "page": "personal/../work/x.md", "repos": []},
                ],
                "prefs": [
                    {"title": "p1", "page": "personal/prefs/p1.md", "scope": "domain",
                     "text": "decide first, then report"},
                    {"title": "p2", "page": "personal/prefs/p2.md", "scope": "repo",
                     "repos": ["SomeUser/radar-app"], "text": "run the radar tests"},
                    {"title": "p3", "page": "personal/prefs/p3.md", "scope": "repo",
                     "repos": ["SomeUser/elsewhere"], "text": "unrelated repo rule"},
                    {"title": "p4", "page": "personal/prefs/p4.md", "scope": "global",
                     "text": "global rule goes to rules only"},
                ],
            },
            "work": {
                "projects": [
                    {"title": WORK_MARK + "-proj", "page": "work/projects/w.md",
                     "repos": [WORK_OWNER + "/svc"], "summary": WORK_MARK + " summary"},
                ],
                "prefs": [{"title": "w", "page": "work/prefs/w.md", "scope": "domain",
                           "text": WORK_MARK + " pref"}],
            },
        },
        "pending": {
            "updated_at": "2026-01-02T12:00:00+09:00",
            "unresolved": 1,
            "domains": {"personal": {"count": 2, "titles": ["mem radar note"]},
                        "work": {"count": 5, "titles": [WORK_MARK + " title"]}},
        },
    }
    cache.update(overrides)
    return cache


def make_alias_cache():
    return {
        "version": 1,
        "generated_at": "2026-01-02T02:15:00+09:00",
        "domains": {
            "personal": [
                {"page": "personal/projects/radar-app.md", "title": "radar-app",
                 "aliases": [u"레이더앱", "Radar"]},
                {"page": "personal/projects/side-tool.md", "title": "side-tool",
                 "aliases": [u"위키", "ab", u"사이드툴"]},
                {"page": "personal/topics/gamma.md", "title": "gamma"},
                {"page": "personal/topics/delta.md", "title": "delta"},
                {"page": "work/projects/w.md", "title": "smuggled"},
            ],
            "work": [{"page": "work/projects/w.md", "title": WORK_MARK.lower()}],
        },
    }


class HookCase(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        os.makedirs(os.path.join(self.root, ".state"))
        self.config_dir = os.path.join(self.home, ".claude")
        os.makedirs(os.path.join(self.config_dir, "projects", "p"))
        self.transcript = os.path.join(self.config_dir, "projects", "p", "s.jsonl")
        self.environ = {"HOME": self.home, "WIKI_ROOT": self.root, "CLAUDECODE": "1",
                        "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        patcher = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                               "GIT_CONFIG_NOSYSTEM": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write_cache("context-cache.json", make_context_cache())
        self.write_cache("alias-cache.json", make_alias_cache())

    def write_cache(self, name, data):
        path = os.path.join(self.root, ".state", name)
        with open(path, "w", encoding="utf-8") as handle:
            if isinstance(data, str):
                handle.write(data)
            else:
                json.dump(data, handle, ensure_ascii=False)

    def make_repo(self, name, *urls):
        repo = os.path.join(self.tmp, "repos", name)
        os.makedirs(repo)
        self.git(repo, "init", "-q")
        for index, url in enumerate(urls):
            self.git(repo, "remote", "add", "r%d" % index, url)
        return repo

    def payload(self, cwd, event="SessionStart", **extra):
        data = {"session_id": "s", "transcript_path": self.transcript, "cwd": cwd,
                "hook_event_name": event}
        data.update(extra)
        return data

    def context(self, cwd, event="SessionStart", environ=None, **extra):
        return session_context.build_context(event, self.payload(cwd, event, **extra),
                                             environ or self.environ)

    def nudge(self, cwd, prompt, environ=None):
        payload = self.payload(cwd, "UserPromptSubmit", prompt=prompt)
        return prompt_nudge.build_nudge("UserPromptSubmit", payload, environ or self.environ)


class HooksJsonTest(unittest.TestCase):
    def setUp(self):
        with open(HOOKS_JSON, encoding="utf-8") as handle:
            self.data = json.load(handle)

    def test_events_matchers_and_commands(self):
        hooks = self.data["hooks"]
        self.assertEqual(sorted(hooks), ["SessionStart", "SubagentStart", "UserPromptSubmit"])
        self.assertEqual(hooks["SessionStart"][0]["matcher"], "startup|clear|compact|resume")
        self.assertNotIn("matcher", hooks["SubagentStart"][0])
        self.assertNotIn("matcher", hooks["UserPromptSubmit"][0])
        scripts = {"SessionStart": "session_context.py", "SubagentStart": "session_context.py",
                   "UserPromptSubmit": "prompt_nudge.py"}
        for event, groups in hooks.items():
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0]["hooks"]), 1)
            hook = groups[0]["hooks"][0]
            self.assertEqual(hook["type"], "command")
            self.assertEqual(hook["timeout"], 5)
            command = hook["command"]
            self.assertTrue(command.startswith('[ -d "${WIKI_ROOT:-$HOME/wiki}" ] || exit 0;'))
            self.assertIn('[ "${LLM_WIKI_HOOK:-1}" = 0 ] && exit 0;', command)
            self.assertIn('/usr/bin/python3 "${CLAUDE_PLUGIN_ROOT}/skills/wiki/scripts/%s"'
                          % scripts[event], command)
            self.assertIn("--event %s" % event, command)
            self.assertTrue(command.endswith("2>/dev/null || exit 0"))
            self.assertTrue(os.path.isfile(os.path.join(_helpers.SCRIPTS_DIR, scripts[event])))


class SignalTest(HookCase):
    def test_requires_claudecode_and_transcript_in_config_dir(self):
        payload = self.payload("/x")
        self.assertTrue(hooklib.is_claude_session(payload, self.environ))
        no_flag = dict(self.environ)
        del no_flag["CLAUDECODE"]
        self.assertFalse(hooklib.is_claude_session(payload, no_flag))
        self.assertFalse(hooklib.is_claude_session(payload, dict(self.environ, CLAUDECODE="0")))
        codex_like = dict(payload, transcript_path=os.path.join(self.home, ".codex", "s", "t.jsonl"))
        self.assertFalse(hooklib.is_claude_session(codex_like, self.environ))
        self.assertFalse(hooklib.is_claude_session(dict(payload, transcript_path=None), self.environ))
        self.assertFalse(hooklib.is_claude_session(dict(payload, transcript_path="rel/t.jsonl"),
                                                   self.environ))
        sneaky = os.path.join(self.config_dir, "..", ".codex", "t.jsonl")
        self.assertFalse(hooklib.is_claude_session(dict(payload, transcript_path=sneaky),
                                                   self.environ))

    def test_respects_claude_config_dir(self):
        other = os.path.join(self.tmp, "cfg")
        os.makedirs(os.path.join(other, "projects"))
        environ = dict(self.environ, CLAUDE_CONFIG_DIR=other)
        inside = dict(self.payload("/x"), transcript_path=os.path.join(other, "projects", "t.jsonl"))
        self.assertTrue(hooklib.is_claude_session(inside, environ))
        self.assertFalse(hooklib.is_claude_session(self.payload("/x"), environ))

    def test_no_signal_means_no_output(self):
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        environ = dict(self.environ)
        del environ["CLAUDECODE"]
        self.assertIsNone(self.context(repo, environ=environ))
        self.assertIsNone(self.nudge(repo, "radar-app", environ=environ))


class SessionContextTest(HookCase):
    def test_personal_repo_context(self):
        repo = self.make_repo("radar-app", personal_url("Radar-App"))
        text = self.context(repo)
        self.assertTrue(text.startswith("wiki as of 2026-01-02 02:15 · domain: personal"))
        self.assertIn("radar-app — ~/wiki/personal/projects/radar-app.md", text)
        self.assertIn("line one\nline two\nline three", text)
        self.assertIn("이번 주: ship the hooks", text)
        self.assertIn("- run the radar tests", text)
        self.assertIn("- decide first, then report", text)
        self.assertLess(text.index("run the radar tests"), text.index("decide first"))
        self.assertNotIn("unrelated repo rule", text)
        self.assertNotIn("global rule", text)
        self.assertIn("같은 도메인 다른 프로젝트: side-tool", text)
        self.assertNotIn("other summary", text)
        self.assertNotIn("leaky", text)
        self.assertNotIn("escape", text)
        self.assertIn("지난 absorb에서 반영되지 못한 원본 3건 (판정 안 된 것 1건): mem radar note", text)
        self.assertNotIn(WORK_MARK, text)

    def test_work_wins_when_any_remote_is_work(self):
        repo = self.make_repo("svc", personal_url("svc"), work_url("svc"))
        text = self.context(repo)
        self.assertIn("domain: work", text)
        self.assertIn(WORK_MARK + " summary", text)
        self.assertIn(WORK_MARK + " pref", text)
        self.assertNotIn("radar-app", text)
        self.assertNotIn("decide first", text)
        self.assertIn("반영되지 못한 원본 6건 (판정 안 된 것 1건)", text)

    def test_repo_without_project_page_still_gets_domain_context(self):
        repo = self.make_repo("new-thing", personal_url("new-thing"))
        text = self.context(repo)
        self.assertIn("domain: personal", text)
        self.assertIn("같은 도메인 다른 프로젝트: radar-app, side-tool", text)
        self.assertNotIn("line one", text)

    def test_undetermined_sessions_are_silent(self):
        cases = {
            "no_git": os.path.join(self.tmp, "plain"),
            "no_remote": self.make_repo("bare-repo"),
            "unlisted_owner": self.make_repo("mixed", personal_url("mixed"),
                                             "git@github.com:Stranger/mixed.git"),
            "local_remote": self.make_repo("local", "/srv/git/local.git"),
        }
        os.makedirs(cases["no_git"])
        for name, cwd in cases.items():
            self.assertIsNone(self.context(cwd), name)
            self.assertIsNone(self.nudge(cwd, "radar-app"), name)

    def test_home_and_epic_folders_are_silent_even_with_remotes(self):
        self.git(self.home, "init", "-q")
        self.git(self.home, "remote", "add", "origin", personal_url("dotfiles"))
        self.assertIsNone(self.context(self.home))
        epic = os.path.join(self.home, ".traycer", "epics", "abc")
        os.makedirs(epic)
        self.assertIsNone(self.context(epic))
        self.assertIsNone(self.nudge(epic, "radar-app"))

    def test_disabled_missing_or_bad_cache_is_silent(self):
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        self.assertIsNotNone(self.context(repo))
        self.assertIsNone(self.context(repo, environ=dict(self.environ, LLM_WIKI_HOOK="0")))
        self.assertIsNone(self.context(repo, environ=dict(self.environ, WIKI_ROOT=self.tmp + "/nope")))
        for bad in ("{not json", json.dumps(make_context_cache(version=2)),
                    json.dumps(make_context_cache(owners={})), json.dumps([1, 2])):
            self.write_cache("context-cache.json", bad)
            self.assertIsNone(self.context(repo), bad[:20])
        os.remove(os.path.join(self.root, ".state", "context-cache.json"))
        self.assertIsNone(self.context(repo))

    def test_missing_domain_block_is_silent(self):
        cache = make_context_cache()
        del cache["domains"]["personal"]
        self.write_cache("context-cache.json", cache)
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        self.assertIsNone(self.context(repo))

    def test_pending_block_optional(self):
        cache = make_context_cache()
        del cache["pending"]
        self.write_cache("context-cache.json", cache)
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        self.assertNotIn("반영되지 못한 원본", self.context(repo))

    def test_section_and_total_caps(self):
        cache = make_context_cache()
        block = cache["domains"]["personal"]
        block["projects"][0]["summary"] = "S" * 5000
        block["projects"][0]["this_week"] = "W" * 5000
        block["prefs"] = [{"title": "p%d" % i, "page": "personal/prefs/p%d.md" % i,
                           "scope": "domain", "text": "pref %d " % i + "x" * 200}
                          for i in range(100)]
        block["projects"] += [{"title": "proj-%03d" % i, "page": "personal/projects/p%d.md" % i,
                               "repos": []} for i in range(300)]
        cache["pending"]["domains"]["personal"]["titles"] = ["t%03d" % i for i in range(500)]
        self.write_cache("context-cache.json", cache)
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        main = self.context(repo)
        sub = self.context(repo, event="SubagentStart")
        self.assertLessEqual(len(main), 6000)
        self.assertLessEqual(len(sub), 2000)
        self.assertGreater(len(main), 4000)
        for text, caps in ((main, session_context.SECTION_CAPS["SessionStart"]),
                           (sub, session_context.SECTION_CAPS["SubagentStart"])):
            self.assertIn("radar-app — ", text)
            self.assertIn("선호:", text)
            self.assertIn("같은 도메인 다른 프로젝트:", text)
            self.assertIn("반영되지 못한 원본", text)
            prefs = text[text.index("선호:"):text.index("같은 도메인")].rstrip("\n")
            self.assertLessEqual(len(prefs), caps["prefs"])

    def test_control_characters_are_stripped(self):
        cache = make_context_cache()
        cache["domains"]["personal"]["projects"][0]["this_week"] = "a\x1b[31mb\x07c"
        self.write_cache("context-cache.json", cache)
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        self.assertIn("이번 주: a[31mbc", self.context(repo))

    def test_subagent_event_uses_smaller_caps(self):
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        text = self.context(repo, event="SubagentStart")
        self.assertIn("radar-app — ", text)


class PromptNudgeTest(HookCase):
    def setUp(self):
        HookCase.setUp(self)
        self.repo = self.make_repo("radar-app", personal_url("radar-app"))

    def lines(self, prompt):
        text = self.nudge(self.repo, prompt)
        return text.split("\n") if text else []

    def test_korean_substring_with_particle(self):
        self.assertEqual(self.lines(u"레이더앱에서 확인해줘"),
                         [u"관련 위키: ~/wiki/personal/projects/radar-app.md (radar-app)"])

    def test_latin_word_boundary_and_case(self):
        self.assertEqual(len(self.lines("look at RADAR now")), 1)
        self.assertEqual(len(self.lines(u"radar-app에서")), 1)
        self.assertEqual(len(self.lines(u"Radar에서")), 1)
        self.assertEqual(self.lines("radars and deltaforce and xgamma"), [])
        self.assertEqual(self.lines("gamma_ray"), [])
        self.assertEqual(len(self.lines("(gamma)")), 1)

    def test_short_names_are_ignored_including_nfd_hangul(self):
        self.assertEqual(self.lines(u"위키 ab 정리"), [])
        nfd = unicodedata.normalize("NFD", u"위키")
        self.assertGreater(len(nfd), 2)
        alias = make_alias_cache()
        alias["domains"]["personal"][1]["aliases"].append(nfd)
        self.write_cache("alias-cache.json", alias)
        self.assertEqual(self.lines(u"위키 정리"), [])

    def test_nfd_prompt_matches_nfc_alias(self):
        prompt = unicodedata.normalize("NFD", u"사이드툴 고쳐줘")
        self.assertEqual(len(self.lines(prompt)), 1)

    def test_at_most_three_in_order_of_appearance(self):
        lines = self.lines(u"delta, gamma, 사이드툴, radar-app, radar")
        self.assertEqual(len(lines), 3)
        self.assertIn("delta.md", lines[0])
        self.assertIn("gamma.md", lines[1])
        self.assertIn("side-tool.md", lines[2])

    def test_same_page_counted_once(self):
        self.assertEqual(len(self.lines(u"radar-app 레이더앱 radar")), 1)

    def test_other_domain_names_never_surface(self):
        self.assertEqual(self.lines("ask about workonly and smuggled"), [])
        work_repo = self.make_repo("svc", work_url("svc"))
        text = prompt_nudge.build_nudge("UserPromptSubmit", self.payload(
            work_repo, "UserPromptSubmit", prompt="workonly radar-app"), self.environ)
        self.assertEqual(text, u"관련 위키: ~/wiki/work/projects/w.md (%s)" % WORK_MARK.lower())

    def test_name_budget_stops_scanning(self):
        with mock.patch.object(prompt_nudge, "MAX_NAMES", 3):
            self.assertEqual(len(self.lines("radar-app")), 1)
            self.assertEqual(self.lines("side-tool gamma"), [])

    def test_silent_cases(self):
        self.assertEqual(self.lines("nothing relevant here"), [])
        self.assertIsNone(self.nudge(self.repo, ""))
        os.remove(os.path.join(self.root, ".state", "alias-cache.json"))
        self.assertIsNone(self.nudge(self.repo, "radar-app"))


class MainTest(HookCase):
    def run_main(self, module, event, payload, environ=None):
        stdin = io.BytesIO(json.dumps(payload).encode("utf-8"))
        stdout = io.BytesIO()
        fake = mock.Mock()
        fake.buffer = stdout
        with mock.patch("sys.stdout", fake):
            code = module.main(["--event", event], environ or self.environ, stdin)
        return code, stdout.getvalue().decode("ascii")

    def test_output_is_single_json_with_event_name(self):
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        code, out = self.run_main(session_context, "SessionStart", self.payload(repo))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("radar-app", data["hookSpecificOutput"]["additionalContext"])
        code, out = self.run_main(prompt_nudge, "UserPromptSubmit",
                                  self.payload(repo, "UserPromptSubmit", prompt="radar-app"))
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_event_mismatch_and_unknown_event_are_silent(self):
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        self.assertEqual(self.run_main(session_context, "SubagentStart", self.payload(repo)), (0, ""))
        self.assertEqual(self.run_main(session_context, "Stop", self.payload(repo)), (0, ""))
        self.assertEqual(self.run_main(prompt_nudge, "SessionStart", self.payload(repo)), (0, ""))

    def test_failure_mid_build_prints_nothing(self):
        repo = self.make_repo("radar-app", personal_url("radar-app"))
        with mock.patch.object(session_context, "_pending_section", side_effect=RuntimeError("x")):
            self.assertEqual(self.run_main(session_context, "SessionStart", self.payload(repo)),
                             (0, ""))
        with mock.patch.object(hooklib, "hook_output", side_effect=KeyboardInterrupt()):
            self.assertEqual(self.run_main(session_context, "SessionStart", self.payload(repo)),
                             (0, ""))

    def test_bad_stdin_is_silent(self):
        for raw in (b"", b"not json", b"[1]", b"\xff\xfe"):
            stdout = io.BytesIO()
            fake = mock.Mock()
            fake.buffer = stdout
            with mock.patch("sys.stdout", fake):
                self.assertEqual(session_context.main(["--event", "SessionStart"], self.environ,
                                                      io.BytesIO(raw)), 0)
            self.assertEqual(stdout.getvalue(), b"")


@unittest.skipUnless(os.path.exists(SYSTEM_PYTHON), "needs /usr/bin/python3")
@unittest.skipUnless(shutil.which("git"), "needs git")
class HookCommandTest(HookCase):
    """Runs the exact hooks.json command lines through sh -c."""

    def setUp(self):
        HookCase.setUp(self)
        with open(HOOKS_JSON, encoding="utf-8") as handle:
            hooks = json.load(handle)["hooks"]
        self.commands = dict((event, groups[0]["hooks"][0]["command"])
                             for event, groups in hooks.items())
        self.repo = self.make_repo("radar-app", personal_url("radar-app"))

    def sh(self, event, payload, plugin_root=None, **env):
        environ = _helpers.isolated_env(self.home, {"WIKI_ROOT": self.root, "LLM_WIKI_HOOK": "1",
                                                    "CLAUDECODE": "1"})
        environ["CLAUDE_PLUGIN_ROOT"] = plugin_root or _helpers.REPO_ROOT
        environ.update(env)
        environ = dict((k, v) for k, v in environ.items() if v is not None)
        started = time.time()
        proc = subprocess.run(["/bin/sh", "-c", self.commands[event]],
                              input=json.dumps(payload).encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=environ, cwd=self.tmp, timeout=10)
        return proc, time.time() - started

    def test_full_run_outputs_json_quickly(self):
        for event in ("SessionStart", "SubagentStart"):
            proc, elapsed = self.sh(event, self.payload(self.repo, event))
            self.assertEqual(proc.returncode, 0)
            data = json.loads(proc.stdout.decode("ascii"))
            self.assertEqual(data["hookSpecificOutput"]["hookEventName"], event)
            self.assertLess(elapsed, 3.0)
        proc, _ = self.sh("UserPromptSubmit",
                          self.payload(self.repo, "UserPromptSubmit", prompt=u"레이더앱 봐줘"))
        self.assertIn("radar-app.md", json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_default_wiki_root_is_home_wiki(self):
        proc, _ = self.sh("SessionStart", self.payload(self.repo), WIKI_ROOT=None)
        self.assertIn("radar-app", proc.stdout.decode("ascii"))

    def test_guards_skip_python(self):
        fake_root = os.path.join(self.tmp, "fake-plugin")
        scripts = os.path.join(fake_root, "skills", "wiki", "scripts")
        os.makedirs(scripts)
        marker = os.path.join(self.tmp, "python-ran")
        for name in ("session_context.py", "prompt_nudge.py"):
            with open(os.path.join(scripts, name), "w") as handle:
                handle.write("open(%r, 'w').write('x')\n" % marker)
        payload = self.payload(self.repo)
        self.sh("SessionStart", payload, fake_root, WIKI_ROOT=os.path.join(self.tmp, "missing"))
        self.assertFalse(os.path.exists(marker), "python ran without a wiki dir")
        proc, _ = self.sh("SessionStart", payload, fake_root, LLM_WIKI_HOOK="0")
        self.assertFalse(os.path.exists(marker), "python ran with LLM_WIKI_HOOK=0")
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))
        self.sh("SessionStart", payload, fake_root)
        self.assertTrue(os.path.exists(marker), "fake script should run when guards pass")

    def test_failures_exit_zero_without_output(self):
        self.write_cache("context-cache.json", "{broken")
        proc, _ = self.sh("SessionStart", self.payload(self.repo))
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))
        proc, _ = self.sh("SessionStart", self.payload(self.repo),
                          os.path.join(self.tmp, "no-such-plugin"))
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))
        proc, _ = self.sh("SessionStart", self.payload(self.repo), CLAUDECODE=None)
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))


if __name__ == "__main__":
    unittest.main()
