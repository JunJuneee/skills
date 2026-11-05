"""Regression tests for fix round 1: home-folder names outside work_terms,
short-chunk path tokens, src ids exempt only when known, hidden '## 내 메모'
headings, fence-aware notes subsections, CommonMark fence lengths, D10
expiry of undated lines, and the user rules folder guard. Temp dirs and
synthetic fixtures only; secret-looking strings are assembled at runtime."""

import os
import random
import unittest

import _helpers
import absorb
import common
import prepare
import redact
import test_verify as tv
import verify

NOW = tv.NOW


def j(*parts):
    return "".join(parts)


def rand(seed, alphabet, size):
    rng = random.Random(seed)
    return "".join(rng.choice(alphabet) for _ in range(size))


HEX = "0123456789abcdef"
ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


# ---------------------------------------------------------------------------
# (d) home folder names never count as work_terms
# ---------------------------------------------------------------------------

class HomeTermsTest(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        self.word = j("acme", "co")
        self.user_home = os.path.join(self.tmp, "Users", self.word)
        os.makedirs(os.path.join(self.user_home, "Desktop", "side-hobby"))

    def resolver(self):
        return prepare.Resolver({"owners": {}, "work_terms": [self.word]},
                                remote_fn=lambda cwd: [], home=self.user_home)

    def test_strip_home_absolute_encoded_and_boundary(self):
        home = self.user_home
        self.assertEqual(common.strip_home(home + "/Desktop/x", home), "~/Desktop/x")
        encoded = prepare.fs_encode(home) + "-Desktop-side-hobby"
        self.assertEqual(common.strip_home(encoded, home), "~-Desktop-side-hobby")
        sibling = home + "corp/x"
        self.assertEqual(common.strip_home(sibling, home), sibling)
        self.assertEqual(common.strip_home(prepare.fs_encode(sibling), home),
                         prepare.fs_encode(sibling))

    def test_memory_folder_under_home_without_remote_stays_unresolved(self):
        cwd = os.path.join(self.user_home, "Desktop", "side-hobby")
        paths = prepare.SourcePaths(os.path.join(self.tmp, "projects"), None, None, None, None,
                                    None)
        item = {"folder": prepare.fs_encode(cwd), "text": "장보기 목록"}
        self.assertEqual(prepare.resolve_memory(item, paths, self.resolver()), (None, None))
        # The rest of the path still counts, and so does the text.
        work_cwd = os.path.join(self.user_home, "Desktop", self.word + "-api")
        item = {"folder": prepare.fs_encode(work_cwd), "text": "x"}
        self.assertEqual(prepare.resolve_memory(item, paths, self.resolver()),
                         ("work", "work_terms"))
        item = {"folder": prepare.fs_encode(cwd), "text": "%s 배포" % self.word}
        self.assertEqual(prepare.resolve_memory(item, paths, self.resolver()),
                         ("work", "work_terms"))

    def test_prompts_from_home_stay_unresolved(self):
        records = []
        for cwd in (self.user_home, os.path.join(self.user_home, "Desktop", "side-hobby")):
            records.append({"ts": len(records), "date": "2026-11-05",
                            "time": "10:0%d" % len(records), "label": "x", "cwd": cwd,
                            "epic": None, "text": "점심 메뉴"})
        items = prepare.build_prompt_items(records, self.resolver(), None)
        self.assertEqual([item["id"] for item in items], ["prompts:unresolved/2026-11-05"])

    def test_quoted_home_path_is_not_a_work_term(self):
        terms = prepare.TermMatcher([self.word], home=self.user_home)
        self.assertFalse(terms.hits("메모 위치: %s/notes/a.md" % self.user_home))
        self.assertTrue(terms.hits("%s 회의" % self.word))
        vterms = verify.Terms([self.word], home=self.user_home)
        self.assertFalse(vterms.hits("경로 %s/Desktop" % self.user_home))
        self.assertTrue(vterms.hits("%s 회의" % self.word))


# ---------------------------------------------------------------------------
# Items 6 and 8/10: short chunks inside path-shaped candidates
# ---------------------------------------------------------------------------

class ShortChunkPathTest(unittest.TestCase):
    def test_reported_probe_tokens_are_redacted(self):
        chunks = [j("Kq7", "Z"), j("p2W", "m"), j("9Xr", "4"), j("Tn8", "L"), j("v3H", "b"),
                  j("6Jd", "1")]
        texts = [
            "x/" + "-".join(["ab", "cd", "ef", "gh", "ij", "kl", "mn", "op", "qr", "st"]),
            "x/" + "-".join(["abcd", "efgh", "ijkl", "mnop", "qrst", "uvwx"]),
            "/tmp/" + "-".join([j("Qx7", "z"), j("Lm9", "P"), j("aB3", "k"), j("Zt8", "W"),
                                j("Rr2", "Y"), j("Kp5", "N")]),
            "see /%s/x" % "-".join(chunks),
            "/srv/" + "/".join(chunks),
            "~/%s.md" % "_".join(chunks),
        ]
        for text in texts:
            self.assertTrue(redact.scan(text), text)

    def test_split_hex_keys_are_redacted(self):
        a, b, c = rand(1, HEX, 16), rand(2, HEX, 16), rand(3, HEX, 16)
        for text in ("/opt/%s-%s" % (a, b), "/opt/%s_%s" % (a, b), "/k/%s-%s-%s" % (a, b, c),
                     "/a/%s/%s" % (a, b), "%s_%s" % (a, b)):
            self.assertEqual(redact.scan(text), {"hex": 1}, text)

    def test_measured_shapes_regression(self):
        upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        lower = "abcdefghijklmnopqrstuvwxyz"
        shapes = (
            ("/k/", "-", ALNUM, 6),
            ("/srv/", "/", ALNUM, 6),
            ("notes/", "-", lower, 6),
            ("/k/", "-", upper, 5),
            ("https://h.example/", "-", lower + lower.upper(), 6),
        )
        rng = random.Random(20261106)
        for prefix, sep, alphabet, count in shapes:
            total = passed = 0
            for _ in range(200):
                token = sep.join("".join(rng.choice(alphabet) for _ in range(4))
                                 for _ in range(count))
                if redact.shannon_entropy(token) < redact.ENTROPY_THRESHOLD:
                    continue
                total += 1
                passed += not redact.scan("see %s%s now" % (prefix, token))
            self.assertGreater(total, 20, prefix)
            self.assertLessEqual(passed, total // 20, (prefix, passed, total))

    def test_real_shapes_still_pass(self):
        folder = j("-Users-someone--traycer-worktrees-acme--tools-", "tools-quiet-otter-",
                   "0123456789ab")
        uuid = j("1b4e28ba-2fa1-11d2", "-883f-0016d3cca427")
        for text in ("/home/someone/projects/demo-tools-lucky-fox-4c2e9a1b7d3f/skills",
                     "~/.traycer/worktrees/acme__tools/tools-quiet-otter-0123456789ab/skills",
                     "~/.claude/projects/%s/memory/a.md" % folder,
                     "/x/projects/%s/%s.jsonl" % (folder, uuid),
                     "/x/session-%s/a" % uuid,
                     "/home/someone/.claude/projects/foo/bar-0123456789ab",
                     "Sources/AppFeature/UserProfileSettingsPanel.swift",
                     "~/.claude/handoff/2026-11-05_sample-tools-workflow-v2-0123456789ab.md"):
            self.assertEqual(redact.scan(text), {}, text)


# ---------------------------------------------------------------------------
# src ids are exempt only when the caller knows them
# ---------------------------------------------------------------------------

def _sec():
    return "-".join([rand(11, ALNUM, 10), rand(12, ALNUM, 10), rand(13, ALNUM, 10)])


class KnownSrcIdTest(tv.RepoCase):
    def test_unknown_src_id_is_text(self):
        sec = _sec()
        comment = "<!-- src: mem:%s @2026-11-01 -->" % sec
        self.assertEqual(redact.scan(sec), {"entropy": 1})
        self.assertEqual(redact.scan(comment), {"entropy": 1})
        self.assertEqual(redact.scan(comment, known_ids=["mem:other/a.md"]), {"entropy": 1})
        self.assertIn("[REDACTED:entropy]", redact.redact(comment).text)

    def test_known_src_id_still_passes(self):
        folder = j("-Users-someone--traycer-worktrees-acme--tools-", "tools-quiet-otter-",
                   "0123456789ab")
        source_id = "mem:%s/sample-review-board.md" % folder
        comment = "<!-- src: %s @2026-11-01 -->" % source_id
        self.assertEqual(redact.scan(comment), {"entropy": 1})
        self.assertEqual(redact.scan(comment, known_ids=[source_id]), {})

    def test_unknown_src_id_in_summary_or_draft_fails_the_batch(self):
        comment = "<!-- src: mem:%s @2026-11-01 -->" % _sec()
        path = os.path.join(self.wt, "personal", "notes", "a.md")
        tv.write(path, tv.page("a", fm_extra="summary: '%s'\n" % comment,
                               body="## 요약\n\n내용\n<!-- src: mem:x/a.md @2026-11-04 -->\n"))
        self.assert_fails("secret_found")
        os.remove(path)
        tv.write(os.path.join(self.wt, "personal", "_drafts", "now.md"), "- 지금\n%s\n" % comment)
        self.assert_fails("secret_found")

    def test_prepare_redacts_an_unknown_src_id_in_source_text(self):
        sec = _sec()
        text = "메모\n<!-- src: mem:%s @2026-11-01 -->\n" % sec
        self.assertNotIn(sec, redact.redact(text, (), {"mem:x/a.md"}).text)

    def test_scan_tree_uses_known_ids(self):
        folder = j("-Users-someone--traycer-worktrees-acme--tools-", "tools-quiet-otter-",
                   "0123456789ab")
        source_id = "mem:%s/a.md" % folder
        tv.write(os.path.join(self.wt, "personal", "notes", "a.md"),
                 tv.page("a", body="## 요약\n\n내용\n<!-- src: %s @2026-11-04 -->\n" % source_id))
        self.assertTrue(verify.scan_tree(self.wt, []))
        self.assertEqual(verify.scan_tree(self.wt, [], {source_id}), [])


# ---------------------------------------------------------------------------
# (a) a page whose '## 내 메모' heading is hidden by an open fence
# ---------------------------------------------------------------------------

class HiddenNotesTest(tv.RepoCase):
    def setUp(self):
        tv.RepoCase.setUp(self)
        self.path = os.path.join(self.wt, "personal", "notes", "human.md")
        body = "## 요약\n\n내용\n<!-- src: mem:x/a.md @2026-11-04 -->\n\n```\npasted code\n"
        self.human = tv.page("human", body=body, notes="## 내 메모\n\n- 사람이 쓴 글\n")
        tv.write(self.path, self.human)
        self.commit()
        self.base = verify.head_sha(self.wt)

    def test_hidden_heading_is_detected(self):
        self.assertTrue(verify.notes_hidden(self.human))
        self.assertEqual(verify.notes_tail(self.human), "")

    def test_rewriting_the_human_text_fails(self):
        tv.write(self.path, self.human.replace("사람이 쓴 글", "LLM이 바꾼 글"))
        self.assert_fails("my_notes_unlocatable")

    def test_deleting_the_page_fails(self):
        os.remove(self.path)
        self.assert_fails("my_notes_unlocatable")

    def test_python_edits_are_caught_by_the_snapshot(self):
        snap = verify.notes_snapshot(self.wt, ["personal/notes/human.md"])
        tv.write(self.path, self.human.replace("사람이 쓴 글", "링크 [[x]]"))
        with self.assertRaises(verify.BatchFailure) as caught:
            verify.assert_notes_unchanged(self.wt, snap)
        self.assertEqual(caught.exception.reason, "my_notes_changed")

    def test_frontmatter_only_change_passes(self):
        tv.write(self.path, self.human.replace("type: note\n", "type: note\nsummary: 요약\n"))
        self.check()


# ---------------------------------------------------------------------------
# NEW-1: fences in notes subsections and fence lengths
# ---------------------------------------------------------------------------

class FenceRulesTest(unittest.TestCase):
    def test_subsection_heading_inside_code_is_code(self):
        canary = j("WORK", "-CANARY-", "7f3a")
        notes = ("## 내 메모\n\n### work\n\n```\n### personal\n%s\n```\n\n"
                 "### personal\n\n개인 메모\n" % canary)
        personal = common.my_notes_subsection(notes, "personal")
        self.assertNotIn(canary, personal)
        self.assertEqual(personal.strip(), "개인 메모")
        self.assertIn(canary, common.my_notes_subsection(notes, "work"))

    def test_longer_fence_is_not_closed_by_a_shorter_one(self):
        body = ("## 요약\n\n````md\n예시:\n```\n## 내 메모\n```\n````\n\n"
                "## 내 메모\n\n- 진짜 메모\n")
        before, notes = common.split_my_notes(body)
        self.assertEqual(notes, "## 내 메모\n\n- 진짜 메모\n")
        self.assertTrue(verify.fences_balanced(body))
        self.assertNotIn("## 내 메모", verify.strip_fences(before))

    def test_fence_step_rules(self):
        fence, is_fence = common.fence_step(None, "````md\n")
        self.assertEqual((fence, is_fence), ("````", True))
        self.assertEqual(common.fence_step(fence, "```\n"), ("````", False))
        self.assertEqual(common.fence_step(fence, "~~~~~\n"), ("````", False))
        self.assertEqual(common.fence_step(fence, "````` \n"), (None, True))
        self.assertEqual(common.fence_step(None, "``` a`b\n"), (None, False))
        self.assertEqual(common.fence_step("~~~", "~~~ x\n"), ("~~~", False))


# ---------------------------------------------------------------------------
# D10: an undated line in 현재 상태 survives expiry
# ---------------------------------------------------------------------------

class HandoffExpiryUndatedTest(tv.RepoCase):
    def write_project(self, body):
        path = os.path.join(self.wt, "personal", "projects", "p.md")
        tv.write(path, tv.page("p", kind="project", body=body,
                               fm_extra="status: active\nsummary: 요약\nas_of: 2026-10-01\n"))
        return path

    def test_human_line_without_src_stays(self):
        path = self.write_project(
            "## 현재 상태\n\n- 사람이 적은 줄\n\n- 오래된 handoff\n"
            "<!-- src: handoff:a.md @2026-10-01 -->\n\n## 실측값과 함정\n\n- 함정\n")
        self.assertEqual(verify.expire_handoff_state(self.wt, NOW), ["personal/projects/p.md"])
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("- 사람이 적은 줄\n", text)
        self.assertNotIn("handoff:a.md", text)

    def test_reported_probe_keeps_the_human_line(self):
        path = self.write_project(
            "## 현재 상태\n\n- human line no src\n- x <!-- src: handoff:a.md @2026-10-01 -->\n\n"
            "## 실측값과 함정\n\n- 함정\n")
        verify.expire_handoff_state(self.wt, NOW)
        with open(path, encoding="utf-8") as handle:
            self.assertIn("- human line no src", handle.read())

    def test_all_stale_section_is_emptied(self):
        path = self.write_project(
            "## 현재 상태\n\n- 오래된 handoff\n<!-- src: handoff:a.md @2026-10-01 -->\n\n"
            "## 실측값과 함정\n\n- 함정\n")
        self.assertEqual(verify.expire_handoff_state(self.wt, NOW), ["personal/projects/p.md"])
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("## 현재 상태\n\n## 실측값과 함정", text)


# ---------------------------------------------------------------------------
# User rules folder guard: symlinks and the wiki's own file
# ---------------------------------------------------------------------------

class ForeignRulesTest(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        self.rules_dir = os.path.join(self.home, ".claude", "rules")
        os.makedirs(self.rules_dir)
        self.env = {"HOME": self.home}

    def write(self, path, text):
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_symlinked_folder_is_counted_and_loops_stop(self):
        shared = os.path.join(self.tmp, "shared")
        self.write(os.path.join(shared, "x.md"), "- 팀 규칙\n")
        os.symlink(shared, os.path.join(self.rules_dir, "team"))
        os.symlink(self.rules_dir, os.path.join(shared, "back"))
        self.assertEqual(absorb.foreign_user_rules(self.env), 1)

    def test_own_file_is_trusted_by_content_not_name(self):
        own = os.path.join(self.rules_dir, absorb.RULES_FILENAME)
        self.write(own, verify.rules_text(["- 답변은 짧게"]))
        self.assertEqual(absorb.foreign_user_rules(self.env), 0)
        self.write(own, "# 회사 규칙\n\n배포 전에 확인\n")
        self.assertEqual(absorb.foreign_user_rules(self.env), 1)
        os.remove(own)
        real = os.path.join(self.tmp, "elsewhere.md")
        self.write(real, verify.rules_text(["- 답변은 짧게"]))
        os.symlink(real, own)
        self.assertEqual(absorb.foreign_user_rules(self.env), 1)

    def test_rules_path_does_not_hide_a_foreign_file(self):
        team = os.path.join(self.rules_dir, "team.md")
        self.write(team, "- 팀 규칙\n")
        self.assertEqual(absorb.foreign_user_rules(self.env), 1)
        self.assertEqual(absorb.foreign_user_rules(self.env, rules_path=team), 1)
        self.write(team, verify.rules_text(["- 답변은 짧게"]))
        self.assertEqual(absorb.foreign_user_rules(self.env, rules_path=team), 0)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Item 9/(e): the opt-in isolation probe's verdict logic, with a fake claude
# ---------------------------------------------------------------------------

FAKE_CLAUDE = r'''#!%s
import json, os, sys, urllib.request
if "--version" in sys.argv:
    print("0.0.0 (fake)")
    sys.exit(0)
sys.stdin.read()
config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.environ["HOME"], ".claude")
isolated = "--setting-sources" in sys.argv or os.environ.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS")
parts = []
leak = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "leak"))
if not isolated or leak:
    for dirpath, dirnames, filenames in os.walk(os.path.join(config, "rules"), followlinks=True):
        parts += [open(os.path.join(dirpath, n)).read() for n in filenames]
if not isolated:
    parts.append(open(os.path.join(config, "CLAUDE.md")).read())
body = json.dumps({"system": "\n".join(parts)}).encode()
request = urllib.request.Request(os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages", data=body)
try:
    urllib.request.urlopen(request, timeout=10)
except Exception:
    pass
sys.exit(1)
'''


class IsolationProbeTest(_helpers.TempHomeCase):
    def fake(self):
        import stat
        import sys
        import isolation_probe
        path = os.path.join(self.tmp, "bin", "claude")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(FAKE_CLAUDE % sys.executable)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return isolation_probe, path

    def test_hidden_inconclusive_and_leak(self):
        probe, claude = self.fake()
        report = probe.measure(claude)
        verdicts = report["variants"]["home"]["verdicts"]
        self.assertEqual(verdicts["user_claude_md"], "hidden")
        self.assertEqual(verdicts["user_rules_symlinked"], "hidden")
        # The fake never reads auto-memory: the control did not see it.
        self.assertEqual(verdicts["auto_memory"], "INCONCLUSIVE")
        self.assertEqual(report["result"], "inconclusive")
        with open(os.path.join(os.path.dirname(claude), "leak"), "w") as handle:
            handle.write("")
        report = probe.measure(claude)
        self.assertEqual(report["variants"]["config_dir"]["verdicts"]["user_rules"], "LEAK")
        self.assertEqual(report["result"], "leak")
