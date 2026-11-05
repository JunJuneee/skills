"""Regression tests for the review-round-3 fixes: redaction without the
slug and shape-only exemptions, usable redact_allow, held secret edits,
src ids outside the work_terms check, fence-safe root assembly, D10
expiry units and the cheap minors. Temp dirs and synthetic fixtures only;
secret-looking strings are assembled at runtime."""

import json
import os
import shutil
import tempfile
import unittest

import _helpers  # noqa: F401
import absorb
import common
import redact
import schedule
import test_absorb as ta
import test_verify as tv
import verify

NOW = ta.NOW
LATER = ta.LATER


def j(*parts):
    return "".join(parts)


# ---------------------------------------------------------------------------
# redact: contract 4 exceptions only
# ---------------------------------------------------------------------------

class RedactRound3Test(unittest.TestCase):
    def test_random_word_like_slugs_are_redacted(self):
        # Measured bypasses of the old slug exemption (entropy >= 4.0).
        for token in (j("sbmajjuh", "-csqyevwz", "-tmykxpej", "-xtuebwqu"),
                      j("MFeYerAM", "-NUNGVOBf", "-UhzHwceo", "-YjZLOcqL"),
                      j("qavtmeru", "-zibnoxal", "-pufydeks"),
                      j("mlheqpcy", "-bdeufzvn", "-tcmmtoqi")):
            self.assertGreaterEqual(redact.shannon_entropy(token), redact.ENTROPY_THRESHOLD)
            self.assertEqual(redact.scan("x %s y" % token), {"entropy": 1}, token)

    def test_shape_only_encoded_paths_are_redacted(self):
        for text in (j("value -data-", "Kx9mQp4ZsW8nBc6Lf3Yh", "-Rt2mQp4ZsW8nBc6Lf3Yh"),
                     j("-Users-", "Kx9mQp4Z", "-sW8nBc6L", "-f3YhRt2m")):
            self.assertEqual(redact.scan(text), {"entropy": 1}, text)

    def test_anchored_random_segments_are_redacted(self):
        for text in (j("/Zq8Lm3Xw9Pv", "Tn4Rb7Ys2/Kd+Hf6Jc1Gu", "5Ve0WaQ"),
                     j("`/Kx9mQp4ZsW8n", "/Bc6Lf3YhRt2m", "/Qp4ZsW8nBc6L`"),
                     j("웹훅 `/api/webhooks/123456789012345678/", "Xa9_Kq2-Lm7Pz4Rt8Wv",
                       "1Yc6Nb3Hd5Gf0Js2Ke4Mu7Qo9Ti1Ul3Ap6Bs8Dx0Fz2Hw5Jy7Lr9Nq1Pk3", "`")):
            self.assertTrue(redact.scan(text), text)

    def test_real_paths_and_src_ids_stay(self):
        folder = "-Users-someone-Desktop-side-tools"
        # Fix round 1: src ids are exempt only when the caller knows them.
        known = ["mem:%s/feedback_x.md" % folder,
                 "handoff:2026-11-05_sample-tools-workflow-v2-0123456789ab.md"]
        for text in ("~/.claude/projects/%s/memory/feedback_x.md" % folder,
                     "<!-- src: mem:%s/feedback_x.md @2026-11-01 -->" % folder,
                     "<!-- src: handoff:2026-11-05_sample-tools-workflow-v2-0123456789ab.md"
                     " @2026-11-05 -->",
                     "Sources/AppFeature/UserProfileSettingsPanel.swift",
                     "<!-- src:mem:%s/feedback_x.md @2026-11-01 -->" % folder,
                     "/srv/someone/.traycer/worktrees/acme__tools/tools-quiet-otter-0123456789ab"):
            self.assertEqual(redact.scan(text, known_ids=known), {}, text)
        # A src id is no hiding place for a long secret part.
        token = j("Zx9Qw3Er", "7Ty1Ui5O", "p2As8Df4", "Gh6Jk0Lm")
        cited = "mem:-Users-x/%s.md" % token
        self.assertTrue(redact.scan("<!-- src: %s @2026-11-01 -->" % cited, known_ids=[cited]))
        # Outside a src comment an encoded folder is just a token.
        self.assertEqual(redact.scan(j("mem:-Users-", "Kx9mQp4ZsW8nBc6Lf3YhRt2m/x.md")),
                         {"entropy": 1})

    def test_redact_allow_takes_the_bare_id_or_the_full_url(self):
        doc_id = j("1AbCdEfGhIjKlMnOp", "QrStUvWxYz0123456789abcdEf")
        url = "https://docs.example.com/document/d/%s/edit" % doc_id
        text = "문서 %s 참고" % url
        self.assertEqual(redact.scan(text), {"entropy": 1})
        self.assertEqual(redact.scan(text, [doc_id]), {})
        self.assertEqual(redact.scan(text, [url]), {})
        self.assertEqual(redact.redact(text, [doc_id]).text, text)
        # An allowed id does not cover a second secret next to it.
        token = j("Zx9Qw3Er", "7Ty1Ui5O", "p2As8Df4", "Gh6Jk0Lm")
        self.assertEqual(redact.scan("%s/%s" % (url, token), [doc_id]), {"entropy": 1})
        # Short entries never cut a token apart.
        self.assertEqual(redact.scan(text, ["d"]), {"entropy": 1})

    def test_random_slug_pref_never_reaches_the_rules_file(self):
        wt = tempfile.mkdtemp(prefix="wiki-r3-")
        self.addCleanup(shutil.rmtree, wt, True)
        token = j("mlheqpcy", "-bdeufzvn", "-tcmmtoqi")
        ta.write(os.path.join(wt, "personal", "prefs", "p.md"),
                 ta.pref_page("선호", ("mem:x/a.md", "2026-11-04"), summary="쓰기 " + token))
        ta.write(os.path.join(wt, "personal", "prefs", "q.md"),
                 ta.pref_page("선호 둘", ("mem:x/a.md", "2026-11-04"), summary="답변은 짧게"))
        self.assertEqual(verify.rules_lines(wt, {"work_terms": [], "redact_allow": []}),
                         ["- 답변은 짧게"])


class PageNameAllowTest(tv.RepoCase):
    def test_existing_page_names_are_allowed_and_random_links_are_not(self):
        name = "kubernetes-deployment-configuration-manager"
        random_name = j("sbmajjuh", "-csqyevwz", "-tmykxpej", "-xtuebwqu")
        self.assertEqual(redact.scan("see [[%s]]" % name), {"entropy": 1})
        self.assertEqual(redact.scan("see [[%s]]" % random_name), {"entropy": 1})
        tv.write(os.path.join(self.wt, "personal", "notes", name + ".md"), tv.page("k8s"))
        allow = verify.scan_allow(self.wt, tv.DOMAINS_CFG)
        self.assertIn(name, allow)
        self.assertEqual(redact.scan("see [[%s]] and %s" % (name, name), allow), {})
        self.assertEqual(redact.scan("see [[%s]]" % random_name, allow), {"entropy": 1})
        # A page linking an existing long-named page passes check_batch.
        tv.write(os.path.join(self.wt, "personal", "notes", "b.md"),
                 tv.page("b", body="## 요약\n\n[[%s]] 참고\n" % name))
        self.check()
        # A file name with a long random part is never trusted.
        token = j("Zx9Qw3Er", "7Ty1Ui5O", "p2As8Df4", "Gh6Jk0Lm")
        tv.write(os.path.join(self.wt, "personal", "notes", "x-%s.md" % token), tv.page("x"))
        self.assertNotIn("x-" + token, verify.scan_allow(self.wt, tv.DOMAINS_CFG))


class ExistingHitTest(ta.AbsorbCase):
    def test_bytes_main_already_holds_do_not_freeze_the_merge(self):
        slug = "kubernetes-deployment-configuration-manager-x"
        ta.write(os.path.join(self.root, "personal", "notes", "old.md"),
                 tv.page("old", body="## 요약\n\n%s 참고\n" % slug))
        self.git(self.root, "add", "-A")
        self.git(self.root, "-c", "user.email=t@localhost", "-c", "user.name=t", "commit", "-q",
                 "-m", "old")
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        report = self.run_absorb(ta.Runner(ta.writes_pref()))
        self.assertEqual(report["status"], "ok", report)
        self.assertIn("secret_found_existing:1", report["warnings"])
        # New bytes still block: a batch writing the same text fails.
        self.add_memory(self.repo, "feedback_more.md", "보고는 숫자로.")
        runner = ta.Runner(ta.writes_pref(extra_files={"notes/new.md": tv.page(
            "new", body="## 요약\n\n%s\n" % slug)}))
        report2 = self.run_absorb(runner, now=LATER)
        self.assertEqual(report2["batches"][0]["reason"], "secret_found", report2)


# ---------------------------------------------------------------------------
# prepare: an edit with a hit is held, the run goes on
# ---------------------------------------------------------------------------

class ManualSecretHoldTest(ta.AbsorbCase):
    def test_pasted_document_link_is_held_and_picked_up_once_allowed(self):
        doc_id = j("1AbCdEfGhIjKlMnOp", "QrStUvWxYz0123456789abcdEf")
        page = os.path.join(self.root, "personal", "notes", "links.md")
        ta.write(page, ta.page_text("링크", "note", "personal",
                                    [("요약", "문서 https://docs.example.com/d/%s/edit" % doc_id)]))
        src_id = self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        runner = ta.Runner(ta.writes_pref())
        report = self.run_absorb(runner)
        self.assertEqual(report["status"], "ok", report)
        self.assertIn("secret_found_manual:1", report["warnings"])
        self.assertNotIn("links.md", json.dumps(report["warnings"]))
        staged = [s["id"] for r in runner.requests for s in r["sources"]]
        self.assertIn(src_id, staged)
        self.assertNotIn("manual:personal/notes/links.md", staged)
        self.assertFalse(self.committed("personal/notes/links.md"))
        self.assertTrue(os.path.isfile(page))

        cfg = json.loads(ta.read(os.path.join(self.root, "domains.json")))
        cfg["redact_allow"] = [doc_id]
        ta.write(os.path.join(self.root, "domains.json"), json.dumps(cfg))
        self.git(self.root, "add", "domains.json")
        self.git(self.root, "-c", "user.email=t@localhost", "-c", "user.name=t", "commit", "-q",
                 "-m", "allow")
        again = ta.Runner(ta.writes_pref())
        report2 = self.run_absorb(again, now=LATER)
        self.assertNotIn("secret_found_manual:1", report2["warnings"], report2)
        self.assertTrue(self.committed("personal/notes/links.md"))
        staged = [s["id"] for r in again.requests for s in r["sources"]]
        self.assertIn("manual:personal/notes/links.md", staged)


# ---------------------------------------------------------------------------
# verify: src ids are not page content for work_terms
# ---------------------------------------------------------------------------

class SrcIdTermsTest(ta.AbsorbCase):
    def test_work_term_in_the_memory_folder_path_merges(self):
        repo = os.path.join(self.tmp, "Users", ta.TERM.lower(), "side")
        os.makedirs(repo)
        self.git(repo, "init", "-q")
        self.git(repo, "remote", "add", "o", "git@github.com:%s/side.git" % ta.ME)
        src_id = self.add_memory(repo, "feedback_lang.md", "답변은 한국어로.")
        self.assertIn(ta.TERM.lower(), src_id.lower())
        report = self.run_absorb(ta.Runner(ta.writes_pref()))
        self.assertEqual(report["status"], "ok", report)
        self.assertTrue(report["batches"][0]["merged"], report)


class SrcIdTermsVerifyTest(tv.RepoCase):
    def test_term_in_a_handoff_id_passes_and_in_the_body_fails(self):
        source_id = "handoff:2026-11-05_%s-side-notes.md" % tv.TERM.lower()
        path = os.path.join(self.wt, "personal", "notes", "a.md")
        tv.write(path, tv.page("a", body="## 요약\n\n내용\n<!-- src: %s @2026-11-04 -->\n"
                               % source_id))
        self.check(self.batch(ids=(source_id,)))
        tv.write(path, tv.page("a", body="## 요약\n\n%s 내용\n<!-- src: %s @2026-11-04 -->\n"
                               % (tv.TERM, source_id)))
        self.assert_fails("work_terms_hit", self.batch(ids=(source_id,)))


# ---------------------------------------------------------------------------
# Fences: a draft or root file with an open fence never costs 내 메모
# ---------------------------------------------------------------------------

class DraftFenceTest(tv.RepoCase):
    def test_unbalanced_draft_fails_the_batch(self):
        tv.write(os.path.join(self.wt, "personal", "_drafts", "now.md"), "- 사이드\n```\ncode\n")
        self.assert_fails("draft_unbalanced_fence")

    def test_root_assemblable(self):
        good = "# 지금\n\n## work\n\n```\nx\n```\n\n## 내 메모\n\n### personal\n\nmy note\n"
        self.assertTrue(verify.root_assemblable(good))
        bad = "# 지금\n\n## work\n\n```\n\n## 내 메모\n\n### personal\n\nmy note\n"
        self.assertFalse(verify.root_assemblable(bad))


class RootFenceTest(ta.AbsorbCase):
    def test_bad_fragment_fails_only_its_batch(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        self.add_memory(self.work_repo, "feedback_w.md", "리뷰는 짧게.")

        def fn(request):
            source = request["sources"][0]
            cwd = request["cwd"]
            dom = request["domain"]
            path = os.path.join(cwd, "prefs", "p-%s.md" % dom)
            ta.write(path, ta.pref_page("선호 %s" % dom, (source["id"], source["date"]),
                                        scope="domain", domain=dom))
            body = "- 사이드\n```\ncode\n" if dom == "personal" else "- 업무 정리\n"
            ta.write(os.path.join(cwd, "_drafts", "now.md"), body)
            return ta.result([path])

        report = self.run_absorb(ta.Runner(fn))
        by_domain = dict((b["domain"], b) for b in report["batches"])
        self.assertEqual(by_domain["personal"]["reason"], "draft_unbalanced_fence", report)
        self.assertTrue(by_domain["work"]["merged"], report)
        self.assertIn("## work\n\n- 업무 정리\n", self.main_file("now.md"))

    def test_open_fence_in_the_root_file_keeps_it_untouched(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        self.assertEqual(self.run_absorb(ta.Runner(ta.writes_pref()))["status"], "ok")
        path = os.path.join(self.root, "now.md")
        human = ta.read(path).replace("## work\n", "## work\n\n```\n", 1)
        human = human.rstrip("\n") + "\n\nmy note\n"
        ta.write(path, human)
        self.assertFalse(verify.root_assemblable(human))
        self.add_memory(self.repo, "feedback_more.md", "보고는 숫자로.")
        report = self.run_absorb(ta.Runner(ta.writes_pref(title="보고 형식")), now=LATER)
        self.assertNotEqual(report["status"], "failed", report)
        self.assertIn("root_file_skipped:now.md", report["warnings"])
        self.assertEqual(ta.read(path), human)


# ---------------------------------------------------------------------------
# Cheap minors: stray Obsidian notes, schedule install on a template
# ---------------------------------------------------------------------------

class MinorsRound3Test(ta.AbsorbCase):
    def test_untracked_root_note_is_counted(self):
        ta.write(os.path.join(self.root, "Untitled.md"), "그냥 메모\n")
        ta.write(os.path.join(self.root, "2026-11-06.md"), "오늘\n")
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        report = self.run_absorb(ta.Runner(ta.writes_pref()))
        self.assertIn("root_untracked_notes:2", report["warnings"], report)
        self.assertNotIn("Untitled", json.dumps(report))

    def test_foreign_user_rules_stop_personal_batches_only(self):
        rules_dir = os.path.join(self.home, ".claude", "rules")
        own = os.path.join(rules_dir, "wiki-prefs.md")
        ta.write(own, verify.rules_text(["- 답변은 짧게"]))
        absorb.record_rules_write(self.root, own, ["- 답변은 짧게"])
        terms = verify.Terms([ta.TERM])
        self.assertEqual(absorb.foreign_user_rules(self.env, None, self.root, terms), 0)
        ta.write(os.path.join(rules_dir, "team", "workflow.md"), "- 팀 규칙\n")
        self.assertEqual(absorb.foreign_user_rules(self.env, None, self.root, terms), 1)
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        self.add_memory(self.work_repo, "feedback_w.md", "리뷰는 짧게.")

        def fn(request):
            source = request["sources"][0]
            path = os.path.join(request["cwd"], "prefs", "p.md")
            ta.write(path, ta.pref_page("선호", (source["id"], source["date"]), scope="domain",
                                        domain=request["domain"]))
            return ta.result([path])

        runner = ta.Runner(fn)
        report = self.run_absorb(runner)
        self.assertIn("user_rules_present:1", report["warnings"])
        by_domain = dict((b["domain"], b) for b in report["batches"])
        self.assertEqual(by_domain["personal"]["reason"], "user_rules_unisolated")
        self.assertTrue(by_domain["work"]["merged"], report)
        self.assertEqual([r["domain"] for r in runner.requests], ["work"])

    def test_schedule_install_refuses_template_domains(self):
        ta.write(os.path.join(self.root, "domains.json"),
                 json.dumps({"owners": {"<work-github-org>": "work"}, "work_terms": ["x"]}))
        with self.assertRaises(common.WikiError) as caught:
            schedule.install(self.root, self.env, claude="/nonexistent", no_load=True,
                             agents_dir=os.path.join(self.tmp, "agents"))
        self.assertEqual(caught.exception.reason, "owners_unset")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "agents")))


# ---------------------------------------------------------------------------
# D10: expiry units
# ---------------------------------------------------------------------------

class ExpiryUnitsTest(unittest.TestCase):
    CUTOFF = "2026-10-23"

    def test_src_on_its_own_paragraph_expires_with_its_item(self):
        text = ("\n- old item\n\n<!-- src: handoff:a.md @2026-10-01 -->\n\n- new item\n\n"
                "<!-- src: mem:x/y.md @2026-11-04 -->\n")
        out = verify._expire_items(text, self.CUTOFF)
        self.assertNotIn("old item", out)
        self.assertNotIn("handoff:a.md", out)
        self.assertIn("- new item\n\n<!-- src: mem:x/y.md @2026-11-04 -->\n", out)

    def test_paragraph_with_trailing_src_block_expires(self):
        text = ("문단 내용\n\n<!-- src: handoff:a.md @2026-10-01 -->\n"
                "<!-- src: handoff:b.md @2026-10-02 -->\n\n- 남는 항목\n")
        out = verify._expire_items(text, self.CUTOFF)
        self.assertNotIn("문단 내용", out)
        self.assertIn("- 남는 항목", out)

    def test_nested_child_goes_with_its_parent(self):
        fresh = ("\n- a <!-- src: handoff:a.md @2026-10-01 -->\n"
                 "  - sub <!-- src: mem:x @2026-11-04 -->\n")
        self.assertEqual(verify._expire_items(fresh, self.CUTOFF), fresh)
        stale = ("\n- a <!-- src: handoff:a.md @2026-10-01 -->\n"
                 "  - sub <!-- src: handoff:a.md @2026-10-01 -->\n- keep\n")
        self.assertEqual(verify._expire_items(stale, self.CUTOFF), "\n- keep\n")


if __name__ == "__main__":
    unittest.main()
