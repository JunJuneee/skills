"""absorb (T3): orchestration with the LLM step mocked, the real runner
against a fake `claude` executable, deferral, rollback, and the cache
contract read back through T4's hook code. Temp dirs and synthetic
fixtures only; owners and work terms are made up."""

import datetime
import json
import os
import re
import stat
import subprocess
import sys
import unittest
from unittest import mock

import _helpers
import absorb
import common
import prepare
import prompt_nudge
import session_context
import verify
import wiki

NOW = datetime.datetime(2026, 11, 6, 12, 0)
LATER = datetime.datetime(2026, 11, 7, 12, 0)
WORK_ORG = "WorkOrg"
ME = "MeUser"
TERM = "AcmeCorp"


def j(*parts):
    return "".join(parts)


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def page_text(title, kind, domain, sections, src=None, extra=None, notes="## 내 메모\n"):
    lines = ["---", "title: %s" % title, "type: %s" % kind, "domain: %s" % domain]
    for key, value in (extra or []):
        lines.append("%s: %s" % (key, value))
    lines += ["updated: 2026-11-06", "---", "# %s" % title, ""]
    for heading, body in sections:
        lines += ["## %s" % heading, "", body]
        if src:
            lines.append("<!-- src: %s @%s -->" % src)
        lines.append("")
    return "\n".join(lines) + notes


def pref_page(title, src, summary="답변은 한국어로 짧게 한다", scope="global", domain="personal"):
    return page_text(title, "pref", domain, [("선호", summary), ("Why", "원본 Why"),
                                               ("How to apply", "원본 How")],
                     src=src, extra=[("scope", scope), ("summary", summary)])


def result(paths=(), mentions=(), merges=(), withdrawn=(), notes="ok"):
    return {"ok": True, "reason": None, "cost": 0.01,
            "structured": {"pages": list(paths), "merges": [list(m) for m in merges],
                           "mentions": [{"name": n, "sources": list(s)} for n, s in mentions],
                           "withdrawn_src": list(withdrawn), "notes": notes}}


class Runner(object):
    """In-process stand-in for the LLM step: calls fn(request) and keeps
    every request for assertions."""

    def __init__(self, fn):
        self.fn = fn
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.fn(request)


def write(path, text):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class AbsorbCase(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        patcher = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                               "GIT_CONFIG_NOSYSTEM": "1",
                                               "GIT_TERMINAL_PROMPT": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)
        wiki.init_wiki(self.root, environ=self.env)
        self.write_domains()
        self.git(self.root, "add", "domains.json")
        self.git(self.root, "-c", "user.email=t@localhost", "-c", "user.name=t", "commit", "-q",
                 "-m", "domains")
        self.src = os.path.join(self.tmp, "src")
        self.projects = os.path.join(self.src, "projects")
        self.handoff = os.path.join(self.src, "handoff")
        self.design = os.path.join(self.src, "design")
        for path in (self.projects, self.handoff, self.design):
            os.makedirs(path)
        self.history = os.path.join(self.src, "history.jsonl")
        self.repo = self.make_repo("side", "git@github.com:%s/side.git" % ME)
        self.work_repo = self.make_repo("job", "git@github.com:%s/job.git" % WORK_ORG)
        self.rules = os.path.join(self.tmp, "rules", "wiki-prefs.md")
        self.wt = os.path.join(self.root, common.WORKTREE_DIRNAME)

    def write_domains(self):
        data = {"owners": {WORK_ORG: "work", ME: "personal"}, "work_terms": [TERM],
                "overrides": {}, "redact_allow": [], "obsidian_plugins_allow": []}
        write(os.path.join(self.root, "domains.json"), json.dumps(data))

    def make_repo(self, name, *urls):
        path = os.path.join(self.tmp, "repos", name)
        os.makedirs(path)
        self.git(path, "init", "-q")
        for index, url in enumerate(urls):
            self.git(path, "remote", "add", "r%d" % index, url)
        return path

    def paths(self):
        return prepare.SourcePaths(self.projects, self.history, self.handoff, self.design, None,
                                   None)

    def add_memory(self, cwd, name, body, kind="feedback"):
        folder = prepare.fs_encode(cwd)
        memdir = os.path.join(self.projects, folder, "memory")
        lines = ["---", "name: %s" % name[:-3], "description: test", "metadata:",
                 "  type: %s" % kind, "  modified: 2026-11-04T03:00:00.000Z", "---", "", body, ""]
        write(os.path.join(memdir, name), "\n".join(lines))
        jsonl = os.path.join(self.projects, folder, "s1.jsonl")
        if not os.path.exists(jsonl):
            write(jsonl, json.dumps({"type": "user", "cwd": cwd}) + "\n")
        return "mem:%s/%s" % (folder, name)

    def run_absorb(self, runner, now=NOW, **kwargs):
        return absorb.absorb(self.root, environ=self.env, paths=self.paths(), now=now,
                             runner=runner, rules_path=self.rules, **kwargs)

    def main_file(self, rel):
        path = os.path.join(self.root, rel)
        return read(path) if os.path.exists(path) else None

    def head(self):
        return self.git(self.root, "rev-parse", "HEAD").stdout.decode().strip()

    def committed(self, rel):
        proc = self.git(self.root, "cat-file", "-e", "HEAD:%s" % rel)
        return proc.returncode == 0

    def entries(self):
        return prepare.load_sources(self.root)["sources"]


def writes_pref(title="답변 언어", drafts=True, extra_files=None, page_fn=None):
    """Runner fn: one personal pref page citing the batch's first source."""
    def fn(request):
        source = request["sources"][0]
        cwd = request["cwd"]
        path = os.path.join(cwd, "prefs", "answer-language.md")
        text = (page_fn or pref_page)(title, (source["id"], source["date"]))
        write(path, text)
        if drafts:
            write(os.path.join(cwd, "_drafts", "now.md"), "- 사이드 프로젝트 마무리\n")
            write(os.path.join(cwd, "_drafts", "about-me.md"),
                  "## 하는 일\n\n- 개인 도구를 만든다\n\n## 일하는 방식\n\n- 직접 정하고 결과만 본다\n")
        for rel, body in (extra_files or {}).items():
            write(os.path.join(cwd, rel), body)
        return result([path], mentions=[("Side Tool", [source["id"]])])
    return fn


class HappyPathTest(AbsorbCase):
    def test_personal_batch_merges_and_generates_everything(self):
        src_id = self.add_memory(self.repo, "feedback_lang.md",
                                 "답변은 한국어로.\n\n**Why:** 읽기 쉬움\n\n**How to apply:** 항상")
        seen = {}

        def fn(request):
            staging = request["staging_dir"]
            seen["staging_mode"] = mode(staging)
            with self.assertRaises(OSError):
                write(os.path.join(staging, "evil.md"), "x")
            seen["prompt"] = request["prompt"]
            return writes_pref()(request)

        runner = Runner(fn)
        report = self.run_absorb(runner)
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(report["applied"], 1)
        self.assertEqual(report["new_pages"], 1)
        self.assertEqual((report["rules_added"], report["rules_removed"]), (1, 0))
        self.assertEqual(report["summary_line"],
                         "위키: 반영 1 · 새 페이지 1 · 격리 0 · 전역 선호 +1/−0")

        request = runner.requests[0]
        self.assertEqual(request["cwd"], os.path.join(self.wt, "personal"))
        self.assertEqual(request["allowed_globs"], ["personal/**"])
        self.assertEqual(seen["staging_mode"], 0o555)
        self.assertTrue(seen["prompt"].startswith("# 안전 규칙"))
        self.assertIn(src_id, seen["prompt"])
        self.assertNotIn("{{", seen["prompt"])
        self.assertIn("## memory를 페이지로 옮기는 규칙", seen["prompt"])  # SCHEMA inlined
        self.assertNotIn("답변은 한국어로.", seen["prompt"])  # source body is not inlined

        self.assertTrue(self.committed("personal/prefs/answer-language.md"))
        self.assertFalse(self.committed("personal/_drafts/now.md"))
        status = self.git(self.root, "status", "--porcelain").stdout.decode()
        self.assertEqual(status, "")
        now_md = self.main_file("now.md")
        self.assertIn("## personal\n\n- 사이드 프로젝트 마무리\n", now_md)
        template_now = read(os.path.join(_helpers.TEMPLATES_DIR, "root", "now.md"))
        self.assertEqual(verify.notes_tail(now_md), verify.notes_tail(template_now))
        about = self.main_file("about-me.md")
        self.assertIn("## 하는 일\n\n### personal\n\n- 개인 도구를 만든다", about)
        self.assertIn("[[personal/prefs/answer-language|답변 언어]]", self.main_file("index.md"))
        self.assertIn("- %s · 반영 대기 1 · 묶음 1/1" % report["run_id"], self.main_file("log.md"))

        state = common.state_dir(self.root)
        context = json.loads(read(os.path.join(state, "context-cache.json")))
        self.assertEqual(context["version"], 1)
        self.assertEqual(context["owners"], {WORK_ORG: "work", ME: "personal"})
        self.assertEqual(context["domains"]["personal"]["prefs"], [])  # global goes to rules only
        self.assertEqual(mode(os.path.join(state, "context-cache.json")), 0o600)
        aliases = json.loads(read(os.path.join(state, "alias-cache.json")))
        self.assertEqual(aliases["domains"]["personal"][0]["page"],
                         "personal/prefs/answer-language.md")
        self.assertIn("- 답변은 한국어로 짧게 한다", read(self.rules))

        entry = self.entries()[src_id]
        self.assertEqual(entry["status"], "active")
        self.assertTrue(os.path.isfile(os.path.join(state, entry["snapshot"])))
        mentions = prepare.load_sources(self.root)["mentions"]["personal"]
        self.assertEqual(mentions["Side Tool"], [src_id])
        self.assertEqual(mode(common.staging_dir(self.root)), 0o700)
        self.assertFalse(os.path.exists(self.wt))
        last = json.loads(read(os.path.join(state, "last-absorb")))
        self.assertEqual(last["status"], "ok")

        again = Runner(writes_pref())
        report2 = self.run_absorb(again, now=LATER)
        self.assertEqual(report2["status"], "empty")
        self.assertEqual(again.requests, [])
        self.assertIn("간격 24.0h", self.main_file("log.md"))

    def test_cache_contract_through_hook_code(self):
        src_id = self.add_memory(self.repo, "project_side.md", "사이드 도구 진행 중", kind="project")

        def fn(request):
            source = request["sources"][0]
            cwd = request["cwd"]
            text = page_text("Side Tool", "project", "personal",
                             [("이번 주 무엇을 왜", "- 배포 준비"), ("현재 상태", "- 베타")],
                             src=(source["id"], source["date"]),
                             extra=[("aliases", "[사이드 도구]"), ("repos", "[%s/side]" % ME),
                                    ("status", "active"), ("summary", "개인 도구")])
            path = os.path.join(cwd, "projects", "side-tool.md")
            write(path, text)
            return result([path])

        report = self.run_absorb(Runner(fn))
        self.assertEqual(report["status"], "ok", report)
        config = os.path.join(self.home, ".claude")
        transcript = os.path.join(config, "projects", "p", "s.jsonl")
        write(transcript, "")
        environ = {"HOME": self.home, "WIKI_ROOT": self.root, "CLAUDECODE": "1",
                   "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        payload = {"session_id": "s", "transcript_path": transcript, "cwd": self.repo,
                   "hook_event_name": "SessionStart"}
        text = session_context.build_context("SessionStart", payload, environ)
        self.assertIsNotNone(text)
        self.assertIn("domain: personal", text)
        self.assertIn("Side Tool", text)
        self.assertIn("이번 주: 배포 준비", text)
        nudge_payload = dict(payload, hook_event_name="UserPromptSubmit",
                             prompt="사이드 도구를 어떻게 배포하지?")
        nudge = prompt_nudge.build_nudge("UserPromptSubmit", nudge_payload, environ)
        self.assertIn("personal/projects/side-tool.md", nudge)
        work_payload = dict(payload, cwd=self.work_repo)
        work_text = session_context.build_context("SessionStart", work_payload, environ) or ""
        self.assertNotIn("Side Tool", work_text)
        self.assertEqual(self.entries()[src_id]["status"], "active")


class FailureTest(AbsorbCase):
    def setUp(self):
        AbsorbCase.setUp(self)
        self.src_id = self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        # An unrelated, uncommitted Obsidian-style edit in main that must survive.
        schema = os.path.join(self.root, "SCHEMA.md")
        self.schema_dirty = read(schema) + "\n사람이 고친 줄\n"
        write(schema, self.schema_dirty)

    def assert_not_applied(self, report, reason):
        self.assertEqual(report["status"], "failed", report)
        self.assertEqual(report["batches"][0]["reason"], reason, report["batches"][0])
        self.assertFalse(self.committed("personal/prefs/answer-language.md"))
        self.assertNotIn(self.src_id, self.entries())
        self.assertEqual(self.main_file("SCHEMA.md"), self.schema_dirty)

    def test_write_outside_allowed_globs(self):
        for extra in ({"../index.md": "x"}, {"../work/notes/x.md": "x"}, {"../settings.json": "{}"}):
            report = self.run_absorb(Runner(writes_pref(extra_files=extra)))
            self.assert_not_applied(report, "outside_allowed_globs")
            self.assertFalse(self.committed("work/notes/x.md"))

    def test_failed_batch_is_offered_again(self):
        self.run_absorb(Runner(writes_pref(extra_files={"../index.md": "x"})))
        report = self.run_absorb(Runner(writes_pref()), now=LATER)
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(self.entries()[self.src_id]["status"], "active")
        self.assertEqual(self.main_file("SCHEMA.md"), self.schema_dirty)

    def test_symlink_is_rejected(self):
        def fn(request):
            os.symlink(os.path.join(self.root, "domains.json"),
                       os.path.join(request["cwd"], "notes", "link.md"))
            return writes_pref()(request)
        self.assert_not_applied(self.run_absorb(Runner(fn)), "not_regular_file")

    def test_secret_and_work_terms_fail(self):
        token = j("gh", "p_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
        report = self.run_absorb(Runner(writes_pref(
            page_fn=lambda t, s: pref_page(t, s, summary="키 " + token))))
        self.assert_not_applied(report, "secret_found")
        report = self.run_absorb(Runner(writes_pref(
            page_fn=lambda t, s: pref_page(t, s, summary="acmecorp 규칙"))))
        self.assert_not_applied(report, "work_terms_hit")

    def test_unknown_and_cross_domain_src(self):
        report = self.run_absorb(Runner(writes_pref(
            page_fn=lambda t, s: pref_page(t, ("mem:made-up/x.md", "2026-11-01")))))
        self.assert_not_applied(report, "src_unknown")

    def test_cross_domain_link(self):
        report = self.run_absorb(Runner(writes_pref(
            page_fn=lambda t, s: pref_page(t, s, summary="참고 [[work/projects/x|x]]"))))
        self.assert_not_applied(report, "cross_domain_link")

    def test_staging_tampering_fails(self):
        def fn(request):
            staging = request["staging_dir"]
            os.chmod(staging, 0o700)
            write(os.path.join(staging, "extra.md"), "x")
            return writes_pref()(request)
        self.assert_not_applied(self.run_absorb(Runner(fn)), "staging_modified")

    def test_budget_exceeded_is_held(self):
        report = self.run_absorb(Runner(lambda r: {"ok": False, "reason": "budget_exceeded"}))
        self.assertEqual(report["status"], "held")
        self.assertTrue(report["ok"])
        self.assertTrue(report["summary_line"].startswith("위키: 한도 보류"))
        self.assertNotIn(self.src_id, self.entries())

    def test_missing_claude_fails_without_running(self):
        write(os.path.join(self.root, "settings.json"),
              json.dumps({"claude_path": os.path.join(self.tmp, "no-such-claude")}))
        report = self.run_absorb(None)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["reason"], "claude_missing")
        self.assertEqual(report["summary_line"], "위키: 실패 (claude_missing)")


class NotesAndWithdrawalTest(AbsorbCase):
    def test_my_notes_must_stay_byte_for_byte(self):
        src_id = self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        page = os.path.join(self.root, "personal", "prefs", "answer-language.md")
        write(page, pref_page("답변 언어", ("prompts:personal/2026-11-01", "2026-11-01"))
              .replace("## 내 메모\n", "## 내 메모\n\n사람 메모 줄\r\n"))
        report = self.run_absorb(Runner(lambda r: result()))  # commits the human page first
        human = self.main_file("personal/prefs/answer-language.md")

        def fn(request):
            path = os.path.join(request["cwd"], "prefs", "answer-language.md")
            write(path, read(path).replace("사람 메모 줄", "고친 줄"))
            return result([path])
        self.add_memory(self.repo, "feedback_more.md", "새 선호")
        report = self.run_absorb(Runner(fn), now=LATER)
        self.assertEqual(report["batches"][0]["reason"], "my_notes_changed", report)
        self.assertEqual(self.main_file("personal/prefs/answer-language.md"), human)
        self.assertIn(src_id, json.dumps(self.entries()))

    def test_withdrawn_source_must_leave_the_pages(self):
        src_id = self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        self.assertEqual(self.run_absorb(Runner(writes_pref()))["status"], "ok")
        memfile = os.path.join(self.projects, prepare.fs_encode(self.repo), "memory",
                               "feedback_lang.md")
        os.unlink(memfile)
        lazy = Runner(lambda r: result())
        report = self.run_absorb(lazy, now=LATER)
        self.assertEqual(lazy.requests[0]["sources"][0]["op"], "deleted")
        self.assertEqual(report["batches"][0]["reason"], "src_withdrawn")
        self.assertEqual(self.entries()[src_id]["status"], "active")

        def removes(request):
            path = os.path.join(request["cwd"], "prefs", "answer-language.md")
            os.unlink(path)
            return result([path], withdrawn=[src_id])
        report = self.run_absorb(Runner(removes), now=LATER + datetime.timedelta(hours=1))
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(self.entries()[src_id]["status"], "deleted")
        self.assertFalse(self.committed("personal/prefs/answer-language.md"))
        self.assertNotIn("- 답변은", read(self.rules))
        self.assertEqual(report["rules_removed"], 1)


class MergeTest(AbsorbCase):
    def setUp(self):
        AbsorbCase.setUp(self)
        self.src_id = self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        schema = os.path.join(self.root, "SCHEMA.md")
        self.schema_dirty = read(schema) + "\n사람이 고친 줄\n"
        write(schema, self.schema_dirty)

    def test_human_edit_during_run_defers_that_file(self):
        target = os.path.join(self.root, "personal", "prefs", "answer-language.md")

        def fn(request):
            out = writes_pref()(request)
            write(target, "사람이 Obsidian에서 같은 이름으로 만든 파일\n")  # during the LLM step
            return out
        report = self.run_absorb(Runner(fn))
        self.assertEqual(report["status"], "ok", report)
        self.assertTrue(report["batches"][0]["deferred"])
        self.assertFalse(report["batches"][0]["merged"])
        self.assertIn("personal/prefs/answer-language.md", report["deferred_files"])
        self.assertEqual(read(target), "사람이 Obsidian에서 같은 이름으로 만든 파일\n")
        self.assertFalse(self.committed("personal/prefs/answer-language.md"))
        self.assertNotIn(self.src_id, self.entries())
        self.assertIn("보류 1", report["summary_line"])
        self.assertTrue(self.committed("log.md"))
        self.assertEqual(self.main_file("SCHEMA.md"), self.schema_dirty)

    def test_dirty_generated_file_is_deferred(self):
        now_md = os.path.join(self.root, "now.md")

        def fn(request):
            out = writes_pref()(request)
            write(now_md, read(now_md) + "\n### personal\n\n사람이 방금 쓴 메모\n")
            return out
        report = self.run_absorb(Runner(fn))
        self.assertEqual(report["status"], "ok", report)
        self.assertIn("now.md", report["deferred_files"])
        self.assertIn("사람이 방금 쓴 메모", read(now_md))
        self.assertTrue(self.committed("personal/prefs/answer-language.md"))

    def test_main_moved_merges_nothing(self):
        def fn(request):
            out = writes_pref()(request)
            write(os.path.join(self.root, "README-human.md"), "x\n")
            self.git(self.root, "add", "README-human.md")
            self.git(self.root, "-c", "user.email=t@localhost", "-c", "user.name=t", "commit",
                     "-q", "-m", "human")
            return out
        report = self.run_absorb(Runner(fn))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["reason"], "main_moved")
        self.assertFalse(self.committed("personal/prefs/answer-language.md"))
        self.assertNotIn(self.src_id, self.entries())
        self.assertEqual(self.main_file("SCHEMA.md"), self.schema_dirty)

    def test_rollback_restores_only_absorb_files(self):
        base_index = self.main_file("index.md")
        with mock.patch.object(absorb, "merged_mismatches", return_value=["index.md"]):
            report = self.run_absorb(Runner(writes_pref()))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["reason"], "merge_mismatch")
        self.assertEqual(self.head(), report["base_sha"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "personal", "prefs",
                                                     "answer-language.md")))
        self.assertEqual(self.main_file("index.md"), base_index)
        self.assertEqual(self.main_file("SCHEMA.md"), self.schema_dirty)
        status = self.git(self.root, "status", "--porcelain").stdout.decode()
        self.assertEqual(status.strip(), "M SCHEMA.md")
        self.assertNotIn(self.src_id, self.entries())

    def test_secret_anywhere_in_wiki_blocks_merge(self):
        token = j("xo", "xb-", "1234567890", "-abcdefghijklmnop")
        notes = os.path.join(self.root, "log.md")
        write(notes, read(notes) + "\n" + token + "\n")
        self.git(self.root, "add", "log.md")
        self.git(self.root, "-c", "user.email=t@localhost", "-c", "user.name=t", "commit", "-q",
                 "-m", "oops")
        report = self.run_absorb(Runner(writes_pref()))
        self.assertEqual(report["reason"], "secret_found")
        self.assertIn("secret_found:log.md", report["warnings"])
        self.assertFalse(self.committed("personal/prefs/answer-language.md"))


class MultiRunTest(AbsorbCase):
    def test_page_citing_a_merged_manual_source_stays_valid(self):
        page_path = os.path.join(self.root, "personal", "projects", "side.md")
        write(page_path, page_text("Side", "project", "personal",
                                   [("현재 상태", "- 사람이 쓴 상태")], extra=[("status", "active")]))

        def cite_manual(request):
            manual = [s for s in request["sources"] if s["id"].startswith("manual:")][0]
            path = os.path.join(request["cwd"], "projects", "side.md")
            write(path, read(path).replace(
                "- 사람이 쓴 상태\n",
                "- 사람이 쓴 상태\n<!-- src: %s @%s -->\n" % (manual["id"], manual["date"])))
            return result([path])
        report = self.run_absorb(Runner(cite_manual))
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(self.entries()["manual:personal/projects/side.md"]["status"], "closed")
        self.assertIn("src: manual:personal/projects/side.md",
                      self.main_file("personal/projects/side.md"))

        src_id = self.add_memory(self.repo, "project_side.md", "베타 출시", kind="project")

        def extend(request):
            source = request["sources"][0]
            path = os.path.join(request["cwd"], "projects", "side.md")
            write(path, read(path).replace(
                "## 내 메모", "## 실측값과 함정\n\n- 베타\n<!-- src: %s @%s -->\n\n## 내 메모"
                % (source["id"], source["date"]), 1))
            return result([path])
        report = self.run_absorb(Runner(extend), now=LATER)
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(self.entries()[src_id]["status"], "active")
        self.assertIn("- 베타", self.main_file("personal/projects/side.md"))

    def test_deferred_batch_does_not_half_merge(self):
        src_id = self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        human = os.path.join(self.root, "personal", "notes", "a.md")

        def fn(request):
            source = request["sources"][0]
            for name in ("a", "b"):
                write(os.path.join(request["cwd"], "notes", name + ".md"),
                      page_text(name.upper(), "note", "personal", [("요약", "내용 " + name)],
                                src=(source["id"], source["date"])))
            write(human, "사람이 만든 파일\n")  # Obsidian, during the LLM step
            return result()
        report = self.run_absorb(Runner(fn))
        self.assertEqual(report["status"], "ok", report)
        self.assertTrue(report["batches"][0]["deferred"])
        self.assertEqual(report["deferred_files"], ["personal/notes/a.md", "personal/notes/b.md"])
        self.assertFalse(self.committed("personal/notes/a.md"))
        self.assertFalse(self.committed("personal/notes/b.md"))
        self.assertNotIn("[[personal/notes/b", self.main_file("index.md"))
        self.assertEqual(read(human), "사람이 만든 파일\n")
        self.assertNotIn(src_id, self.entries())

        os.unlink(human)
        report = self.run_absorb(Runner(_write_ab), now=LATER)
        self.assertEqual(report["status"], "ok", report)
        self.assertTrue(self.committed("personal/notes/a.md"))
        self.assertTrue(self.committed("personal/notes/b.md"))
        self.assertEqual(self.entries()[src_id]["status"], "active")
        self.assertEqual(self.main_file("personal/notes/b.md").count("내용 b"), 1)


def _write_ab(request):
    source = request["sources"][0]
    paths = []
    for name in ("a", "b"):
        path = os.path.join(request["cwd"], "notes", name + ".md")
        write(path, page_text(name.upper(), "note", "personal", [("요약", "내용 " + name)],
                              src=(source["id"], source["date"])))
        paths.append(path)
    return result(paths)


FAKE_HELP = """Usage: claude [options] [command] [prompt]
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

FAKE_CLAUDE = r'''#!%(python)s
import json, os, re, sys
LOG = %(log)r
SCENARIO = %(scenario)r
HELP = %(help)r
args = sys.argv[1:]
if args == ["--help"]:
    sys.stdout.write(HELP)
    sys.exit(0)
prompt = sys.stdin.read()
add_dir = args[args.index("--add-dir") + 1]
record = {"argv": args, "env": dict(os.environ), "cwd": os.getcwd(), "prompt_head": prompt[:40]}
try:
    open(os.path.join(add_dir, "evil.md"), "w").close()
    record["staging_writable"] = True
except OSError:
    record["staging_writable"] = False
with open(SCENARIO) as handle:
    scenario = json.load(handle)
match = re.search(r"id: `([^`]+)` . op: \S+ . \S+: (\d{4}-\d{2}-\d{2})", prompt)
written = []
for rel, text in scenario.get("write", {}).items():
    path = os.path.join(os.getcwd(), rel)
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, "w") as handle:
        handle.write(text.replace("{SRC}", match.group(1)).replace("{DATE}", match.group(2)))
    written.append(path)
with open(LOG, "w") as handle:
    json.dump(record, handle)
out = {"type": "result", "subtype": scenario.get("subtype", "success"),
       "is_error": scenario.get("is_error", False), "total_cost_usd": 0.01}
if scenario.get("structured", True):
    out["structured_output"] = {"pages": written, "merges": [], "mentions": [],
                                "withdrawn_src": [], "notes": "fake"}
sys.stdout.write(json.dumps(out) + "\n")
sys.exit(scenario.get("exit", 0))
'''


class FakeClaudeTest(AbsorbCase):
    def setUp(self):
        AbsorbCase.setUp(self)
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        self.log = os.path.join(self.tmp, "fake-log.json")
        self.scenario = os.path.join(self.tmp, "fake-scenario.json")
        self.claude = self.make_fake(FAKE_HELP)
        write(os.path.join(self.root, "settings.json"),
              json.dumps({"claude_path": self.claude, "model": "test-model",
                          "max_budget_usd": 0.5}))

    def make_fake(self, help_text, name="claude"):
        path = os.path.join(self.tmp, "bin", name)
        write(path, FAKE_CLAUDE % {"python": sys.executable, "log": self.log,
                                   "scenario": self.scenario, "help": help_text})
        os.chmod(path, 0o755)
        return path

    def set_scenario(self, **data):
        write(self.scenario, json.dumps(data, ensure_ascii=False))

    def test_real_runner_flags_env_cwd_and_sealing(self):
        page = pref_page("답변 언어", ("{SRC}", "{DATE}"))
        self.set_scenario(write={"prefs/answer-language.md": page})
        report = self.run_absorb(None)
        self.assertEqual(report["status"], "ok", report)
        with open(self.log) as handle:
            seen = json.load(handle)
        argv = seen["argv"]
        staging = prepare.batch_dir(self.root, 1)
        expected = ["-p", "--restricted", "--strict-mcp-config", "--setting-sources", "",
                    "--tools", "Read,Edit,Write,Glob,Grep", "--add-dir", staging,
                    "--permission-mode", "acceptEdits", "--permission-prompts", "none",
                    "--no-session-persistence", "--output-format", "json", "--json-schema"]
        self.assertEqual(argv[:len(expected)], expected)
        self.assertEqual(json.loads(argv[len(expected)]), json.loads(json.dumps(
            verify.OUTPUT_SCHEMA)))
        self.assertEqual(argv[len(expected) + 1:], ["--model", "test-model",
                                                    "--max-budget-usd", "0.5"])
        self.assertEqual(os.path.realpath(seen["cwd"]),
                         os.path.realpath(os.path.join(self.wt, "personal")))
        env = seen["env"]
        allowed = {"HOME", "USER", "PATH", "LLM_WIKI_HOOK", "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
                   "CLAUDE_CODE_DISABLE_CLAUDE_MDS",
                   # added by the fake (a Python process) or macOS itself, not by absorb
                   "__CF_USER_TEXT_ENCODING", "PWD", "LC_CTYPE"}
        self.assertLessEqual(set(env), allowed, sorted(set(env) - allowed))
        self.assertEqual(env["LLM_WIKI_HOOK"], "0")
        self.assertNotIn("WIKI_ROOT", env)
        self.assertFalse(seen["staging_writable"])
        self.assertTrue(seen["prompt_head"].startswith("# 안전 규칙"))
        self.assertTrue(self.committed("personal/prefs/answer-language.md"))

    def test_probe_refuses_weaker_isolation(self):
        for flag in ("--restricted", "--permission-prompts", "--no-session-persistence"):
            help_text = "\n".join(line for line in FAKE_HELP.splitlines()
                                  if not line.strip().startswith(flag))
            claude = self.make_fake(help_text, name="claude-old")
            with self.assertRaises(common.WikiError) as caught:
                absorb.probe_claude(claude, absorb.llm_env(self.env, claude))
            self.assertEqual(caught.exception.reason, "claude_flags_missing")
        write(os.path.join(self.root, "settings.json"), json.dumps({"claude_path": claude}))
        self.set_scenario(write={})
        report = self.run_absorb(None)
        self.assertEqual(report["reason"], "claude_flags_missing")
        self.assertFalse(os.path.exists(self.log))

    def test_budget_and_error_results(self):
        self.set_scenario(write={}, subtype="error_max_budget_usd", is_error=True, exit=1,
                          structured=False)
        self.assertEqual(self.run_absorb(None)["status"], "held")
        self.set_scenario(write={}, subtype="error_during_execution", is_error=True, exit=1)
        report = self.run_absorb(None, now=LATER)
        self.assertEqual(report["batches"][0]["reason"], "llm_error")
        self.set_scenario(write={}, structured=False)
        report = self.run_absorb(None, now=LATER + datetime.timedelta(hours=1))
        self.assertEqual(report["batches"][0]["reason"], "llm_output_invalid")


class CliTest(AbsorbCase):
    def test_cli_absorb_empty_run(self):
        proc = self.run_cli("--json", "absorb", "--rules-path", self.rules)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        report = json.loads(proc.stdout.decode())
        self.assertIn(report["status"], ("empty", "failed"))
        self.assertEqual(report["rules_path"], self.rules)

    def test_lock_busy(self):
        with common.wiki_lock(self.root):
            with self.assertRaises(common.LockBusy):
                self.run_absorb(Runner(writes_pref()))


if __name__ == "__main__":
    unittest.main()
