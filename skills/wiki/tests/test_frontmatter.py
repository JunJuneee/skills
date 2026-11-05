import unittest

import _helpers  # noqa: F401
import common
from common import FrontmatterError


OBSIDIAN_PAGE = (
    "---\n"
    "title: 예시 프로젝트\n"
    "aliases:\n"
    "  - Example Project\n"
    "  - \"[[personal/projects/example]]\"\n"
    "type: project\n"
    "domain: personal\n"
    "repos:\n"
    "  - owner/example\n"
    "status: active\n"
    "summary: |\n"
    "  첫 줄\n"
    "  둘째 줄\n"
    "tags: []\n"
    "updated: 2026-11-05\n"
    "---\n"
    "# 예시\n\n## 내 메모\n\n손 메모\n"
)


class FrontmatterParseTest(unittest.TestCase):
    def test_flow_and_block_lists_are_equal(self):
        flow, _ = common.parse_frontmatter("---\naliases: [a, \"b c\", 'd''e']\n---\n")
        block, _ = common.parse_frontmatter(
            "---\naliases:\n  - a\n  - \"b c\"\n  - 'd''e'\n---\n")
        col0, _ = common.parse_frontmatter("---\naliases:\n- a\n- b c\n- d'e\n---\n")
        self.assertEqual(flow["aliases"], ["a", "b c", "d'e"])
        self.assertEqual(flow, block)
        self.assertEqual(flow, col0)

    def test_obsidian_block_list_round_trip(self):
        fm, body = common.parse_frontmatter(OBSIDIAN_PAGE)
        self.assertEqual(fm["aliases"], ["Example Project", "[[personal/projects/example]]"])
        self.assertEqual(fm["summary"], "첫 줄\n둘째 줄\n")
        self.assertEqual(fm["tags"], [])
        self.assertEqual(common.render_page(fm, body), OBSIDIAN_PAGE)

    def test_flow_list_rewritten_as_obsidian_block(self):
        fm, body = common.parse_frontmatter("---\naliases: [a, b]\n---\nbody")
        self.assertEqual(common.render_page(fm, body), "---\naliases:\n  - a\n  - b\n---\nbody")

    def test_scalars_stay_strings(self):
        fm, _ = common.parse_frontmatter(
            "---\na: true\nb: 2026\nc: 2026-11-05\nd: null\ne: '3'\n---\n")
        self.assertEqual(fm, {"a": "true", "b": "2026", "c": "2026-11-05", "d": "null", "e": "3"})
        self.assertEqual(common.dump_scalar("true"), "true")
        self.assertEqual(common.dump_scalar("2026-11-05"), "2026-11-05")

    def test_obsidian_checkbox_and_number_round_trip(self):
        text = "---\ndone: true\ncount: 3\nmissing: null\n---\n"
        fm, body = common.parse_frontmatter(text)
        self.assertEqual(fm["done"], "true")
        self.assertEqual(common.render_page(fm, body), text)

    def test_bare_key_and_empty_list(self):
        fm, _ = common.parse_frontmatter("---\nempty:\nlist: []\nnext: x\n---\n")
        self.assertIsNone(fm["empty"])
        self.assertEqual(fm["list"], [])
        self.assertEqual(common.dump_frontmatter(fm), "empty:\nlist: []\nnext: x\n")

    def test_block_strings(self):
        fm, _ = common.parse_frontmatter(
            "---\nkeep: |\n  a\n\n  b\n\nstrip: |-\n  x\n  y\nafter: z\n---\n")
        self.assertEqual(fm["keep"], "a\n\nb\n")
        self.assertEqual(fm["strip"], "x\ny")
        self.assertEqual(fm["after"], "z")

    def test_comments_and_blank_lines(self):
        fm, _ = common.parse_frontmatter(
            "---\n# comment\ntitle: a # trailing\n\nlist:\n  - x\n\n  - y\n---\n")
        self.assertEqual(fm["title"], "a")
        self.assertEqual(fm["list"], ["x", "y"])

    def test_body_is_byte_identical(self):
        for text in ("---\r\ntitle: a\r\n---\r\nline1\r\n\r\n## 내 메모\r\nx",
                     "---\ntitle: a\n---\nno trailing newline",
                     "---\ntitle: a\n---\n",
                     "---\ntitle: a\n---\n---\nmore dashes\n"):
            fm, body = common.parse_frontmatter(text)
            self.assertEqual(fm["title"], "a")
            self.assertTrue(text.endswith(body))
            _fm_text, body2, newline = common.split_frontmatter(text)
            self.assertEqual(body, body2)
            self.assertEqual(common.render_page(fm, body, newline), text)

    def test_no_frontmatter(self):
        fm, body = common.parse_frontmatter("# plain\n---\n")
        self.assertEqual(fm, {})
        self.assertEqual(body, "# plain\n---\n")
        self.assertEqual(common.render_page(fm, body), body)

    def test_key_order_and_unknown_keys_preserved(self):
        fm, body = common.parse_frontmatter("---\nzeta: 1\ncustom key: v\nalpha: 2\n---\n")
        self.assertEqual(list(fm.keys()), ["zeta", "custom key", "alpha"])
        self.assertEqual(common.render_page(fm, body), "---\nzeta: 1\ncustom key: v\nalpha: 2\n---\n")

    def test_dump_parse_round_trip_awkward_strings(self):
        values = [
            "a: b", "x #y", "- dash", "[bracket", "{brace", '"dq', "'sq", "!bang",
            "&amp", "*star", "@at", "`tick", "|pipe", ">gt", "%pct", "?q", ",comma",
            "[[link]]", "한글 제목: 부제", "", " lead", "trail ", "colon:", "true", "No",
            "~", "back\\slash", 'say "hi"', "tab\there", "multi\nline\n", "multi\nline",
            "trailing\n\n", "\n", "  indented\nsecond", "ok-value", "x\u0007bell", "#hash",
        ]
        fm = {}
        for index, value in enumerate(values):
            fm["k%d" % index] = value
        fm["list"] = list(values)
        fm["none"] = None
        fm["emptylist"] = []
        text = "---\n" + common.dump_frontmatter(fm) + "---\n"
        parsed, body = common.parse_frontmatter(text)
        self.assertEqual(body, "")
        self.assertEqual(dict(parsed), fm)

    def test_rejects_unsupported_yaml(self):
        bad = [
            "---\nmap:\n  nested: x\n---\n",
            "---\nflow: {a: 1}\n---\n",
            "---\nanchor: &a x\n---\n",
            "---\nalias: *a\n---\n",
            "---\nfolded: >\n  x\n---\n",
            "---\nindent: |2\n  x\n---\n",
            "---\nkeep: |+\n  x\n---\n",
            "---\n\ttitle: x\n---\n",
            "---\nlist:\n\t- x\n---\n",
            "---\ntitle: a: b\n---\n",
            "---\ntitle: x\ntitle: y\n---\n",
            "---\nlist:\n  - [a]\n---\n",
            "---\nlist: [a, [b]]\n---\n",
            "---\nlist:\n  - a\n    - b\n---\n",
            "---\ntitle: \"unterminated\n---\n",
            "---\nkey:value\n---\n",
            "---\ntitle: x\n",
            "---\n  indented: x\n---\n",
        ]
        for text in bad:
            with self.assertRaises(FrontmatterError, msg=repr(text)):
                common.parse_frontmatter(text)

    def test_dump_rejects_non_strings(self):
        with self.assertRaises(TypeError):
            common.dump_frontmatter({"n": 1})
        with self.assertRaises(TypeError):
            common.dump_frontmatter({"l": [1]})

    def test_error_reason_code(self):
        try:
            common.parse_frontmatter("---\nx: {}\n---\n")
        except FrontmatterError as exc:
            self.assertEqual(exc.reason, "frontmatter_invalid")
        else:
            self.fail("expected FrontmatterError")


class PageFieldsTest(unittest.TestCase):
    def test_valid_project(self):
        fm, _ = common.parse_frontmatter(OBSIDIAN_PAGE)
        self.assertEqual(common.validate_page_frontmatter(fm), [])

    def test_invalid_fields(self):
        errors = common.validate_page_frontmatter({
            "title": "x", "type": "blog", "domain": "both", "aliases": "one",
            "updated": "05/11/2026",
        })
        joined = " | ".join(errors)
        for needle in ("type must", "domain must", "aliases must be a list", "updated must"):
            self.assertIn(needle, joined)

    def test_scope_and_decision_fields(self):
        self.assertEqual(common.validate_page_frontmatter(
            {"title": "p", "type": "pref", "domain": "work", "scope": "global"}), [])
        self.assertTrue(common.validate_page_frontmatter(
            {"title": "p", "type": "pref", "domain": "work", "scope": "everywhere"}))
        self.assertTrue(common.validate_page_frontmatter(
            {"title": "p", "type": "note", "domain": "work", "scope": "global"}))
        self.assertTrue(common.validate_page_frontmatter(
            {"title": "p", "type": "note", "domain": "work", "decided": "2026-01-01"}))
        self.assertEqual(common.validate_page_frontmatter(
            {"title": "d", "type": "decision", "domain": "personal", "decided": "2026-01-01",
             "supersedes": ["personal/decisions/old"]}), [])
        self.assertIn("missing title", common.validate_page_frontmatter({"type": "note"}))


class SectionHelpersTest(unittest.TestCase):
    def test_split_my_notes_byte_exact(self):
        body = ("# t\n\n```\n## 내 메모\n```\n\n## 현재 상태\nx\n"
                "## 내 메모\r\n\r\n손으로 쓴 글  \n## 다른 제목\nmore")
        before, notes = common.split_my_notes(body)
        self.assertEqual(before + notes, body)
        self.assertTrue(notes.startswith("## 내 메모\r\n"))
        self.assertTrue(notes.endswith("## 다른 제목\nmore"))
        self.assertIn("```\n## 내 메모\n```", before)

    def test_split_my_notes_missing(self):
        self.assertEqual(common.split_my_notes("# t\n"), ("# t\n", ""))

    def test_my_notes_subsection(self):
        notes = ("## 내 메모\n공통 글\n\n### work\n회사 메모\n\n### personal\n개인 메모\n")
        self.assertEqual(common.my_notes_subsection(notes, "work"), "회사 메모\n\n")
        self.assertEqual(common.my_notes_subsection(notes, "personal"), "개인 메모\n")
        self.assertNotIn("공통", common.my_notes_subsection(notes, "personal"))

    def test_src_marker(self):
        marker = common.format_src("mem:proj/feedback_x.md", "2026-11-04")
        self.assertEqual(marker, "<!-- src: mem:proj/feedback_x.md @2026-11-04 -->")
        match = common.SRC_COMMENT_RE.search("text " + marker)
        self.assertEqual(match.groups(), ("mem:proj/feedback_x.md", "2026-11-04"))
        for bad_id, bad_date in (("no kind", "2026-01-01"), ("mem:x", "2026-1-1"),
                                 ("mem:a-->b", "2026-01-01")):
            with self.assertRaises(ValueError):
                common.format_src(bad_id, bad_date)


if __name__ == "__main__":
    unittest.main()
