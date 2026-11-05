"""Regression tests for the review-round-1 fixes: rollback keeps human
edits, the work_terms guard, the D12 rules default, new-page notes,
manual source records, merge-name filtering, session output, counts,
generated-file restore, root-notes sources, handoff expiry and the cheap
minors. Temp dirs and synthetic fixtures only; secret-looking strings are
assembled at runtime."""

import io
import json
import os
import stat
import unittest
from unittest import mock

import _helpers
import absorb
import common
import notify
import prepare
import schedule
import test_absorb as ta
import test_verify as tv
import verify
import wiki

NOW = ta.NOW
LATER = ta.LATER


def j(*parts):
    return "".join(parts)


class RollbackTest(ta.AbsorbCase):
    def test_human_write_between_merge_and_check_survives(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        target = os.path.join(self.root, "personal", "prefs", "answer-language.md")
        human = "사람이 병합 직후 Obsidian에서 고친 내용\n"
        real = absorb.merged_mismatches

        def racing(root, sha, paths):
            ta.write(target, human)  # Obsidian autosave right after the ff-merge
            return real(root, sha, paths)

        base_index = self.main_file("index.md")
        with mock.patch.object(absorb, "merged_mismatches", side_effect=racing):
            report = self.run_absorb(ta.Runner(ta.writes_pref()))
        self.assertEqual(report["reason"], "merge_mismatch", report)
        self.assertEqual(self.head(), report["base_sha"])
        self.assertEqual(ta.read(target), human)  # not erased by the rollback
        self.assertEqual(self.main_file("index.md"), base_index)  # absorb's own file restored


class DomainsGuardTest(ta.AbsorbCase):
    def write_cfg(self, owners, terms):
        ta.write(os.path.join(self.root, "domains.json"),
                 json.dumps({"owners": owners, "work_terms": terms}))

    def test_empty_or_placeholder_work_terms_stop_absorb(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        for owners, terms, reason in (
                ({ta.WORK_ORG: "work", ta.ME: "personal"}, [], "work_terms_unset"),
                ({ta.WORK_ORG: "work", ta.ME: "personal"}, ["<company-name>"], "work_terms_unset"),
                ({"<work-github-org>": "work", ta.ME: "personal"}, ["x"], "owners_unset")):
            self.write_cfg(owners, terms)
            runner = ta.Runner(ta.writes_pref())
            report = self.run_absorb(runner)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["reason"], reason)
            self.assertEqual(report["summary_line"], "위키: 실패 (%s)" % reason)
            self.assertEqual(runner.requests, [])
            self.assertFalse(os.path.exists(os.path.join(common.state_dir(self.root),
                                                         "context-cache.json")))
        # Personal-only owners need no work_terms.
        self.write_cfg({ta.ME: "personal"}, [])
        self.assertIsNone(common.domains_guard(common.load_domains(self.root)))


class RulesDefaultTest(ta.AbsorbCase):
    def test_default_is_claude_rules_under_the_given_home(self):
        self.assertEqual(absorb.default_rules_path(self.env),
                         os.path.join(self.home, ".claude", "rules", "wiki-prefs.md"))
        config = os.path.join(self.tmp, "cfg")
        self.assertEqual(absorb.default_rules_path(dict(self.env, CLAUDE_CONFIG_DIR=config)),
                         os.path.join(config, "rules", "wiki-prefs.md"))
        explicit = os.path.join(self.tmp, "x", "p.md")
        self.assertEqual(absorb.default_rules_path(dict(self.env, WIKI_RULES_PATH=explicit)),
                         explicit)

    def test_absorb_without_rules_path_writes_d12_file(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        report = absorb.absorb(self.root, environ=self.env, paths=self.paths(), now=NOW,
                               runner=ta.Runner(ta.writes_pref()))
        self.assertEqual(report["status"], "ok", report)
        expected = os.path.join(self.home, ".claude", "rules", "wiki-prefs.md")
        self.assertEqual(report["rules_path"], expected)
        self.assertIn("- 답변은 한국어로 짧게 한다", ta.read(expected))


class NewPageNotesTest(ta.AbsorbCase):
    def test_llm_page_with_text_under_my_notes_fails(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        report = self.run_absorb(ta.Runner(ta.writes_pref(
            page_fn=lambda t, s: ta.pref_page(t, s) + "\n주입된 글 [[work/projects/x|x]]\n")))
        self.assertEqual(report["batches"][0]["reason"], "my_notes_changed", report)
        self.assertFalse(self.committed("personal/prefs/answer-language.md"))


class ManualSourceTest(ta.AbsorbCase):
    def test_fabricated_manual_src_is_unknown(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        report = self.run_absorb(ta.Runner(ta.writes_pref(
            page_fn=lambda t, s: ta.pref_page(t, ("manual:personal/made-up.md", s[1])))))
        self.assertEqual(report["batches"][0]["reason"], "src_unknown", report)
        index = verify.SourceIndex({}, [], "personal")
        self.assertIsNone(index.domain_of("manual:personal/made-up.md"))
        closed = verify.SourceIndex({"manual:personal/a.md": {"status": "closed",
                                                              "domain": "personal"}}, [],
                                    "personal")
        self.assertEqual(closed.domain_of("manual:personal/a.md"), "personal")

    def test_secret_in_human_edit_is_not_committed(self):
        page = os.path.join(self.root, "personal", "notes", "pasted.md")
        token = j("gh", "p_", "Q1w2E3r4T5y6U7i8O9p0A1s2D3f4G5h6J7k8")
        ta.write(page, ta.page_text("붙여 넣음", "note", "personal", [("요약", "키 " + token)]))
        runner = ta.Runner(ta.writes_pref())
        report = self.run_absorb(runner)
        # Review round 3: the file is held (count-only warning), the run goes on.
        self.assertIn("secret_found_manual:1", report["warnings"], report)
        self.assertNotEqual(report["status"], "failed", report)
        staged = [s["id"] for r in runner.requests for s in r["sources"]]
        self.assertNotIn("manual:personal/notes/pasted.md", staged)
        log = self.git(self.root, "log", "--all", "-p").stdout.decode("utf-8", "replace")
        self.assertNotIn(token, log)
        self.assertTrue(os.path.isfile(page))  # left for the human to fix


class MergeNamesTest(ta.AbsorbCase):
    def test_work_term_merge_name_never_reaches_aliases_or_caches(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")

        def fn(request):
            out = ta.writes_pref()(request)
            out["structured"]["merges"] = [["답변 언어", ta.TERM + " 언어"]]
            out["structured"]["mentions"].append({"name": ta.TERM + " 툴",
                                                  "sources": [request["sources"][0]["id"]]})
            return out
        report = self.run_absorb(ta.Runner(fn))
        self.assertEqual(report["status"], "ok", report)
        page = self.main_file("personal/prefs/answer-language.md")
        self.assertNotIn(ta.TERM, page)
        state = common.state_dir(self.root)
        self.assertNotIn(ta.TERM, ta.read(os.path.join(state, "alias-cache.json")))
        self.assertNotIn(ta.TERM, ta.read(os.path.join(state, "sources.json")))


class SessionOutputTest(ta.AbsorbCase):
    def test_public_report_has_codes_and_counts_only(self):
        report = absorb.new_report()
        report.update(status="ok", ok=True, run_id="r1", summary_line="위키: 반영 1",
                      warnings=["secret_found:work/projects/hidden.md", "draft_ignored:x/y",
                                "secret_found:work/b.md"],
                      deferred_files=["work/projects/hidden.md"])
        batch = common.make_batch(1, [common.make_source(
            "mem:-opt-HiddenRepo/feedback.md", "work", "new", "2026-11-04", "staging/1/a.md")])
        outcome = absorb._new_outcome(batch)
        outcome["problems"] = ["src_unknown:work/projects/hidden.md:mem:-opt-HiddenRepo/f.md"]
        outcome["pages"] = ["work/projects/hidden.md"]
        report["batches"] = [outcome]
        shown = json.dumps(absorb.public_report(report, "/state/last-report.json"),
                           ensure_ascii=False)
        self.assertNotIn("hidden", shown)
        self.assertNotIn("HiddenRepo", shown)
        public = json.loads(shown)
        self.assertEqual(public["warnings"], {"secret_found": 2, "draft_ignored": 1})
        self.assertEqual(public["batches"][0]["problems"], 1)
        self.assertEqual(public["deferred_files"], 1)

    def test_cli_prints_no_paths_and_writes_the_report_file(self):
        fake = absorb.new_report()
        fake.update(status="ok", ok=True, run_id="r1", summary_line="위키: 반영 0",
                    warnings=["secret_found:work/projects/hidden.md"])
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(schedule, "run_absorb", return_value=fake), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = wiki.main(["--root", self.root, "--json", "absorb"], environ=self.env)
        self.assertEqual(code, 0)
        self.assertNotIn("hidden", out.getvalue() + err.getvalue())
        path = absorb.last_report_path(self.root)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertIn("hidden", ta.read(path))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(schedule, "run_absorb", return_value=fake), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            wiki.main(["--root", self.root, "absorb"], environ=self.env)
        self.assertNotIn("hidden", out.getvalue() + err.getvalue())
        self.assertIn("경고: secret_found", err.getvalue())


class CountsAndStagingTest(ta.AbsorbCase):
    def test_unresolved_counts_only_changes_and_staging_is_emptied(self):
        self.add_memory(os.path.join(self.tmp, "nowhere", "unknown-project"), "u.md",
                        "판정 불가 원본")
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        first = self.run_absorb(ta.Runner(ta.writes_pref()))
        self.assertEqual(first["unresolved"], 1, first)
        self.assertEqual(os.listdir(common.staging_dir(self.root)), [])
        self.add_memory(self.repo, "feedback_more.md", "새 선호")
        second = self.run_absorb(ta.Runner(lambda r: ta.result()), now=LATER)
        self.assertEqual(second["unresolved"], 0, second)
        cache = json.loads(ta.read(os.path.join(common.state_dir(self.root),
                                                "context-cache.json")))
        self.assertEqual(cache["pending"]["unresolved"], 0)
        self.assertIn("판정 불가 0", self.main_file("log.md").splitlines()[-1])


class GeneratedRestoreTest(ta.AbsorbCase):
    def test_human_edit_to_index_is_backed_up_and_restored(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        index = os.path.join(self.root, "index.md")
        ta.write(index, ta.read(index) + "사람이 실수로 쓴 줄\n")
        report = self.run_absorb(ta.Runner(ta.writes_pref()))
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(report["deferred_files"], [])
        self.assertIn("generated_restored:index.md", report["warnings"])
        self.assertIn("[[personal/prefs/answer-language|", self.main_file("index.md"))
        backups = os.path.join(common.state_dir(self.root), "backups")
        saved = [name for name in os.listdir(backups) if name.startswith("index.md.")]
        self.assertEqual(len(saved), 1)
        self.assertIn("사람이 실수로 쓴 줄", ta.read(os.path.join(backups, saved[0])))

    def test_deferred_file_shows_in_the_slack_line(self):
        self.assertEqual(notify.format_line({"status": "ok", "applied": 1, "new_pages": 0,
                                             "quarantined": 0, "rules_added": 0,
                                             "rules_removed": 0, "batches": [{"ok": True}],
                                             "deferred_files": ["now.md"]}),
                         "위키: 반영 1 · 새 페이지 0 · 격리 0 · 전역 선호 +0/−0 · 보류 파일 1")


class UnreadablePageTest(ta.AbsorbCase):
    def test_cp949_page_does_not_abort_the_run(self):
        legacy = os.path.join(self.root, "personal", "notes", "legacy.md")
        with open(legacy, "wb") as handle:
            handle.write("---\ntitle: 옛 메모\ntype: note\ndomain: personal\n---\n본문\n"
                         .encode("cp949"))
        self.git(self.root, "add", "personal/notes/legacy.md")
        self.git(self.root, "-c", "user.email=t@localhost", "-c", "user.name=t", "commit",
                 "-q", "-m", "legacy")
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        report = self.run_absorb(ta.Runner(ta.writes_pref()))
        self.assertEqual(report["status"], "ok", report)
        self.assertTrue(self.committed("personal/prefs/answer-language.md"))


class VerifyFixesTest(tv.RepoCase):
    def test_bare_wikilink_into_other_domain_fails(self):
        tv.write(os.path.join(self.wt, "work", "projects", "secret-plan.md"),
                 tv.page("Plan", domain="work"))
        self.commit()
        self.base = verify.head_sha(self.wt)
        path = os.path.join(self.wt, "personal", "notes", "a.md")
        tv.write(path, tv.page("a", body="## 요약\n\n[[secret-plan]] 참고\n"))
        self.assert_fails("cross_domain_link")
        tv.write(path, tv.page("a", body="## 요약\n\n[[other-page]] 참고\n"))
        self.check()

    def test_gitkeep_must_be_empty(self):
        tv.write(os.path.join(self.wt, "personal", "notes", ".gitkeep"), "hidden text\n")
        self.assert_fails("gitkeep_not_empty")

    def test_rules_need_a_recorded_personal_source(self):
        body = "## 선호\n\n결과만 보고\n<!-- src: mem:x/a.md @2026-11-04 -->\n"
        tv.write(os.path.join(self.wt, "personal", "prefs", "p.md"),
                 tv.page("p", kind="pref", body=body,
                         fm_extra="scope: global\nsummary: 결과만 보고\n"))
        self.assertEqual(verify.rules_lines(self.wt, tv.DOMAINS_CFG, {}), [])
        entries = {"mem:x/a.md": {"domain": "personal", "status": "active"}}
        self.assertEqual(verify.rules_lines(self.wt, tv.DOMAINS_CFG, entries), ["- 결과만 보고"])

    def test_handoff_only_state_expires_after_14_days(self):
        stale = ("## 이번 주 무엇을 왜\n\n- 배포\n<!-- src: prompts:personal/2026-11-05 @2026-11-05 -->"
                 "\n\n## 현재 상태\n\n- 그날의 상태\n<!-- src: handoff:a.md @2026-10-01 -->\n\n"
                 "## 실측값과 함정\n\n- 함정\n")
        fresh = stale.replace("handoff:a.md @2026-10-01", "handoff:a.md @2026-11-01")
        mixed = stale.replace("<!-- src: handoff:a.md @2026-10-01 -->",
                              "<!-- src: handoff:a.md @2026-10-01 -->\n"
                              "<!-- src: mem:x/a.md @2026-11-04 -->")
        for name, body in (("stale", stale), ("fresh", fresh), ("mixed", mixed)):
            tv.write(os.path.join(self.wt, "personal", "projects", name + ".md"),
                     tv.page(name, kind="project", body=body,
                             fm_extra="status: active\nsummary: 요약\nas_of: 2026-10-01\n",
                             notes="## 내 메모\n\n- 그날의 상태\n"))
        changed = verify.expire_handoff_state(self.wt, tv.NOW)
        self.assertEqual(changed, ["personal/projects/stale.md"])
        with open(os.path.join(self.wt, "personal", "projects", "stale.md"), encoding="utf-8") as h:
            text = h.read()
        self.assertIn("## 현재 상태\n\n## 실측값과 함정", text)
        self.assertIn("## 이번 주 무엇을 왜\n\n- 배포", text)
        self.assertTrue(text.endswith("## 내 메모\n\n- 그날의 상태\n"))
        cache = verify.build_context_cache(self.wt, tv.DOMAINS_CFG, "r", tv.NOW)
        summaries = dict((p["title"], p["summary"])
                         for p in cache["domains"]["personal"]["projects"])
        self.assertEqual(summaries, {"stale": "", "fresh": "요약", "mixed": "요약"})


class MinorsTest(_helpers.TempHomeCase):
    def test_resolver_skips_home_and_epic_folders(self):
        epic = os.path.join(self.home, ".traycer", "epics", "e1")
        repo = os.path.join(self.tmp, "repo")
        for path in (epic, repo):
            os.makedirs(path)
        resolver = prepare.Resolver({"owners": {"me": "personal"}, "work_terms": ["t"]},
                                    remote_fn=lambda cwd: ["git@github.com:me/x.git"],
                                    home=self.home)
        self.assertIsNone(resolver.cwd_domain(self.home))
        self.assertIsNone(resolver.cwd_domain(epic))
        self.assertEqual(resolver.cwd_domain(repo), "personal")

    def test_traycer_repo_fallback_needs_no_workspace(self):
        workspace = os.path.join(self.tmp, "ws")
        os.makedirs(workspace)
        resolver = prepare.Resolver({"owners": {"me": "personal"}, "work_terms": ["t"]},
                                    remote_fn=lambda cwd: ["git@github.com:other/x.git"],
                                    home=self.home)
        epics = prepare.TraycerEpics(None, resolver, [])
        epics._payloads = {
            "with": {"workspaces": [{"workspacePath": workspace}],
                     "repoIdentifiers": [{"owner": "me", "repo": "x"}]},
            "without": {"repoIdentifiers": [{"owner": "me", "repo": "x"}]}}
        self.assertEqual(epics.domain("with"), (None, None))
        self.assertEqual(epics.domain("without"), ("personal", None))

    def test_token_cmd_found_outside_the_job_path(self):
        local_bin = os.path.join(self.home, ".local", "bin")
        os.makedirs(local_bin)
        program = os.path.join(local_bin, "fake-cred-tool")
        with open(program, "w") as handle:
            handle.write("#!/bin/sh\n")
        os.chmod(program, 0o755)
        environ = {"HOME": self.home, "PATH": os.path.join(self.tmp, "empty")}
        self.assertEqual(notify.resolve_program("fake-cred-tool", environ), program)
        self.assertIsNone(notify.resolve_program("no-such-tool-xyz", environ))

    def test_bootstrap_retries_after_bootout(self):
        class Proc(object):
            def __init__(self, code):
                self.returncode = code
                self.stderr = b"Bootstrap failed: 5: Input/output error"
        calls = []
        results = [Proc(5), Proc(5), Proc(0)]

        def fake(tool, args, check=True):
            calls.append(args)
            return results.pop(0)
        with mock.patch.object(schedule, "_launchctl", side_effect=fake):
            schedule.bootstrap("launchctl", "gui/1", "/x.plist", sleep=lambda s: None)
            self.assertEqual(len(calls), 3)
            results[:] = [Proc(5)] * 5
            with self.assertRaises(common.WikiError) as caught:
                schedule.bootstrap("launchctl", "gui/1", "/x.plist", sleep=lambda s: None)
        self.assertEqual(caught.exception.reason, "launchctl_failed")
        self.assertIn("not loaded", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
