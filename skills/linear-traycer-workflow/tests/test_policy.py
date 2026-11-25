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

    def test_other_family_is_used_before_same_family(self):
        # 리뷰: Qwen이 소진돼도 DeepSeek이 남아 있으면 같은 계열로 내려가지 않는다.
        result = run(exhausted=["claude", "qwen"])
        self.assertEqual(families(result), ("codex", ["deepseek"], "deepseek"))
        self.assertFalse(result["roles"]["reviewer"].get("same_family"))
        # critique: DeepSeek이 소진돼도 Qwen이 남아 있다.
        result = run(exhausted=["claude", "deepseek"])
        self.assertEqual(families(result), ("codex", ["qwen"], "qwen"))
        self.assertFalse(result["roles"]["critics"][0].get("same_family"))

    def test_same_family_only_when_no_other_family_is_left(self):
        every = [[], ["claude"], ["codex"], ["qwen"], ["deepseek"], ["claude", "qwen"], ["claude", "deepseek"],
                 ["codex", "qwen"], ["codex", "deepseek"], ["qwen", "deepseek"], ["claude", "qwen", "deepseek"],
                 ["codex", "qwen", "deepseek"]]
        for exhausted in every:
            for switch in ("auto", "on", "off"):
                for now in (DAY, NIGHT):
                    result = run(switch=switch, now=now, exhausted=exhausted)
                    if "implement" in result["wait"]:
                        continue
                    impl = result["roles"]["implement"]["family"]
                    allowed = {"claude", "codex"} | ({"qwen", "deepseek"} if switch != "off" else set())
                    others = allowed - {impl} - set(exhausted)
                    checkers = result["roles"]["critics"] + [result["roles"].get("reviewer", {})]
                    for checker in checkers:
                        if checker.get("same_family"):
                            self.assertEqual(others, set(), (exhausted, switch))

    def test_high_risk_critique_never_uses_chinese_models(self):
        result = run(lane="L", exhausted=["claude", "qwen"])
        self.assertIn("critique", result["wait"])
        self.assertEqual(result["roles"]["reviewer"]["family"], "deepseek")
        for switch in ("auto", "on"):
            for now in (DAY, NIGHT):
                roles = run(lane="L", switch=switch, now=now)["roles"]
                for r in [roles["implement"], roles["test_writer"], roles["verifier"]] + roles["critics"]:
                    self.assertNotEqual(r["harness"], "qwen")

    def test_escalation_target(self):
        self.assertEqual(run()["escalation"]["model"], "gpt-6.1-sol")
        night = run(now=NIGHT)
        self.assertEqual(night["roles"]["implement"]["family"], "qwen")
        self.assertEqual(night["escalation"]["model"], "gpt-6.1-sol")
        self.assertNotEqual(night["escalation"]["family"], night["roles"]["reviewer"]["family"])
        self.assertIsNone(run(lane="L")["escalation"])

    def test_no_escalation_into_the_same_family_reviewer(self):
        result = run(switch="off", exhausted=["claude"])
        self.assertTrue(result["roles"]["reviewer"]["same_family"])
        self.assertIsNone(result["escalation"])
        for exhausted in ([], ["claude"], ["codex"], ["qwen"], ["claude", "qwen"], ["codex", "deepseek"]):
            for switch in ("auto", "on", "off"):
                for now in (DAY, NIGHT):
                    for lane in ("S", "M"):
                        result = run(lane=lane, switch=switch, now=now, exhausted=exhausted)
                        up, reviewer = result.get("escalation"), result["roles"].get("reviewer")
                        if up and reviewer:
                            self.assertNotEqual(up["family"], reviewer["family"], (exhausted, switch, lane))

    def test_switch_file_parsing(self):
        parse = resolve.parse_switch
        self.assertEqual(parse("export NIGHT_ROSTER=off\n"), "off")
        self.assertEqual(parse("# NIGHT_ROSTER=on\nNIGHT_ROSTER=off\n"), "off")
        self.assertEqual(parse('NIGHT_ROSTER="off"\n'), "off")
        self.assertEqual(parse("NIGHT_ROSTER='on'  # 강제\n"), "on")
        self.assertEqual(parse("NIGHT_ROSTER=on\nNIGHT_ROSTER=auto\n"), "auto")
        self.assertIsNone(parse("MY_NIGHT_ROSTER=on\nNIGHT_ROSTER=maybe\n"))

    def test_window_that_does_not_cross_midnight(self):
        policy = resolve.merge(POLICY, {"night": {"window_kst": [0, 9]}})
        self.assertFalse(resolve.is_night(policy, DAY))
        self.assertTrue(resolve.is_night(policy, datetime.datetime(2026, 11, 22, 3, 0, tzinfo=resolve.KST)))
        utc = datetime.timezone.utc
        self.assertTrue(resolve.is_night(POLICY, datetime.datetime(2026, 11, 22, 14, 0, tzinfo=utc)))
        self.assertFalse(resolve.is_night(POLICY, datetime.datetime(2026, 11, 22, 0, 0, tzinfo=utc)))

    def test_unknown_exhausted_family_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve.parse_exhausted("codex,bogus", POLICY)
        self.assertEqual(resolve.parse_exhausted(" codex , claude ", POLICY), ["codex", "claude"])

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

    def test_lane_comes_only_from_labels(self):
        body = "DB 마이그레이션 포함, 결제 단계 권한 확인\n## 완료 기준\n- 적용된다\n"
        # 제목·본문의 단어는 실행을 막지 않는다. 라벨이 없으면 기본 줄이다.
        self.assertEqual(self.reasons(description=body), ("M", []))
        self.assertEqual(self.reasons(description=body, labels=["lane-l"]), ("L", []))
        self.assertEqual(self.reasons(description=body, labels=["Lane-S"]), ("S", []))

    def test_issue_ids_before_the_predecessor_word_are_references(self):
        listing = ("* JAY-370 복합 챗, JAY-371/373 derma 연결의 현재 계약·선행·소유를 확인한다.\n"
                   "## 완료 기준\n- 조사 결과가 있다\n")
        self.assertEqual(self.reasons(description=listing)[1], [])
        real = "JAY-1 explicitly requires predecessor JAY-558.\n## 완료 기준\n- 재계산된다\n"
        self.assertTrue(any("JAY-558" in r for r in self.reasons(description=real)[1]))
        titled = "## 선행: JAY-7\n내용\n## 완료 기준\n- 된다\n"
        self.assertTrue(any("JAY-7" in r for r in self.reasons(description=titled)[1]))

    def test_fully_checked_criteria_mean_nothing_is_left(self):
        done = "## 완료 기준 및 검증 (변경)\n\n- [X] 설정했다.\n- [x] 수신을 확인했다.\n"
        self.assertTrue(any("모두 체크" in r for r in self.reasons(description=done)[1]))
        partial = "## 완료 기준\n- [x] 설정했다.\n- [ ] 수신을 확인한다.\n"
        self.assertEqual(self.reasons(description=partial)[1], [])
        plain = "## 완료 기준\n- [x] 설정했다.\n- 수신을 확인한다.\n"
        self.assertEqual(self.reasons(description=plain)[1], [])
        # 목록 기호가 섞여 있어도 체크되지 않은 항목을 놓치지 않는다.
        mixed = "## 완료 기준\n- [x] 저장했다\n+ [ ] 재시작 후 복원된다\n"
        self.assertEqual(self.reasons(description=mixed)[1], [])
        plus = "## 완료 기준\n+ [x] 저장했다\n+ [X] 복원된다\n"
        self.assertTrue(any("모두 체크" in r for r in self.reasons(description=plus)[1]))
        self.assertEqual(self.reasons(description="## 완료 기준\n+ 저장된다\n")[1], [])


    def test_every_predecessor_on_the_line_is_checked(self):
        body = "선행: JAY-100, JAY-101 완료 후 진행\n## 완료 기준\n- 입력 보존\n"
        linked = [{"identifier": "JAY-100", "state_type": "completed"}]
        lane, why = self.reasons(description=body, blocked_by=linked)
        self.assertTrue(any("JAY-101" in r and "JAY-100" not in r for r in why))

    def test_predecessor_section_list(self):
        body = "## 선행 이슈\n- JAY-100\n- JAY-101\n## 완료 기준\n- 입력 보존\n"
        lane, why = self.reasons(description=body)
        self.assertTrue(any("JAY-100" in r and "JAY-101" in r for r in why))
        self.assertEqual(self.reasons(description="## 참고\n- JAY-100 과 비슷함\n## 완료 기준\n- 입력 보존\n")[1], [])

    def test_predecessor_match_ignores_case(self):
        body = "depends on jay-100\n## 완료 기준\n- 입력 보존\n"
        linked = [{"identifier": "JAY-100", "state_type": "completed"}]
        self.assertEqual(self.reasons(description=body, blocked_by=linked)[1], [])

    def test_empty_criteria_section_is_not_filled_by_a_later_list(self):
        body = "## 완료 기준\n\n## 참고 자료\n- https://example.com/spec\n"
        self.assertTrue(any("완료 기준" in r for r in self.reasons(description=body)[1]))
        self.assertEqual(self.reasons(description="**완료 기준**\n1. 저장된다\n")[1], [])
        self.assertEqual(self.reasons(description="완료 기준:\n- 저장된다\n")[1], [])

    def test_subheadings_belong_to_their_parent_section(self):
        body = "## 완료 기준\n### 정상 동작\n- 입력이 보존된다\n### 오류 처리\n- 안내가 표시된다\n"
        self.assertEqual(self.reasons(description=body)[1], [])
        self.assertEqual(self.reasons(description="## 완료 기준\n**정상 동작**\n- 입력이 보존된다\n")[1], [])
        nested = "## 선행 이슈\n### 공통 작업\n- JAY-100\n## 완료 기준\n- 입력 보존\n"
        self.assertTrue(any("JAY-100" in r for r in self.reasons(description=nested)[1]))
        # 상위 제목이 다시 나오면 섹션이 끝난다.
        ended = "### 완료 기준\n## 참고\n- 링크\n"
        self.assertTrue(any("완료 기준" in r for r in self.reasons(description=ended)[1]))
        after = "## 선행 이슈\n없음\n## 참고\n- JAY-100 과 비슷함\n## 완료 기준\n- 입력 보존\n"
        self.assertEqual(self.reasons(description=after)[1], [])

    def test_cli_exit_codes(self):
        import io
        import json
        from unittest import mock

        def cli(payload, *args):
            out = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), mock.patch("sys.stdout", out), \
                    mock.patch.object(resolve, "LOCAL_OVERRIDE", None):
                code = preflight.main(["--project", "seoulseeing", "--now", "2026-11-22T14:00",
                                       "--night-roster", "off"] + list(args))
            return code, json.loads(out.getvalue())

        self.assertEqual(cli(issue())[0], 0)
        self.assertEqual(cli(issue(state="Backlog"))[0], 2)
        code, result = cli(issue(), "--exhausted", "codex,claude")
        self.assertEqual((code, result["ok"]), (3, False))
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            preflight.main(["--project", "seoulseeing", "--exhausted", "bogus"])


if __name__ == "__main__":
    unittest.main()
