"""verify (T3): changed-file detection, page checks, link conversion,
mentions, root page assembly, rules filtering. Temp git repos and
synthetic text only."""

import datetime
import json
import os
import unittest
from unittest import mock

import _helpers
import common
import verify

NOW = datetime.datetime(2026, 11, 6, 12, 0)
TERM = "AcmeCorp"
DOMAINS_CFG = {"owners": {}, "work_terms": [TERM], "redact_allow": []}


def j(*parts):
    return "".join(parts)


def write(path, text):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def page(title, domain="personal", kind="note", body="## 요약\n\n내용\n", fm_extra="",
         notes="## 내 메모\n"):
    return ("---\ntitle: %s\ntype: %s\ndomain: %s\n%s---\n# %s\n\n%s\n%s"
            % (title, kind, domain, fm_extra, title, body, notes))


class RepoCase(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        patcher = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                               "GIT_CONFIG_NOSYSTEM": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.wt = os.path.join(self.tmp, "wt")
        os.makedirs(self.wt)
        common.wiki_git(self.wt, ["init", "-q"])
        write(os.path.join(self.wt, ".gitignore"), "_drafts/\n")
        write(os.path.join(self.wt, "personal", "notes", ".gitkeep"), "")
        write(os.path.join(self.wt, "work", "notes", ".gitkeep"), "")
        self.commit()
        self.base = verify.head_sha(self.wt)

    def commit(self):
        common.wiki_git(self.wt, ["add", "-A"])
        common.wiki_git(self.wt, ["commit", "-q", "-m", "c"])

    def batch(self, ids=("mem:x/a.md",), domain="personal", deleted=()):
        sources = [common.make_source(i, domain, "new", "2026-11-04", "staging/1/a.md")
                   for i in ids]
        sources += [common.make_source(i, domain, "deleted", "2026-11-04", None) for i in deleted]
        return common.make_batch(1, sources)

    def check(self, batch=None, entries=None):
        return verify.check_batch(self.wt, self.base, batch or self.batch(), entries or {},
                                  DOMAINS_CFG)

    def assert_fails(self, reason, batch=None, entries=None):
        with self.assertRaises(verify.BatchFailure) as caught:
            self.check(batch, entries)
        self.assertEqual(caught.exception.reason, reason, caught.exception.problems)
        return caught.exception


class ChangedFilesTest(RepoCase):
    def test_korean_names_and_ignored_drafts_are_seen(self):
        write(os.path.join(self.wt, "personal", "notes", "한글 페이지.md"), page("한글"))
        write(os.path.join(self.wt, "personal", "_drafts", "now.md"), "- x\n")
        changes = dict((path, status) for status, path in verify.changed_files(self.wt, self.base))
        self.assertEqual(changes["personal/notes/한글 페이지.md"], "?")
        self.assertEqual(changes["personal/_drafts/now.md"], "?")
        check = self.check()
        self.assertEqual(check.pages, ["personal/notes/한글 페이지.md"])
        self.assertEqual(check.drafts, {"now.md": "- x\n"})

    def test_ignored_file_outside_globs_fails(self):
        write(os.path.join(self.wt, "work", "_drafts", "now.md"), "x")
        self.assert_fails("outside_allowed_globs")

    def test_tracked_change_outside_globs_fails(self):
        write(os.path.join(self.wt, ".gitignore"), "")
        self.assert_fails("outside_allowed_globs")


class PageChecksTest(RepoCase):
    def test_frontmatter_and_domain(self):
        write(os.path.join(self.wt, "personal", "notes", "a.md"), "---\ntitle: [x\n---\n")
        self.assert_fails("frontmatter_invalid")
        write(os.path.join(self.wt, "personal", "notes", "a.md"), page("a", domain="work"))
        self.assert_fails("page_domain_mismatch")

    def test_non_markdown_rejected(self):
        write(os.path.join(self.wt, "personal", "notes", "a.txt"), "x")
        self.assert_fails("non_markdown")

    def test_src_rules(self):
        path = os.path.join(self.wt, "personal", "notes", "a.md")
        write(path, page("a", body="## 요약\n\nx\n<!-- src: mem:x/a.md @2026-11-04 -->\n"))
        self.check()
        entries = {"mem:w/b.md": {"status": "active", "domain": "work"}}
        write(path, page("a", body="## 요약\n\nx\n<!-- src: mem:w/b.md @2026-11-04 -->\n"))
        self.assert_fails("src_cross_domain", entries=entries)
        write(path, page("a", body="## 요약\n\n```\n<!-- src: mem:zz/q.md @2026-11-04 -->\n```\n"))
        self.check()  # inside a code block: not a section marker

    def test_withdrawn_src_anywhere_in_domain(self):
        old = os.path.join(self.wt, "personal", "notes", "old.md")
        write(old, page("old", body="## 요약\n\nx\n<!-- src: mem:x/gone.md @2026-11-01 -->\n"))
        self.commit()
        self.base = verify.head_sha(self.wt)
        self.assert_fails("src_withdrawn", batch=self.batch(deleted=("mem:x/gone.md",)))
        entries = {"mem:x/gone.md": {"status": "deleted", "domain": "personal"}}
        write(os.path.join(self.wt, "personal", "notes", "b.md"), page("b"))
        self.assert_fails("src_withdrawn", entries=entries)

    def test_my_notes_preserved(self):
        path = os.path.join(self.wt, "personal", "notes", "a.md")
        write(path, page("a", notes="## 내 메모\n\n사람 글\r\n"))
        self.commit()
        self.base = verify.head_sha(self.wt)
        write(path, page("a", body="## 요약\n\n새 내용\n", notes="## 내 메모\n\n사람 글\r\n"))
        self.check()
        write(path, page("a", notes="## 내 메모\n\n사람 글\n"))
        self.assert_fails("my_notes_changed")
        os.unlink(path)
        self.assert_fails("my_notes_changed")

    def test_cross_domain_links(self):
        path = os.path.join(self.wt, "personal", "notes", "a.md")
        for link in ("[[work/projects/x|x]]", "[x](../../work/projects/x.md)", "[[/work/x]]"):
            write(path, page("a", body="## 요약\n\n%s\n" % link))
            self.assert_fails("cross_domain_link")
        write(path, page("a", body="## 요약\n\n`[[work/x]]` [[personal/notes/b|b]]\n"))
        self.assertEqual(self.check().broken_links, 1)

    def test_secret_and_work_terms(self):
        path = os.path.join(self.wt, "personal", "notes", "a.md")
        write(path, page("a", body="## 요약\n\n%s\n" % j("AKIA", "ABCDEFGHIJKLMNOP")))
        self.assert_fails("secret_found")
        write(path, page("a", body="## 요약\n\nＡｃｍｅＣｏｒｐ 일\n"))  # NFKC + casefold
        self.assert_fails("work_terms_hit")
        # A page the LLM creates may not carry text under '## 내 메모'.
        write(path, page("a", notes="## 내 메모\n\nacmecorp [[work/projects/x|x]]\n"))
        self.assert_fails("my_notes_changed")
        # A human's existing tail is not the LLM's output.
        write(path, page("a", body="## 요약\n\n원래\n", notes="## 내 메모\n\nacmecorp\n"))
        self.commit()
        self.base = verify.head_sha(self.wt)
        write(path, page("a", notes="## 내 메모\n\nacmecorp\n"))
        self.check()

    def test_output_normalization(self):
        batch = self.batch(ids=("mem:x/a.md",))
        abs_page = os.path.join(os.path.realpath(self.wt), "personal", "notes", "a.md")
        data = {"pages": [abs_page, "personal/notes/b.md", "/etc/passwd"],
                "merges": [["사이드 도구", "Side Tool"], ["solo"]],
                "mentions": [{"name": "Side Tool", "sources": ["mem:x/a.md", "mem:other/z.md"]}],
                "withdrawn_src": [], "notes": "n"}
        out = verify.normalize_output(data, self.wt, batch)
        self.assertEqual(out["pages"], ["personal/notes/a.md", "personal/notes/b.md"])
        self.assertEqual(out["mentions"], {"Side Tool": {"mem:x/a.md"}})
        self.assertEqual(out["merges"], [["사이드 도구", "Side Tool"]])
        with self.assertRaises(verify.BatchFailure):
            verify.normalize_output({"pages": "x"}, self.wt, batch)


class LinkConversionTest(unittest.TestCase):
    TARGETS = [(["Side Tool", "사이드 도구"], "personal/projects/side-tool.md"),
               (["ab"], "personal/notes/ab.md")]

    def test_links_first_plain_mention_only(self):
        text = ("---\ntitle: x\naliases: [Side Tool]\ntype: note\ndomain: personal\n---\n"
                "# Side Tool 메모\n\n"
                "`Side Tool` 와 [Side Tool](x) 그리고 <!-- Side Tool --> https://e.com/Side-Tool\n"
                "```\nSide Tool\n```\n"
                "사이드 도구를 쓴다. Side Tool 두 번째. ab 짧은 이름.\n"
                "## 내 메모\n\nSide Tool 사람 글\n")
        out = verify.convert_links(text, self.TARGETS, "personal/notes/x.md")
        self.assertIn("[[personal/projects/side-tool|사이드 도구]]를 쓴다. Side Tool 두 번째.", out)
        self.assertEqual(out.count("[[personal/projects/side-tool"), 1)
        self.assertTrue(out.startswith(text.split("# Side Tool")[0]))
        self.assertTrue(out.endswith("## 내 메모\n\nSide Tool 사람 글\n"))
        self.assertIn("`Side Tool` 와 [Side Tool](x) 그리고 <!-- Side Tool -->", out)
        self.assertIn("```\nSide Tool\n```", out)
        self.assertNotIn("[[personal/notes/ab", out)

    def test_latin_word_boundary_and_self(self):
        text = "---\ntitle: y\ntype: note\ndomain: personal\n---\nSideToolkit only\n"
        self.assertEqual(verify.convert_links(text, self.TARGETS, "personal/notes/y.md"), text)
        text = "---\ntitle: y\ntype: note\ndomain: personal\n---\nside tool here\n"
        self.assertIn("[[personal/projects/side-tool|side tool]]",
                      verify.convert_links(text, self.TARGETS, "personal/notes/y.md"))
        self.assertEqual(verify.convert_links(text, self.TARGETS,
                                              "personal/projects/side-tool.md"), text)


class MentionsTest(unittest.TestCase):
    def test_merged_names_count_together(self):
        mentions = {"Side Tool": {"a"}, "사이드 도구": {"b"}, "side tool": {"c"}, "Other": {"a"}}
        groups = verify.mention_groups(mentions, [["Side Tool", "사이드 도구"]])
        counts = dict((tuple(sorted(names)), len(ids)) for names, ids in groups)
        self.assertEqual(counts[("Side Tool", "사이드 도구")], 3)
        promoted = verify.promotions(mentions, [["Side Tool", "사이드 도구"]], [])
        self.assertEqual([(sorted(n), c, p) for n, c, p in promoted],
                         [(["Side Tool", "사이드 도구"], 3, None)])

    def test_update_mentions_accumulates(self):
        data = {"sources": {}}
        verify.update_mentions(data, "personal", {"A": {"s1"}}, [])
        verify.update_mentions(data, "personal", {"A": {"s2"}, "B": {"s3"}}, [["A", "B"]])
        self.assertEqual(data["mentions"]["personal"]["A"], ["s1", "s2"])
        self.assertEqual(data["mention_groups"]["personal"], [["A", "B"]])
        mentions, merges = verify.stored_mentions(data, "personal")
        self.assertEqual(verify.promotions(mentions, merges, [])[0][1], 3)
        self.assertEqual(verify.stored_mentions(data, "work"), ({}, []))


class RootAssemblyTest(unittest.TestCase):
    def template(self, name):
        with open(os.path.join(_helpers.TEMPLATES_DIR, "root", name), encoding="utf-8") as h:
            return h.read()

    def test_now_keeps_my_notes_and_other_domain(self):
        current = self.template("now.md").replace("### personal\n", "### personal\n\n사람\r\n")
        first = verify.assemble_now(current, {"work": "## work\n\n- 일 A\n"}, [])
        self.assertIn("## work\n\n- 일 A\n", first)
        self.assertEqual(verify.notes_tail(first), verify.notes_tail(current))
        second = verify.assemble_now(first, {"personal": "- 개인 B\n## 세부\n\n- c\n"},
                                     ["- 2026-11-05 · personal · [[personal/decisions/d|d]]"])
        self.assertIn("## work\n\n- 일 A\n", second)
        self.assertIn("## personal\n\n- 개인 B\n### 세부", second)
        self.assertIn("## 최근 결정\n\n- 2026-11-05", second)
        self.assertEqual(verify.notes_tail(second), verify.notes_tail(current))
        self.assertEqual(verify.assemble_now(second, {"personal": "- 개인 B\n## 세부\n\n- c\n"},
                                             ["- 2026-11-05 · personal · [[personal/decisions/d|d]]"]),
                         second)

    def test_about_me_sections_per_domain(self):
        current = self.template("about-me.md")
        out = verify.assemble_about_me(current, {"personal": "## 하는 일\n\n- 도구\n"})
        out = verify.assemble_about_me(out, {"work": "## 하는 일\n\n- 회의\n## 일하는 방식\n\n- 위임\n"})
        self.assertIn("## 하는 일\n\n### work\n\n- 회의\n\n### personal\n\n- 도구\n", out)
        self.assertIn("## 일하는 방식\n\n### work\n\n- 위임\n", out)
        self.assertEqual(verify.notes_tail(out), verify.notes_tail(current))


class RulesAndCachesTest(RepoCase):
    def pref(self, name, summary, scope="global", domain="personal", src=True):
        body = "## 선호\n\n%s\n%s" % (summary, "<!-- src: mem:x/a.md @2026-11-04 -->\n" if src else "")
        write(os.path.join(self.wt, domain, "prefs", name + ".md"),
              page(name, domain=domain, kind="pref", body=body,
                   fm_extra="scope: %s\nsummary: %s\n" % (scope, summary)))

    def test_rules_only_neutral_personal_global(self):
        self.pref("lang", "답변은 한국어로")
        self.pref("work-global", "업무 규칙", domain="work")
        self.pref("local", "레포 규칙", scope="domain")
        self.pref("leak", "acmecorp 방식대로")
        self.pref("secret", "키는 " + j("gh", "p_", "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"))
        self.pref("nosrc", "근거 없음", src=False)
        lines = verify.rules_lines(self.wt, DOMAINS_CFG)
        self.assertEqual(lines, ["- 답변은 한국어로"])
        rules = os.path.join(self.tmp, "out", "wiki-prefs.md")
        backups = os.path.join(self.tmp, "backups")
        self.assertEqual(verify.write_rules(rules, lines, backups, "r1"), (1, 0))
        self.assertEqual(verify.write_rules(rules, lines, backups, "r2"), (0, 0))
        self.assertFalse(os.path.exists(backups))
        self.assertEqual(verify.write_rules(rules, ["- 새 규칙"], backups, "r3"), (1, 1))
        self.assertTrue(os.path.isfile(os.path.join(backups, "wiki-prefs.r3.md")))

    def test_rules_caps(self):
        for index in range(verify.RULES_MAX_LINES + 5):
            self.pref("p%02d" % index, "규칙 %02d" % index)
        self.assertEqual(len(verify.rules_lines(self.wt, DOMAINS_CFG)), verify.RULES_MAX_LINES)

    def test_emptied_page_is_left_out_of_caches_and_index(self):
        write(os.path.join(self.wt, "personal", "prefs", "gone.md"),
              page("빈 선호", kind="pref", body="## 선호\n\n## Why\n\n## How to apply\n",
                   fm_extra="scope: domain\nsummary: 내용을 비웠다\n"))
        write(os.path.join(self.wt, "personal", "projects", "gone.md"),
              page("빈 프로젝트", kind="project", body="## 현재 상태\n\n## 내 메모\n\n손으로 쓴 글\n",
                   fm_extra="status: active\nsummary: 내용을 비웠다\n"))
        self.pref("살아 있는 선호", "내용", scope="domain")
        cache = verify.build_context_cache(self.wt, DOMAINS_CFG, "r", NOW)
        block = cache["domains"]["personal"]
        self.assertEqual([p["title"] for p in block["prefs"]], ["살아 있는 선호"])
        self.assertEqual(block["projects"], [])
        aliases = verify.build_alias_cache(self.wt, NOW, DOMAINS_CFG)["domains"]["personal"]
        self.assertEqual([e["title"] for e in aliases], ["살아 있는 선호"])
        index = verify.build_index(self.wt, NOW)
        self.assertNotIn("빈 선호", index)
        self.assertNotIn("빈 프로젝트", index)

    def test_pref_text_keeps_every_summary_line(self):
        write(os.path.join(self.wt, "personal", "prefs", "roles.md"),
              page("역할", kind="pref", body="## 선호\n\n- 본문\n<!-- src: mem:x/a.md @2026-11-04 -->\n",
                   fm_extra="scope: domain\nsummary: |\n  구현은 A가 한다.\n  B 레포에만 해당한다.\n"))
        cache = verify.build_context_cache(self.wt, DOMAINS_CFG, "r", NOW)
        self.assertEqual(cache["domains"]["personal"]["prefs"][0]["text"],
                         "구현은 A가 한다. B 레포에만 해당한다.")

    def test_context_cache_shape(self):
        self.pref("local", "레포 규칙", scope="repo")
        write(os.path.join(self.wt, "personal", "projects", "p.md"),
              page("P", kind="project", body="## 이번 주 무엇을 왜\n\n- 배포\n"
                   "<!-- src: mem:x/a.md @2026-11-04 -->\n",
                   fm_extra="repos: [me/p]\nstatus: active\nsummary: 요약\nas_of: 2026-10-01\n"))
        write(os.path.join(self.wt, "personal", "projects", "q.md"),
              page("Q", kind="project", body="## 현재 상태\n\nacmecorp\n",
                   fm_extra="status: active\n"))
        cache = verify.build_context_cache(self.wt, DOMAINS_CFG, "2026-11-06T1200", NOW)
        projects = cache["domains"]["personal"]["projects"]
        self.assertEqual([p["title"] for p in projects], ["P", "Q"])
        self.assertEqual(projects[0]["summary"], "")  # as_of older than 14 days
        self.assertEqual(projects[0]["this_week"], "배포")
        self.assertEqual(cache["domains"]["personal"]["prefs"][0]["scope"], "repo")
        self.assertEqual(cache["domains"]["work"], {"projects": [], "prefs": []})
        path = os.path.join(self.tmp, "state", "context-cache.json")
        self.assertTrue(verify.write_cache(path, cache, DOMAINS_CFG))
        bad = dict(cache, run_id=j("gh", "p_", "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"))
        self.assertFalse(verify.write_cache(path, bad, DOMAINS_CFG))
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["run_id"], "2026-11-06T1200")

    def test_paused_after_21_days(self):
        write(os.path.join(self.wt, "personal", "projects", "old.md"),
              page("Old", kind="project", body="## 현재 상태\n\nx\n"
                   "<!-- src: mem:x/a.md @2026-10-01 -->\n",
                   fm_extra="status: active\nupdated: 2026-10-01\n"))
        self.assertEqual(verify.apply_paused(self.wt, NOW), ["personal/projects/old.md"])
        with open(os.path.join(self.wt, "personal", "projects", "old.md"), encoding="utf-8") as h:
            self.assertIn("status: paused", h.read())

    def test_scan_tree_and_index(self):
        write(os.path.join(self.wt, "personal", "notes", "a.md"), page("A", fm_extra="summary: 첫 줄\n"))
        index = verify.build_index(self.wt, NOW)
        self.assertIn("## personal\n\n### notes\n\n- [[personal/notes/a|A]] — 첫 줄", index)
        self.assertEqual(verify.scan_tree(self.wt, []), [])
        write(os.path.join(self.wt, "x.md"), j("sk-ant-", "api03-abcdefghijklmnopqrstuv"))
        self.assertEqual(verify.scan_tree(self.wt, []), ["x.md:anthropic"])


if __name__ == "__main__":
    unittest.main()
