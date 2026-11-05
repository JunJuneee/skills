"""Regression tests for the review-round-2 fixes: contract-4 path and slug
exceptions, held unscannable human edits, the '## 내 메모' heading on human
pages, personal page paths and work_terms, frontmatter links, per-item
handoff expiry, crash visibility in status, and the cheap minors. Temp dirs
and synthetic fixtures only; secret-looking strings are assembled at
runtime."""

import io
import json
import os
import stat
import subprocess
import sys
import unittest
from unittest import mock

import _helpers
import absorb
import common
import prepare
import redact
import schedule
import test_absorb as ta
import test_verify as tv
import verify
import wiki

NOW = ta.NOW


def j(*parts):
    return "".join(parts)


# ---------------------------------------------------------------------------
# Contract 4: path and slug exceptions are not shape-only
# ---------------------------------------------------------------------------

class RedactExceptionsTest(unittest.TestCase):
    def test_sequential_and_random_slugs_are_scanned(self):
        parts = [
            (j("abcd", "efgh"), j("ijkl", "mnop"), j("qrst", "uvwx")),
            (j("ABCD", "EFGH"), j("IJKL", "MNOP"), j("QRST", "UVWX")),
            (j("QWHZ", "KXPLMRTV"), j("BNXC", "VZLKJHGF"), j("POIU", "YTREWQAS")),
            (j("kxqz", "vbnmwqpl"), j("okij", "uhygtfrd"), j("eswa", "qzxcvbnm")),
        ]
        for group in parts:
            for sep in ("-", "_", "/"):
                token = sep.join(group)
                self.assertTrue(redact.scan("x %s y" % token), token)
            # A leading "-" is not an encoded path without a known root.
            self.assertTrue(redact.scan("x -%s y" % "-".join(group)), group)

    def test_dashed_hex_is_scanned(self):
        token = "-".join([j("deadbeef", "cafebabe"), j("01234567", "89abcdef"),
                          j("fedcba98", "76543210")])
        self.assertEqual(redact.scan("digest %s" % token), {"hex": 1})

    def test_colon_or_dot_before_a_slash_value_is_not_a_path(self):
        value = j("Ab3dE5gH", "9jK1mNq", "/", "Qr7sT2uV", "4wX6yZ8")
        for prefix in ("x:", ".", "file.", "note "):
            self.assertEqual(redact.scan(prefix + value), {"entropy": 1}, prefix)
        # A secret file name under an anchored dot folder is still caught.
        token = j("Zx9Qw3Er", "7Ty1Ui5O", "p2As8Df4", "Gh6Jk0Lm")
        self.assertEqual(redact.scan("~/.config/%s.json" % token), {"entropy": 1})

    def test_real_shapes_stay_clean(self):
        folder = j("-Users-someone--traycer-worktrees-acme--tools-", "tools-quiet-otter-",
                   "0123456789ab")
        texts = [
            "<!-- src: mem:%s/sample-review-board.md @2026-11-01 -->" % folder,
            "<!-- src: handoff:2026-11-05_sample-tools-workflow-v2-0123456789ab.md @2026-11-05 -->",
            "/home/someone/projects/demo-tools-lucky-fox-4c2e9a1b7d3f/skills",
            # Dot folders: the candidate starts after the dot, the token does not.
            "~/.traycer/worktrees/acme__tools/tools-quiet-otter-0123456789ab/skills",
            "~/.claude/projects/%s/memory/a.md" % folder,
            "/home/someone/.claude/projects/foo/bar-0123456789ab",
            "see ./.config/some-tool-4c2e9a1b7d3f/settings",
            '"~/.claude/projects/foo/bar-0123456789ab"',
        ]
        known = ["mem:%s/sample-review-board.md" % folder,
                 "handoff:2026-11-05_sample-tools-workflow-v2-0123456789ab.md"]
        for text in texts:
            self.assertEqual(redact.scan(text, known_ids=known), {}, text)

    def test_bare_natural_slugs_need_redact_allow(self):
        # Review round 3: contract 4 has no slug exception. A bare natural
        # slug at entropy >= 4.0 is flagged until it is listed.
        for slug in ("add-jumping-quickly-brown-fox-wizard",
                     "kubernetes-deployment-configuration-manager",
                     "Widget-Orbit-Planner-Example-Quick"):
            self.assertEqual(redact.scan("x %s y" % slug), {"entropy": 1}, slug)
            self.assertEqual(redact.scan("x %s y" % slug, [slug]), {}, slug)


# ---------------------------------------------------------------------------
# verify: notes heading, frontmatter links, page paths
# ---------------------------------------------------------------------------

class PageChecksRound2Test(tv.RepoCase):
    def test_heading_added_to_a_human_page_without_one_passes(self):
        path = os.path.join(self.wt, "personal", "notes", "human.md")
        tv.write(path, tv.page("human", notes=""))
        self.commit()
        self.base = verify.head_sha(self.wt)
        tv.write(path, tv.page("human", notes="## 내 메모\n"))
        self.check()
        tv.write(path, tv.page("human", notes="## 내 메모\n\n- LLM이 쓴 글\n"))
        self.assert_fails("my_notes_changed")

    def test_assert_notes_unchanged_treats_heading_only_as_empty(self):
        path = os.path.join(self.wt, "personal", "notes", "human.md")
        tv.write(path, tv.page("human", notes=""))
        snapshot = verify.notes_snapshot(self.wt, ["personal/notes/human.md"])
        tv.write(path, tv.page("human", notes="## 내 메모\n"))
        verify.assert_notes_unchanged(self.wt, snapshot)

    def test_encoded_src_id_passes_verify(self):
        folder = j("-Users-someone--traycer-worktrees-acme--tools-", "tools-quiet-otter-",
                   "0123456789ab")
        source_id = "mem:%s/sample-review-board.md" % folder
        tv.write(os.path.join(self.wt, "personal", "notes", "a.md"),
                 tv.page("a", body="## 요약\n\n내용\n<!-- src: %s @2026-11-04 -->\n" % source_id))
        self.check(self.batch(ids=(source_id,)))

    def test_frontmatter_link_into_the_other_domain_fails(self):
        tv.write(os.path.join(self.wt, "personal", "notes", "a.md"),
                 tv.page("a", fm_extra='aliases: ["[[work/decisions/x]]"]\n'))
        failure = self.assert_fails("cross_domain_link")
        self.assertIn("cross_domain_link:personal/notes/a.md", failure.problems)

    def test_personal_page_path_with_a_work_term_fails(self):
        tv.write(os.path.join(self.wt, "personal", "prefs", "acmecorp-answer-language.md"),
                 tv.page("답변 언어", kind="pref"))
        self.assert_fails("work_terms_hit")

    def test_term_named_page_is_no_link_target_and_not_indexed(self):
        tv.write(os.path.join(self.wt, "personal", "notes", "acmecorp-pay.md"),
                 tv.page("답변 언어"))
        other = os.path.join(self.wt, "personal", "notes", "b.md")
        tv.write(other, tv.page("b", body="## 요약\n\n답변 언어는 한국어\n"))
        terms = verify.Terms(tv.DOMAINS_CFG["work_terms"])
        self.assertEqual(verify.link_pages(self.wt, "personal", ["personal/notes/b.md"], terms),
                         [])
        self.assertNotIn("acmecorp", verify.build_index(self.wt, NOW, terms).lower())
        # Without terms (the old call) it would have been linked.
        self.assertEqual(verify.link_pages(self.wt, "personal", ["personal/notes/b.md"]),
                         ["personal/notes/b.md"])

    def test_term_named_page_gets_no_aliases_and_no_rules_line(self):
        path = os.path.join(self.wt, "personal", "prefs", "acmecorp-style.md")
        tv.write(path, tv.page("보고 형식", kind="pref",
                               body="## 선호\n\n결과만 보고\n<!-- src: mem:x/a.md @2026-11-04 -->\n",
                               fm_extra="scope: global\nsummary: 결과만 보고\n"))
        terms = verify.Terms(tv.DOMAINS_CFG["work_terms"])
        self.assertEqual(verify.sync_aliases(self.wt, "personal", [["보고 형식", "리포트"]], terms),
                         [])
        entries = {"mem:x/a.md": {"domain": "personal", "status": "active"}}
        self.assertEqual(verify.rules_lines(self.wt, tv.DOMAINS_CFG, entries), [])

    def test_recheck_pages_checks_the_path(self):
        tv.write(os.path.join(self.wt, "personal", "notes", "acmecorp-pay.md"), tv.page("x"))
        with self.assertRaises(verify.BatchFailure) as caught:
            verify.recheck_pages(self.wt, "personal", ["personal/notes/acmecorp-pay.md"],
                                 tv.DOMAINS_CFG)
        self.assertEqual(caught.exception.reason, "work_terms_hit")


class HandoffItemExpiryTest(tv.RepoCase):
    def test_old_handoff_item_goes_newer_item_stays(self):
        body = ("## 이번 주 무엇을 왜\n\n- 배포\n<!-- src: mem:x/a.md @2026-11-04 -->\n\n"
                "## 현재 상태\n\n- 오래된 handoff 항목\n<!-- src: handoff:a.md @2026-10-01 -->\n"
                "- 새 memory 항목\n<!-- src: mem:x/a.md @2026-11-04 -->\n\n"
                "## 실측값과 함정\n\n- 함정\n")
        path = os.path.join(self.wt, "personal", "projects", "p.md")
        tv.write(path, tv.page("p", kind="project", body=body,
                               fm_extra="status: active\nsummary: 요약\nas_of: 2026-10-01\n",
                               notes="## 내 메모\n\n- 오래된 handoff 항목\n"))
        self.assertEqual(verify.expire_handoff_state(self.wt, NOW), ["personal/projects/p.md"])
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("handoff:a.md", text)
        self.assertIn("## 현재 상태\n\n- 새 memory 항목\n<!-- src: mem:x/a.md @2026-11-04 -->\n\n"
                      "## 실측값과 함정", text)
        self.assertTrue(text.endswith("## 내 메모\n\n- 오래된 handoff 항목\n"))
        # Idempotent.
        self.assertEqual(verify.expire_handoff_state(self.wt, NOW), [])


# ---------------------------------------------------------------------------
# prepare: held unscannable edits, term-named personal pages, guard
# ---------------------------------------------------------------------------

class ManualHoldTest(ta.AbsorbCase):
    def test_non_utf8_file_with_a_token_is_never_committed(self):
        token = j("gh", "p_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
        path = os.path.join(self.root, "personal", "notes", "attachment.bin")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xfe\x00 " + token.encode("ascii") + b"\n")
        report = self.run_absorb(ta.Runner(ta.writes_pref()))
        self.assertIn("manual_unscanned:1", report["warnings"])
        log = self.git(self.root, "log", "-p", "--all").stdout
        self.assertNotIn(token.encode("ascii"), log)
        self.assertFalse(self.committed("personal/notes/attachment.bin"))
        self.assertTrue(os.path.exists(path))  # held, not deleted
        self.assertNotIn("manual:personal/notes/attachment.bin", self.entries())

    def test_term_named_human_page_is_quarantined(self):
        ta.write(os.path.join(self.root, "personal", "notes", "acmecorp-pay.md"),
                 tv.page("연봉 메모"))
        runner = ta.Runner(ta.writes_pref())
        report = self.run_absorb(runner)
        self.assertIn("personal_path_term:1", report["warnings"])
        staged = [s["id"] for r in runner.requests for s in r["sources"]]
        self.assertNotIn("manual:personal/notes/acmecorp-pay.md", staged)
        self.assertNotIn("acmecorp", (self.main_file("index.md") or "").lower())


class DomainsGuardRound2Test(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        patcher = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                               "GIT_CONFIG_NOSYSTEM": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        wiki.init_wiki(self.root, environ=self.env)

    def test_work_content_without_terms_stops(self):
        personal_only = {"owners": {"me": "personal"}, "work_terms": [], "overrides": {}}
        self.assertIsNone(common.domains_guard(personal_only, self.root))  # .gitkeep only
        override = dict(personal_only, overrides={"mem:x/a.md": "work"})
        self.assertEqual(common.domains_guard(override, self.root), "work_terms_unset")
        inbox = os.path.join(self.root, common.INBOX_DIRNAME, "work", "n.md")
        ta.write(inbox, "work note")
        self.assertEqual(common.domains_guard(personal_only, self.root), "work_terms_unset")
        os.unlink(inbox)
        ta.write(os.path.join(self.root, "work", "notes", "w.md"), "x")
        self.assertEqual(common.domains_guard(personal_only, self.root), "work_terms_unset")
        self.assertIsNone(common.domains_guard(dict(personal_only, work_terms=["t"]), self.root))

    def test_uncommitted_domains_json_is_not_warned(self):
        with open(os.path.join(self.root, "domains.json"), "a") as handle:
            handle.write("\n")
        warnings = []
        prepare.restore_generated(self.root, NOW, warnings)
        self.assertEqual(warnings, [])

    def test_init_closes_the_root_and_status_warns_when_open(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.root).st_mode), 0o700)
        self.assertNotIn("root_permissions_open", wiki.status_info(self.root, self.env)["warnings"])
        os.chmod(self.root, 0o755)
        self.assertIn("root_permissions_open", wiki.status_info(self.root, self.env)["warnings"])


class GitOptionalLocksTest(unittest.TestCase):
    def test_wiki_git_disables_optional_locks(self):
        seen = {}

        def fake_run(argv, **kwargs):
            seen["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with mock.patch.object(common.subprocess, "run", side_effect=fake_run):
            common.wiki_git("/nonexistent", ["status"], env={"PATH": "/usr/bin"})
        self.assertEqual(seen["env"]["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(seen["env"]["PATH"], "/usr/bin")


# ---------------------------------------------------------------------------
# Crash visibility: running marker, last-absorb on failure, traceback
# ---------------------------------------------------------------------------

class CrashVisibilityTest(ta.AbsorbCase):
    def test_setup_failure_is_recorded_and_marker_removed(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        self.run_absorb(ta.Runner(ta.writes_pref()))  # a previous good run
        self.add_memory(self.repo, "feedback_two.md", "결과만 보고.")
        boom = common.WikiError("git_failed", "worktree add failed")
        with mock.patch.object(absorb, "setup_worktree", side_effect=boom):
            with self.assertRaises(common.WikiError):
                self.run_absorb(ta.Runner(ta.writes_pref()), now=ta.LATER)
        last = absorb.read_last_absorb(self.root)
        self.assertEqual((last["status"], last["reason"]), ("failed", "git_failed"))
        self.assertIsNone(absorb.read_running_marker(self.root))
        self.assertFalse(os.path.exists(absorb.running_marker_path(self.root)))

    def test_marker_is_visible_while_running(self):
        seen = {}

        def fn(request):
            seen["running"] = wiki.status_info(self.root, self.env)["running"]
            return ta.writes_pref()(request)

        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        self.run_absorb(ta.Runner(fn))
        self.assertIsNotNone(seen["running"])
        self.assertIsNone(wiki.status_info(self.root, self.env)["running"])

    def test_dead_pid_marker_is_ignored(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        common.atomic_write_text(absorb.running_marker_path(self.root),
                                 json.dumps({"pid": proc.pid, "started_at": "x"}), mode=0o600)
        self.assertIsNone(absorb.read_running_marker(self.root))

    def test_internal_error_traceback_stays_out_of_stderr(self):
        secret_id = "mem:-Users-someone-Desktop-CompanyRepo/x.md"

        def explode(*_args, **_kwargs):
            raise KeyError(secret_id)

        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            report = schedule.run_absorb(self.root, self.env, absorb_fn=explode, send=False)
        self.assertEqual(report["reason"], "internal_error")
        self.assertNotIn(secret_id, err.getvalue())
        self.assertIn(secret_id, report["traceback"])
        self.assertNotIn("traceback", absorb.public_report(report))

    def test_status_text_shows_ledger_and_hides_next_run_when_not_installed(self):
        schedule.run_absorb(self.root, self.env, send=False,
                            absorb_fn=mock.Mock(side_effect=common.WikiError("git_failed", "x")))
        out = io.StringIO()
        args = mock.Mock(root=self.root, json=False)
        with mock.patch.object(sys, "stdout", out):
            wiki.cmd_status(args, self.env)
        text = out.getvalue()
        self.assertIn("장부의 마지막 실행:", text)
        self.assertIn("failed (git_failed)", text)
        self.assertIn("자동 실행: 설치 안 됨", text)
        self.assertNotIn("다음 자동 실행", text)


class QueryRound2Test(ta.AbsorbCase):
    def test_personal_query_skips_term_named_pages(self):
        ta.write(os.path.join(self.root, "personal", "notes", "acmecorp-pay.md"),
                 tv.page("연봉 메모", body="## 요약\n\n연봉 정리\n"))
        ta.write(os.path.join(self.root, "personal", "notes", "plain.md"),
                 tv.page("연봉 계획", body="## 요약\n\n연봉 계획\n"))
        results = wiki.query_pages(self.root, "personal", "연봉")
        self.assertEqual([r["path"] for r in results], ["personal/notes/plain.md"])


if __name__ == "__main__":
    unittest.main()
