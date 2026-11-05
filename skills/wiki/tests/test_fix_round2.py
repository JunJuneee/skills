"""Regression tests for fix round 2: unbalanced fences in root '## 내 메모'
subsections, random-letter words in path-shaped tokens, the short-parts
check on known src ids, provenance of the wiki's own rules file, and valid
request counts in the isolation probe. Temp dirs and synthetic fixtures
only; secret-looking strings are assembled at runtime."""

import json
import os
import random
import unittest

import _helpers
import absorb
import common
import prepare
import redact
import test_absorb as ta
import test_fix_round1 as tf1
import test_prepare as tp
import verify


def j(*parts):
    return "".join(parts)


LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


# ---------------------------------------------------------------------------
# Unbalanced fences in root '## 내 메모' subsections (both directions)
# ---------------------------------------------------------------------------

def notes_with_open_fence(first, second, canary):
    return ("## 내 메모\n\n### %s\n\nmine\n```\ncode\n\n### %s\n\n%s\n"
            % (first, second, canary))


class NotesFenceUnitTest(unittest.TestCase):
    def test_open_fence_in_personal_does_not_swallow_work(self):
        canary = j("WORK", "-CANARY-", "a1")
        notes = notes_with_open_fence("personal", "work", canary)
        self.assertTrue(common.my_notes_ambiguous(notes))
        self.assertEqual(common.my_notes_subsection(notes, "personal"), "")
        self.assertEqual(common.my_notes_subsection(notes, "work"), "")

    def test_open_fence_in_work_does_not_swallow_personal(self):
        canary = j("PERSONAL", "-CANARY-", "b2")
        notes = notes_with_open_fence("work", "personal", canary)
        self.assertEqual(common.my_notes_subsection(notes, "work"), "")
        self.assertEqual(common.my_notes_subsection(notes, "personal"), "")

    def test_fence_closed_in_the_next_subsection_is_ambiguous(self):
        canary = j("WORK", "-CANARY-", "c3")
        notes = ("## 내 메모\n\n### personal\n\n```\nx\n\n### work\n\n%s\n```\n" % canary)
        self.assertTrue(common.my_notes_ambiguous(notes))
        self.assertEqual(common.my_notes_subsection(notes, "personal"), "")

    def test_heading_two_inside_a_fence_is_ambiguous(self):
        notes = "## 내 메모\n\n### personal\n\n```\n## 다른 제목\n```\n개인\n"
        self.assertTrue(common.my_notes_ambiguous(notes))
        self.assertEqual(common.my_notes_subsection(notes, "personal"), "")

    def test_balanced_code_stays_with_its_domain(self):
        notes = ("## 내 메모\n\n### personal\n\n```\n### 예시\n```\n개인\n\n### work\n\n업무\n")
        self.assertFalse(common.my_notes_ambiguous(notes))
        self.assertEqual(common.my_notes_subsection(notes, "personal"),
                         "\n```\n### 예시\n```\n개인\n\n")
        self.assertEqual(common.my_notes_subsection(notes, "work"), "\n업무\n")


class NotesFencePrepareTest(tp.PrepareCase):
    def edit_now(self, fn):
        path = os.path.join(self.root, "now.md")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(fn(text))

    def contexts(self):
        out = {}
        for record in prepare.load_prepare(self.root)["batches"].values():
            texts = []
            for rel in record.get("context") or []:
                with open(os.path.join(self.root, ".state", rel), encoding="utf-8") as handle:
                    texts.append(handle.read())
            out[record["domain"]] = "\n".join(texts)
        return out

    def test_no_domain_is_staged_and_the_page_warns(self):
        work_canary = j("WORK", "-CANARY-", "d4")
        personal_canary = j("PERSONAL", "-CANARY-", "e5")
        self.edit_now(lambda text: text.replace(
            "### personal\n", "### personal\n\n%s\n```\nunclosed\n" % personal_canary).replace(
            "### work\n", "### work\n\n%s\n" % work_canary))
        warnings = []
        self.assertEqual(prepare.discover_root_notes(self.root, warnings), [])
        self.assertIn("my_notes_unbalanced_fence:now.md", warnings)
        self.add_inbox("personal", "p.md", "개인")
        self.add_inbox("work", "w.md", "업무")
        self.run_prepare()
        self.assertIn("my_notes_unbalanced_fence:now.md",
                      prepare.load_prepare(self.root)["summary"]["warnings"])
        ids = sorted(source["id"] for source in self.all_sources())
        self.assertEqual(ids, ["inbox:personal/p.md", "inbox:work/w.md"])
        contexts = self.contexts()
        self.assertEqual(sorted(contexts), ["personal", "work"])
        for text in contexts.values():
            self.assertNotIn(work_canary, text)
            self.assertNotIn(personal_canary, text)

    def test_recorded_notes_source_is_held_not_deleted(self):
        self.edit_now(lambda text: text.replace("### personal\n", "### personal\n\n개인 메모\n"))
        self.run_prepare()
        self.assertEqual([s["id"] for s in self.all_sources()], ["notes:personal/now.md"])
        self.commit_all()
        self.edit_now(lambda text: text.replace("개인 메모\n", "개인 메모\n```\n"))
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])  # no 'deleted' op retracts the draft
        entry = self.sources_json()["notes:personal/now.md"]
        self.assertEqual(entry["status"], prepare.STATUS_ACTIVE)


# ---------------------------------------------------------------------------
# Items 6, 8/10: random-letter words inside path-shaped tokens
# ---------------------------------------------------------------------------

def _cap(rng, size):
    return rng.choice(LOWER).upper() + "".join(rng.choice(LOWER) for _ in range(size - 1))


def _low(rng, size):
    return "".join(rng.choice(LOWER) for _ in range(size))


SHAPES = (
    ("a/ + 5 Capitalized 6-letter, /", lambda r: "a/" + "/".join(_cap(r, 6) for _ in range(5))),
    ("a/ + 5 Capitalized 6-letter, -", lambda r: "a/" + "-".join(_cap(r, 6) for _ in range(5))),
    ("a/ + 5 Capitalized 6-letter, _", lambda r: "a/" + "_".join(_cap(r, 6) for _ in range(5))),
    ("docs/ + 3x8 lower", lambda r: "docs/" + "-".join(_low(r, 8) for _ in range(3))),
    ("/x/ + 3x8 lower", lambda r: "/x/" + "-".join(_low(r, 8) for _ in range(3))),
    ("a-b/c-d 8-letter", lambda r: "%s-%s/%s-%s" % tuple(_low(r, 8) for _ in range(4))),
    ("/k/ + 5x4 upper+digit", lambda r: "/k/" + "-".join(
        "".join(r.choice(UPPER_DIGITS) for _ in range(4)) for _ in range(5))),
)


def _random_part(text):
    """The random part after the fixed prefix (its entropy is the filter)."""
    if text.startswith("/"):
        return text.split("/", 2)[2]
    if text.startswith(("a/", "docs/")):
        return text.split("/", 1)[1]
    return text


class PathWordsRound2Test(unittest.TestCase):
    def test_measured_shapes_regression(self):
        for name, make in SHAPES:
            rng = random.Random(20261107)
            total = passed = 0
            for _ in range(400):
                text = make(rng)
                if redact.shannon_entropy(_random_part(text)) < redact.ENTROPY_THRESHOLD:
                    continue
                total += 1
                passed += not redact.scan("see %s now" % text)
            self.assertGreater(total, 40, name)
            self.assertLessEqual(passed, total // 50, (name, passed, total))

    def test_natural_paths_with_odd_words_still_pass(self):
        for text in (
                "~/.traycer/worktrees/acme__tools/fix-abc-526-review-20261104/packages/db/test",
                "~/.traycer/worktrees/someone__river-walks/verify-pr20-cold-offline-20261104/"
                "packages/db/test/keyword-ids.test.ts",
                "/home/someone/projects/sqlite-markdown-workflow/src/keyword_index.py",
                "worktrees/someone__river-walks/feat-abc-537-model-web-search/packages",
                "docs/playwright-dashboard-growth/thumbnail-download",
                "Sources/AppFeature/UserProfileSettingsPanel.swift"):
            self.assertEqual(redact.scan(text), {}, text)

    def test_pair_scores_separate_words_from_random_letters(self):
        rng = random.Random(5)
        for word in ("review", "skills", "projects", "feedback", "dashboard", "settings"):
            score, count = redact._pair_score(word)
            self.assertGreaterEqual(score, 0, word)
            self.assertEqual(count, len(word) - 1)
        below = 0
        for _ in range(200):
            score, _count = redact._pair_score(_low(rng, 24))
            below += score < 0
        self.assertGreater(below, 190)


# ---------------------------------------------------------------------------
# A known src id gets the short-parts check before its exemption
# ---------------------------------------------------------------------------

class KnownSrcIdShortPartsTest(unittest.TestCase):
    def test_short_chunk_token_in_a_known_id_is_caught(self):
        rng = random.Random(77)
        alnum = LOWER + LOWER.upper() + "0123456789"
        token = None
        while token is None or redact.shannon_entropy(token) < redact.ENTROPY_THRESHOLD:
            token = "-".join("".join(rng.choice(alnum) for _ in range(4)) for _ in range(6))
        self.assertEqual(redact.scan("see %s now" % token), {"entropy": 1})
        source_id = "mem:x/%s.md" % token
        comment = "<!-- src: %s @2026-11-01 -->" % source_id
        self.assertEqual(redact.scan(comment, known_ids=[source_id]), {"entropy": 1})
        self.assertNotIn(token, redact.redact(comment, (), [source_id]).text)

    def test_macos_temp_folder_id_still_passes(self):
        user_id = j("k3vq8tz1mw4p", "_x7rn2yb9df0000gn")
        for spelling in (user_id, user_id.replace("_", "-")):
            folder = j("-private-var-folders-7h-", spelling, "-T-wiki-test-41-2-repos-side")
            source_id = "mem:%s/feedback_lang.md" % folder
            comment = "<!-- src: %s @2026-11-01 -->" % source_id
            self.assertEqual(redact.scan(comment, known_ids=[source_id]), {})

    def test_dashed_chunks_in_the_temp_folder_slot_are_caught(self):
        chunks = "-".join([j("kq7", "z"), j("p2w", "m"), j("9xr", "4"), j("tn8", "l"),
                           j("v3h", "b"), j("6jd", "1")])
        plain = "see /var/folders/ab/%s/T/x now" % chunks
        self.assertEqual(redact.scan(plain), {"entropy": 1})
        source_id = "mem:-private-var-folders-ab-%s-T-x/a.md" % chunks
        comment = "<!-- src: %s @2026-11-01 -->" % source_id
        self.assertEqual(redact.scan(comment, known_ids=[source_id]), {"entropy": 1})

    def test_natural_known_id_still_passes(self):
        folder = j("-Users-someone--traycer-worktrees-acme--tools-", "tools-quiet-otter-",
                   "0123456789ab")
        source_id = "mem:%s/sample-review-board.md" % folder
        comment = "<!-- src: %s @2026-11-01 -->" % source_id
        self.assertEqual(redact.scan(comment, known_ids=[source_id]), {})


class SourceIdSecretPrepareTest(tp.PrepareCase):
    def test_id_with_short_chunk_token_stays_out_of_batches(self):
        rng = random.Random(78)
        alnum = LOWER + LOWER.upper() + "0123456789"
        token = None
        while token is None or redact.shannon_entropy(token) < redact.ENTROPY_THRESHOLD:
            token = "-".join("".join(rng.choice(alnum) for _ in range(4)) for _ in range(6))
        repo = self.make_repo(token, "git@github.com:%s/side.git" % tp.ME)
        self.add_memory(self.project_folder(repo), "feedback_x.md", "답변은 짧게",
                        jsonl_cwd=repo)
        plain = self.make_repo("plain", "git@github.com:%s/plain.git" % tp.ME)
        self.add_memory(self.project_folder(plain), "feedback_y.md", "보고는 숫자로",
                        jsonl_cwd=plain)
        self.run_prepare()
        ids = [source["id"] for source in self.all_sources()]
        self.assertEqual(len(ids), 1, ids)
        self.assertIn("plain", ids[0])
        self.assertNotIn(token, json.dumps(self.run_json()))
        self.assertIn("source_id_secret:1", prepare.load_prepare(self.root)["summary"]["warnings"])


# ---------------------------------------------------------------------------
# NEW-2: the wiki's own rules file is trusted by provenance and content
# ---------------------------------------------------------------------------

class OwnRulesProvenanceTest(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        self.rules_dir = os.path.join(self.home, ".claude", "rules")
        os.makedirs(self.rules_dir)
        self.env = {"HOME": self.home}
        self.own = os.path.join(self.rules_dir, absorb.RULES_FILENAME)
        self.term = j("Acme", "Corp")
        self.terms = verify.Terms([self.term])

    def write(self, text):
        with open(self.own, "w", encoding="utf-8") as handle:
            handle.write(text)

    def count(self):
        return absorb.foreign_user_rules(self.env, None, self.root, self.terms)

    def test_same_shape_with_a_work_canary_is_foreign(self):
        lines = ["- %s 배포 전에 확인" % self.term]
        self.write(verify.rules_text(lines))
        absorb.record_rules_write(self.root, self.own, lines)
        self.assertEqual(self.count(), 1)

    def test_same_shape_without_a_record_is_foreign(self):
        self.write(verify.rules_text(["- 답변은 짧게"]))
        self.assertEqual(self.count(), 1)
        self.assertEqual(absorb.foreign_user_rules(self.env), 1)  # no root: nothing trusted

    def test_edited_after_absorb_wrote_it_is_foreign(self):
        lines = ["- 답변은 짧게"]
        self.write(verify.rules_text(lines))
        absorb.record_rules_write(self.root, self.own, lines)
        self.assertEqual(self.count(), 0)
        self.write(verify.rules_text(lines + ["- 배포는 금요일에"]))
        self.assertEqual(self.count(), 1)

    def test_record_is_private(self):
        absorb.record_rules_write(self.root, self.own, ["- 답변은 짧게"])
        path = os.path.join(common.state_dir(self.root), absorb.RULES_RECORD)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(list(json.load(handle)), [os.path.realpath(self.own)])


class OwnRulesAbsorbTest(ta.AbsorbCase):
    def test_rules_absorb_wrote_are_trusted_even_when_unchanged(self):
        self.rules = os.path.join(self.home, ".claude", "rules", absorb.RULES_FILENAME)
        terms = verify.Terms([ta.TERM])
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        report = self.run_absorb(ta.Runner(ta.writes_pref()))
        self.assertEqual((report["rules_added"], report["rules_removed"]), (1, 0), report)
        self.assertEqual(absorb.foreign_user_rules(self.env, None, self.root, terms), 0)
        os.remove(os.path.join(common.state_dir(self.root), absorb.RULES_RECORD))
        self.assertEqual(absorb.foreign_user_rules(self.env, None, self.root, terms), 1)
        self.add_memory(self.work_repo, "feedback_w.md", "리뷰는 짧게.")

        def fn(request):
            source = request["sources"][0]
            path = os.path.join(request["cwd"], "prefs", "w.md")
            ta.write(path, ta.pref_page("리뷰", (source["id"], source["date"]), scope="domain",
                                        domain=request["domain"]))
            return ta.result([path])

        report = self.run_absorb(ta.Runner(fn))
        self.assertEqual((report["rules_added"], report["rules_removed"]), (0, 0), report)
        self.assertEqual(absorb.foreign_user_rules(self.env, None, self.root, terms), 0)


# ---------------------------------------------------------------------------
# Isolation probe: a run without a valid model request decides nothing
# ---------------------------------------------------------------------------

class IsolationProbeRequestsTest(_helpers.TempHomeCase):
    fake = tf1.IsolationProbeTest.fake

    def test_absorb_run_without_requests_is_inconclusive(self):
        probe, claude = self.fake()
        with open(os.path.join(os.path.dirname(claude), "silent"), "w") as handle:
            handle.write("")
        report = probe.measure(claude)
        for variant in report["variants"].values():
            self.assertEqual(variant["runs"]["absorb"]["valid"], 0)
            self.assertEqual(variant["runs"]["absorb"]["exit"], 7)
            self.assertGreater(variant["runs"]["control"]["valid"], 0)
            self.assertEqual(set(variant["verdicts"].values()), {"INCONCLUSIVE"})
        self.assertEqual(report["result"], "inconclusive")

    def test_valid_request_needs_messages_with_the_prompt(self):
        import isolation_probe as probe
        good = json.dumps({"messages": [{"role": "user", "content": probe.PROMPT}]}).encode()
        self.assertTrue(probe.valid_request("/v1/messages", good))
        self.assertTrue(probe.valid_request("/v1/messages?beta=true", good))
        self.assertFalse(probe.valid_request("/v1/messages/count_tokens", good))
        self.assertFalse(probe.valid_request("/v1/messages", b"{}"))
        self.assertFalse(probe.valid_request("/v1/messages", json.dumps(
            {"messages": [{"role": "user", "content": "hi"}]}).encode()))
        self.assertFalse(probe.valid_request("/v1/messages", b"not json"))


if __name__ == "__main__":
    unittest.main()
