import datetime
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import preflight  # noqa: E402
import resolve  # noqa: E402

POLICY = resolve.load_policy(override=None)
DAY = datetime.datetime(2026, 11, 22, 14, 0, tzinfo=resolve.KST)
NIGHT = datetime.datetime(2026, 11, 22, 23, 30, tzinfo=resolve.KST)


def run(project="seoulseeing", lane="M", switch="auto", now=DAY, exhausted=(), switches=0):
    return resolve.resolve(POLICY, project, lane, switch, now, exhausted, switches)


def families(result):
    roles = result["roles"]
    return roles["implement"]["family"], [c["family"] for c in roles["critics"]], roles["reviewer"]["family"]


class ResolveTest(unittest.TestCase):
    def test_day_uses_project_primary_and_qwen_review(self):
        self.assertEqual(families(run()), ("codex", ["claude"], "qwen"))
        self.assertEqual(families(run(project="core-ser")), ("claude", ["codex"], "qwen"))

    def test_night_auto_uses_chinese_models(self):
        result = run(now=NIGHT)
        self.assertEqual(result["mode"], "night_cn")
        self.assertEqual(families(result), ("qwen", ["deepseek"], "deepseek"))
        self.assertEqual(result["roles"]["coordinator"]["family"], "codex")

    def test_window_edges(self):
        at = lambda h: datetime.datetime(2026, 11, 22, h, 0, tzinfo=resolve.KST)
        self.assertEqual(run(now=at(22))["mode"], "day")
        self.assertEqual(run(now=at(23))["mode"], "night_cn")
        self.assertEqual(run(now=at(8))["mode"], "night_cn")
        self.assertEqual(run(now=at(9))["mode"], "day")

    def test_switch_off_removes_chinese_models_from_every_role(self):
        result = run(now=NIGHT, switch="off")
        self.assertEqual(families(result), ("codex", ["claude"], "claude"))
        used = [result["roles"]["implement"], result["roles"]["reviewer"]] + result["roles"]["critics"]
        self.assertFalse(any(r["harness"] == "qwen" for r in used))

    def test_switch_on_forces_night_roster_in_daytime(self):
        self.assertEqual(run(switch="on")["roles"]["implement"]["family"], "qwen")

    def test_high_risk_never_implements_on_chinese_models(self):
        result = run(lane="L", now=NIGHT)
        self.assertEqual(result["roles"]["implement"]["model"], "gpt-6.1-sol")
        self.assertEqual(len(result["roles"]["critics"]), 3)
        self.assertEqual({c["family"] for c in result["roles"]["critics"]}, {"claude"})
        self.assertIn("test_writer", result["roles"])
        self.assertTrue(result["limits"]["plan_approval"])

    def test_small_lane_has_no_critics_or_test_session(self):
        result = run(lane="S")
        self.assertEqual(result["roles"]["critics"], [])
        self.assertNotIn("test_writer", result["roles"])
        self.assertEqual(result["limits"]["review_rounds"], 1)

    def test_exhausted_primary_falls_back_at_same_tier(self):
        result = run(exhausted=["codex"])
        self.assertEqual(result["roles"]["implement"]["model"], "sonnet")
        self.assertEqual(families(result), ("claude", ["deepseek"], "qwen"))
        self.assertTrue(any("구현 전환" in note for note in result["notes"]))

    def test_fallback_keeps_author_and_checker_in_different_families(self):
        for exhausted in (["codex"], ["claude"], ["qwen"], ["qwen", "deepseek"], ["codex", "qwen"]):
            for now in (DAY, NIGHT):
                for lane in ("M", "L"):
                    result = run(lane=lane, now=now, exhausted=exhausted)
                    if result["wait"]:
                        continue
                    impl, critics, reviewer = families(result)
                    checkers = result["roles"]["critics"] + [result["roles"]["reviewer"]]
                    for checker in checkers:
                        self.assertNotIn(checker["family"], exhausted)
                        if checker["family"] == impl:
                            self.assertTrue(checker.get("same_family"), (exhausted, lane))
                            self.assertNotEqual(lane, "L")

    def test_same_family_is_last_resort_and_marked(self):
        result = run(switch="off", exhausted=["codex"])
        self.assertEqual(result["wait"], [])
        self.assertEqual(result["roles"]["implement"]["model"], "sonnet")
        for checker in result["roles"]["critics"] + [result["roles"]["reviewer"]]:
            self.assertEqual(checker["model"], "opus")
            self.assertTrue(checker["same_family"])
        self.assertEqual(len(result["notes"]), 3)

    def test_high_risk_waits_instead_of_same_family(self):
        result = run(lane="L", switch="off", exhausted=["codex"])
        self.assertEqual(sorted(result["wait"]), ["critique", "review"])

    def test_everything_exhausted_waits(self):
        result = run(exhausted=["codex", "claude"])
        self.assertIn("implement", result["wait"])

    def test_switch_cap(self):
        self.assertIn("implement", run(switches=3)["wait"])
        self.assertEqual(run(switches=2)["wait"], [])

    def test_unknown_project_uses_default(self):
        self.assertEqual(run(project="nope")["roles"]["implement"]["family"], "codex")


def issue(**over):
    base = {
        "identifier": "JAY-1",
        "title": "입력 대기열",
        "description": "## 완료 기준\n- 답변 중 입력이 보존된다\n",
        "state": "Todo",
        "labels": [],
        "children": 0,
        "has_open_pr": False,
        "blocked_by": [],
        "repo": "JunJuneee/seoul-seeing",
    }
    base.update(over)
    return base


class PreflightTest(unittest.TestCase):
    def reasons(self, **over):
        return preflight.check(issue(**over), POLICY)

    def test_ready_issue_passes_with_default_lane(self):
        self.assertEqual(self.reasons(), ("M", []))

    def test_lane_label(self):
        self.assertEqual(self.reasons(labels=["lane-s"])[0], "S")

    def test_blocks_on_state_label_epic_and_pr(self):
        self.assertTrue(self.reasons(state="In Progress")[1])
        self.assertTrue(self.reasons(labels=["agent-running"])[1])
        self.assertTrue(self.reasons(title="Epic: food")[1])
        self.assertTrue(self.reasons(children=2)[1])
        self.assertTrue(self.reasons(has_open_pr=True)[1])

    def test_unfinished_blocker(self):
        lane, why = self.reasons(blocked_by=[{"identifier": "JAY-558", "state_type": "unstarted"}])
        self.assertIn("JAY-558", why[0])
        self.assertEqual(self.reasons(blocked_by=[{"identifier": "JAY-558", "state_type": "completed"}])[1], [])

    def test_predecessor_written_only_in_body(self):
        body = "선행: JAY-558 완료 후 진행\n## 완료 기준\n- 재계산된다\n"
        lane, why = self.reasons(description=body)
        self.assertTrue(any("blocks 관계" in r and "JAY-558" in r for r in why))
        linked = [{"identifier": "JAY-558", "state_type": "completed"}]
        self.assertEqual(self.reasons(description=body, blocked_by=linked)[1], [])

    def test_missing_criteria_or_repo(self):
        self.assertTrue(self.reasons(description="그냥 해 주세요")[1])
        self.assertTrue(self.reasons(description="## 완료 기준\n없음")[1])
        self.assertTrue(self.reasons(repo=None)[1])

    def test_high_risk_word_needs_lane_l(self):
        body = "DB 마이그레이션 포함\n## 완료 기준\n- 적용된다\n"
        self.assertTrue(self.reasons(description=body)[1])
        self.assertEqual(self.reasons(description=body, labels=["lane-l"]), ("L", []))


if __name__ == "__main__":
    unittest.main()
