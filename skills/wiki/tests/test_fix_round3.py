"""Regression tests for fix round 3: romanized-Korean words in file paths
(I-1), CommonMark heading variants in root '## 내 메모' subsections (I-2),
IAM action names and placeholders in assignments, and failed-batch draft
retention (I-3). Temp dirs and synthetic fixtures only; secret-looking
strings are assembled at runtime."""

import json
import os
import random
import unittest
from unittest import mock

import _helpers  # noqa: F401
import absorb
import common
import prepare
import redact
import test_absorb as ta
import test_prepare as tp
import verify


def j(*parts):
    return "".join(parts)


LOWER = "abcdefghijklmnopqrstuvwxyz"

# Synthetic Revised Romanization syllable parts (I-1 fixtures).
RR_I = ["g", "n", "d", "r", "m", "b", "s", "j", "ch", "k", "t", "p", "h", "", "", "kk", "ss"]
RR_V = ["a", "eo", "o", "u", "eu", "i", "ae", "e", "ya", "yeo", "yo", "yu", "wa", "wi", "oe"]
RR_F = ["", "", "", "n", "ng", "k", "l", "m", "p"]


def rr_word(rng, low=2, high=3):
    return "".join(rng.choice(RR_I) + rng.choice(RR_V) + rng.choice(RR_F)
                   for _ in range(rng.randint(low, high)))


# ---------------------------------------------------------------------------
# I-1: romanized-Korean words in file paths
# ---------------------------------------------------------------------------

class RomanizedPathTest(unittest.TestCase):
    PATHS = (
        "docs/bokhye-iljeong-rokmin-sapyo.md",
        "./docs/bokhye-iljeong-rokmin-sapyo.md",
        "work/notes/yeonmal-jeongsan-chamgo-jaryo.md",
        "docs/hoeuirok/jeongmunseo-gyeoljae-sapyo.md",
        # CamelCase romanized names (each hump parses on its own)
        "src/BokhyeIljeong/RokminSapyo.tsx",
        "docs/JeongBokhye-KimRokmin-sapyo.md",
        "notes/HwangJiu_SongHyeok_gyeoljae.md",
        "Sources/BokhyeFeature/IljeongRokminView.swift",
    )

    def test_romanized_slugs_and_camel_case_names_are_paths(self):
        for path in self.PATHS:
            for text in (path, "see %s now" % path, "`%s`" % path):
                self.assertEqual(redact.scan(text), {}, text)
            self.assertEqual(redact.redact("see %s now" % path).text, "see %s now" % path)

    def test_generated_romanized_paths_pass(self):
        rng = random.Random(20261106)
        total = flagged = 0
        for _ in range(1500):
            words = [rr_word(rng) for _ in range(rng.randint(3, 4))]
            path = "docs/%s.md" % "-".join(words)
            if len(path) < 27:
                continue
            total += 1
            flagged += bool(redact.scan("see %s now" % path))
        self.assertGreater(total, 1000)
        self.assertLessEqual(flagged, total // 200, (flagged, total))

    def test_romanized_parser(self):
        for word in ("bokhye", "iljeong", "rokmin", "sapyo", "JeongMinsu", "Gyeoljae"):
            self.assertTrue(redact._romanized(word), word)
        for word in ("qwxzvb", "Zxcvbn", "JeongQwerty", "kqzvbnwm", "plxrtgfd", "abc1"):
            self.assertFalse(redact._romanized(word), word)

    def test_romanized_word_does_not_lift_random_neighbours(self):
        rng = random.Random(9)
        lucky = None
        while lucky is None:
            word = "".join(rng.choice(LOWER) for _ in range(8))
            if redact._romanized(word):
                lucky = word
        found = 0
        for _ in range(1000):
            others = []
            while len(others) < 2:
                word = "".join(rng.choice(LOWER) for _ in range(8))
                if not redact._romanized(word):
                    others.append(word)
            path = "docs/%s-%s-%s" % (lucky, others[0], others[1])
            if redact.shannon_entropy(path[5:]) < redact.ENTROPY_THRESHOLD:
                continue
            found += 1
            self.assertEqual(redact.scan("see %s now" % path), {"entropy": 1}, path)
        self.assertGreater(found, 15)

    def test_random_dashed_runs_are_still_caught(self):
        rng = random.Random(20261108)
        total = passed = 0
        for _ in range(600):
            path = "docs/" + "-".join("".join(rng.choice(LOWER) for _ in range(8))
                                      for _ in range(3))
            if redact.shannon_entropy(path[5:]) < redact.ENTROPY_THRESHOLD:
                continue
            total += 1
            passed += not redact.scan("see %s now" % path)
        self.assertGreater(total, 150)
        self.assertLessEqual(passed, total // 100, (passed, total))


class SourceIdSecretRecoveryTest(tp.PrepareCase):
    def test_redact_allow_entry_brings_the_source_back(self):
        rng = random.Random(81)
        alnum = LOWER + LOWER.upper() + "0123456789"
        token = None
        while token is None or redact.shannon_entropy(token) < redact.ENTROPY_THRESHOLD:
            token = "-".join("".join(rng.choice(alnum) for _ in range(4)) for _ in range(6))
        repo = self.make_repo(token, "git@github.com:%s/side.git" % tp.ME)
        self.add_memory(self.project_folder(repo), "feedback_x.md", "답변은 짧게",
                        jsonl_cwd=repo)
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])
        self.assertIn("source_id_secret:1", prepare.load_prepare(self.root)["summary"]["warnings"])
        self.write_domains(redact_allow=[token])
        self.run_prepare()
        ids = [source["id"] for source in self.all_sources()]
        self.assertEqual(len(ids), 1, ids)
        self.assertIn(token, ids[0])
        self.assertNotIn("source_id_secret:1",
                         prepare.load_prepare(self.root)["summary"]["warnings"])
        comment = "<!-- src: %s @2026-11-04 -->" % ids[0]
        self.assertEqual(redact.scan(comment, [token], ids), {})


# ---------------------------------------------------------------------------
# I-2: root '## 내 메모' headings read the way they render
# ---------------------------------------------------------------------------

def notes(first, first_text, heading, second_text):
    return "## 내 메모\n\n### %s\n\n%s\n\n%s\n\n%s\n" % (first, first_text, heading,
                                                        second_text)


class NotesHeadingVariantTest(unittest.TestCase):
    VARIANTS = ("   ### {d}", "###   {d}", "###\t{d}", "### {d} ###", "  ###  {d}  #", "### {d}   ")

    def test_variants_start_their_own_subsection_both_ways(self):
        for first, second in (("personal", "work"), ("work", "personal")):
            own = j(first.upper(), "-CANARY-", "f6")
            other = j(second.upper(), "-CANARY-", "g7")
            for variant in self.VARIANTS:
                text = notes(first, own, variant.format(d=second), other)
                self.assertFalse(common.my_notes_ambiguous(text), variant)
                mine = common.my_notes_subsection(text, first)
                theirs = common.my_notes_subsection(text, second)
                self.assertIn(own, mine, variant)
                self.assertNotIn(other, mine, variant)
                self.assertIn(other, theirs, variant)
                self.assertNotIn(own, theirs, variant)

    def test_misplaced_domain_headings_hold_back_every_domain(self):
        misplaced = ("#### {d}", "## {d}", "> ### {d}", "- ### {d}", "1. ### {d}",
                     "    ### {d}", "{d}\n---", "{d}\n===")
        for first, second in (("personal", "work"), ("work", "personal")):
            for heading in misplaced:
                text = notes(first, "mine", heading.format(d=second), j("CANARY", "-h8"))
                self.assertEqual(common.my_notes_ambiguity(text), "heading", heading)
                self.assertEqual(common.my_notes_subsection(text, first), "", heading)
                self.assertEqual(common.my_notes_subsection(text, second), "", heading)

    def test_non_headings_stay_text(self):
        for line in ("###work", "#work", "\\### work"):
            text = notes("work", "업무", line, "더")
            self.assertIsNone(common.my_notes_ambiguity(text), line)
            self.assertIn(line, common.my_notes_subsection(text, "work"))
        rule = notes("work", "업무", "---", "더")
        self.assertIn("더", common.my_notes_subsection(rule, "work"))

    def test_level_one_or_two_heading_ends_the_notes(self):
        canary = j("AFTER", "-CANARY-", "i9")
        for heading in ("# 다른 글", "## 다른 글", "  ##  다른 글 ##"):
            text = notes("work", "업무", heading, canary)
            self.assertNotIn(canary, common.my_notes_subsection(text, "work"), heading)
            later = text + "\n### personal\n\n개인\n"
            self.assertEqual(common.my_notes_subsection(later, "personal"), "", heading)

    def test_atx_heading(self):
        self.assertEqual(common.atx_heading("  ###  work  ##\n"), (3, "work"))
        self.assertEqual(common.atx_heading("### work#"), (3, "work#"))
        self.assertEqual(common.atx_heading("###"), (3, ""))
        self.assertIsNone(common.atx_heading("    ### work"))
        self.assertIsNone(common.atx_heading("###work"))
        self.assertIsNone(common.atx_heading("####### seven"))

    def test_notes_heading_variants_split_and_hide_alike(self):
        for heading in ("## 내 메모", "  ## 내 메모", "##  내 메모 ##", "##\t내 메모"):
            body = "# 제목\n\n본문\n\n%s\n\n내 글\n" % heading
            before, tail = common.split_my_notes(body)
            self.assertEqual(before, "# 제목\n\n본문\n\n", heading)
            self.assertTrue(tail.startswith(heading), heading)
            hidden = "# 제목\n\n```\n%s\n\n내 글\n" % heading
            self.assertTrue(verify.notes_hidden(hidden), heading)
            self.assertFalse(verify.root_assemblable(hidden), heading)


class NotesHeadingPrepareTest(tp.PrepareCase):
    def edit_now(self, fn):
        path = os.path.join(self.root, "now.md")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(fn(text))

    def test_variant_heading_is_staged_under_its_domain(self):
        work_canary = j("WORK", "-CANARY-", "j1")
        personal_canary = j("PERSONAL", "-CANARY-", "k2")
        self.edit_now(lambda text: text.replace(
            "### personal\n", "### personal\n\n%s\n" % personal_canary).replace(
            "### work\n", "  ###  work ##\n\n%s\n" % work_canary))
        items = dict((item["id"], item["text"])
                     for item in prepare.discover_root_notes(self.root, []))
        self.assertIn(work_canary, items["notes:work/now.md"])
        self.assertNotIn(personal_canary, items["notes:work/now.md"])
        self.assertIn(personal_canary, items["notes:personal/now.md"])
        self.assertNotIn(work_canary, items["notes:personal/now.md"])

    def test_misplaced_heading_warns_and_stages_nothing(self):
        self.edit_now(lambda text: text.replace(
            "### personal\n", "### personal\n\n개인\n\n> ### work\n\n%s\n"
            % j("WORK", "-CANARY-", "l3")))
        warnings = []
        self.assertEqual(prepare.discover_root_notes(self.root, warnings), [])
        self.assertIn("my_notes_misplaced_heading:now.md", warnings)


# ---------------------------------------------------------------------------
# I-3: the assignments that failed the real batch are names and placeholders
# ---------------------------------------------------------------------------

class AssignmentRound3Test(unittest.TestCase):
    def test_iam_names_and_placeholders_are_not_secrets(self):
        for text in ("pod 정책에 `secretsmanager:GetSecretValue`가 없다",
                     '"Action": ["secretsmanager:GetSecretValue", "secretsmanager:Describe*"]',
                     "arn:aws:secretsmanager:ap-northeast-2:111122223333:secret:app/db-AbCdEf",
                     "`SAMPLE_API_TOKEN=REPLACE_ME`면 배포가 롤백된다",
                     "SAMPLE_API_TOKEN: REPLACE_ME", "API_KEY=your_api_key", "token = CHANGE_ME"):
            self.assertEqual(redact.scan(text), {}, text)

    def test_real_values_are_still_caught_and_backticks_kept(self):
        value = j("hunter", "22", "xq")
        cases = (("password: `%s`" % value, "password: `[REDACTED:assign]`"),
                 ("`password=%s` 확인" % value, "`password=[REDACTED:assign]` 확인"),
                 ("secretsmanager:%s" % value, "secretsmanager:[REDACTED:assign]"),
                 ("SAMPLE_API_TOKEN=%s" % value, "SAMPLE_API_TOKEN=[REDACTED:assign]"))
        for text, expected in cases:
            self.assertEqual(redact.redact(text).text, expected, text)


class AssignmentAbsorbTest(ta.AbsorbCase):
    def test_page_with_iam_action_and_placeholder_merges(self):
        self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")
        body = ("`SAMPLE_API_TOKEN=REPLACE_ME`면 롤백되고, 정책에 "
                "`secretsmanager:GetSecretValue`가 없다.")

        def page(title, src):
            return ta.page_text(title, "pref", "personal",
                                [("선호", "답변은 짧게"), ("Why", body), ("How to apply", "항상")],
                                src=src, extra=[("scope", "global"), ("summary", "답변은 짧게")])
        report = self.run_absorb(ta.Runner(ta.writes_pref(page_fn=page)))
        self.assertEqual(report["status"], "ok", report)
        self.assertTrue(report["batches"][0]["ok"], report["batches"][0])
        self.assertIn("secretsmanager:GetSecretValue",
                      self.main_file("personal/prefs/answer-language.md"))


# ---------------------------------------------------------------------------
# I-3: a failed batch's draft is kept, redacted, under .state/failed/
# ---------------------------------------------------------------------------

class FailedDraftTest(ta.AbsorbCase):
    def setUp(self):
        ta.AbsorbCase.setUp(self)
        self.src_id = self.add_memory(self.repo, "feedback_lang.md", "답변은 한국어로.")

    def failed_root(self):
        return os.path.join(self.root, ".state", absorb.FAILED_DIR)

    def test_secret_draft_is_kept_redacted_and_private(self):
        token = j("gh", "p_", "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2")
        report = self.run_absorb(ta.Runner(ta.writes_pref(
            page_fn=lambda t, s: ta.pref_page(t, s, summary="키 " + token))))
        batch = report["batches"][0]
        self.assertEqual(batch["reason"], "secret_found")
        self.assertIn("failed_draft_kept", batch["warnings"])
        dest = os.path.join(self.failed_root(), report["run_id"], str(batch["batch_id"]))
        page = os.path.join(dest, "personal", "prefs", "answer-language.md")
        text = ta.read(page)
        self.assertIn("[REDACTED:github]", text)
        self.assertNotIn(token, text)
        self.assertIn("<!-- src: %s" % self.src_id, text)  # known id survives redaction
        for path in (self.failed_root(), os.path.dirname(dest), dest,
                     os.path.dirname(page)):
            self.assertEqual(ta.mode(path), 0o700, path)
        self.assertEqual(ta.mode(page), 0o600)
        info = json.loads(ta.read(os.path.join(dest, "failure.json")))
        self.assertEqual(ta.mode(os.path.join(dest, "failure.json")), 0o600)
        self.assertEqual(info["reason"], "secret_found")
        self.assertIn("secret_found:personal/prefs/answer-language.md", info["problems"])
        self.assertEqual(info["sources"], [self.src_id])
        kept = dict((item["path"], item["kept"]) for item in info["files"])
        self.assertEqual(kept["personal/prefs/answer-language.md"],
                         "personal/prefs/answer-language.md")
        self.assertIn("personal/_drafts/now.md", kept)
        self.assertNotIn(token, json.dumps(info))
        # the worktree was still reset and nothing reached main
        self.assertIsNone(self.main_file("personal/prefs/answer-language.md"))
        status = self.git(self.root, "status", "--porcelain").stdout.decode()
        self.assertNotIn(".state", status)

    def test_secret_shaped_file_name_is_hashed(self):
        token = j("gh", "p_", "Q1w2E3r4T5y6U7i8O9p0A1s2D3f4G5h6J7k8")

        def fn(request):
            out = ta.writes_pref()(request)
            ta.write(os.path.join(request["cwd"], "notes", "%s.md" % token), "x\n")
            return out
        report = self.run_absorb(ta.Runner(fn))
        dest = os.path.join(self.failed_root(), report["run_id"], "1")
        names = []
        for dirpath, _dirs, files in os.walk(dest):
            names += [os.path.join(dirpath, name) for name in files]
        self.assertTrue(any("/_renamed/" in name for name in names), names)
        self.assertFalse(any(token in name for name in names))
        self.assertNotIn(token, ta.read(os.path.join(dest, "failure.json")))

    def test_only_the_newest_runs_are_kept(self):
        base = self.failed_root()
        common.ensure_private_dir(os.path.join(self.root, ".state"))
        common.ensure_private_dir(base)
        for index in range(absorb.FAILED_KEEP_RUNS + 2):
            common.ensure_private_dir(os.path.join(base, "2026-10-0%dT0000" % (index + 1)))
        token = j("gh", "p_", "M1n2B3v4C5x6Z7l8K9j0H1g2F3d4S5a6P7o8")
        report = self.run_absorb(ta.Runner(ta.writes_pref(
            page_fn=lambda t, s: ta.pref_page(t, s, summary="키 " + token))))
        runs = sorted(os.listdir(base))
        self.assertEqual(len(runs), absorb.FAILED_KEEP_RUNS)
        self.assertEqual(runs[-1], report["run_id"])

    def test_retention_failure_keeps_the_batch_reason(self):
        token = j("gh", "p_", "R1t2Y3u4I5o6P7a8S9d0F1g2H3j4K5l6Z7x8")
        with mock.patch.object(absorb, "_retained_name", side_effect=OSError("boom")):
            report = self.run_absorb(ta.Runner(ta.writes_pref(
                page_fn=lambda t, s: ta.pref_page(t, s, summary="키 " + token))))
        batch = report["batches"][0]
        self.assertEqual(batch["reason"], "secret_found")
        self.assertNotIn("failed_draft_kept", batch["warnings"])
        self.assertIsNone(self.main_file("personal/prefs/answer-language.md"))


if __name__ == "__main__":
    unittest.main()
