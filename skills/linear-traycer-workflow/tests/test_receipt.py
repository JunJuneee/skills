import copy
import datetime
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import preflight  # noqa: E402
import receipt  # noqa: E402
import resolve  # noqa: E402

POLICY = resolve.load_policy(override=None)
DAY = datetime.datetime(2026, 11, 22, 14, 0, tzinfo=resolve.KST)
NIGHT = datetime.datetime(2026, 11, 22, 23, 30, tzinfo=resolve.KST)


def roster(lane="M", switch="auto", now=DAY, exhausted=(), project="seoulseeing"):
    return resolve.resolve(POLICY, project, lane, switch, now, exhausted, 0)


def done(r, **over):
    """배정대로 수행한 완료 영수증."""
    impl, rev = r["roles"]["implement"], r["roles"]["reviewer"]
    value = {
        "status": "completed",
        "lane": r["lane"],
        "implement": {"family": impl["family"], "model": impl["model"], "session_id": "impl-1"},
        "review": {"url": "https://github.com/o/r/pull/1#issuecomment-1", "family": rev["family"],
                   "model": rev["model"], "session_id": "rev-1", "verified_from_transcript": True,
                   "rounds": 1, "unresolved_valid_findings": 0},
    }
    if rev.get("same_family"):
        value["review"]["same_family"] = True
    for key, change in over.items():
        if isinstance(change, dict):
            value[key] = dict(value.get(key, {}), **change)
        else:
            value[key] = change
    return value


class ReceiptTest(unittest.TestCase):
    def check(self, r, rc):
        return receipt.validate({"roster": r}, rc, POLICY)

    def test_matching_receipt_passes(self):
        for r in (roster(), roster(now=NIGHT), roster(lane="L"), roster(lane="S", switch="off")):
            self.assertEqual(self.check(r, done(r))[:2], (True, []))

    def test_legacy_manifest_and_non_completed_receipts_are_not_judged(self):
        self.assertEqual(receipt.validate({}, {"status": "completed"}, POLICY), (True, [], "legacy_manifest_without_roster"))
        self.assertTrue(self.check(roster(), {"status": "blocked", "reason": "x"})[0])

    def test_wrong_reviewer_model_or_family_fails(self):
        r = roster(switch="off")  # 리뷰어는 Claude Opus
        ok, why, _ = self.check(r, done(r, review={"family": "qwen", "model": "qwen4-max-preview(openai)"}))
        self.assertFalse(ok)
        self.assertTrue(any("리뷰 모델" in x for x in why))
        ok, why, _ = self.check(r, done(r, review={"family": "codex", "model": "gpt-6.1-sol"}))
        self.assertTrue(any("같은 계열" in x for x in why))

    def test_escalated_implementer_is_accepted_but_other_models_are_not(self):
        r = roster()
        up = r["escalation"]
        self.assertTrue(self.check(r, done(r, implement={"family": up["family"], "model": up["model"]}))[0])
        self.assertFalse(self.check(r, done(r, implement={"model": "gpt-6-luna"}))[0])

    def test_fallback_is_recomputed(self):
        r = roster()  # Codex 구현 배정
        after = roster(exhausted=["codex"])  # 실행 도중 Codex 소진 → Claude 구현
        switched = done(after, fallback=[{"role": "implement", "from": "codex", "to": "claude", "reason": "usage"}])
        self.assertEqual(self.check(r, switched)[:2], (True, []))
        # 전환 기록 없이 다른 계열로 구현했으면 거부한다.
        self.assertFalse(self.check(r, done(after))[0])
        # 기록한 소진 계열과 맞지 않는 전환도 거부한다.
        wrong = done(after, fallback=[{"role": "implement", "from": "qwen", "to": "claude", "reason": "usage"}])
        self.assertFalse(self.check(r, wrong)[0])

    def test_fallback_records_must_follow_the_real_assignment(self):
        r, after = roster(), roster(exhausted=["codex"])
        entry = {"role": "implement", "from": "codex", "to": "claude", "reason": "usage"}
        for change in ({"role": "not-a-role"}, {"to": "not-a-family"}, {"reason": "not-usage"}, {"to": "qwen"},
                       {"role": "reviewer"}):
            self.assertFalse(self.check(r, done(after, fallback=[dict(entry, **change)]))[0], change)
        self.assertFalse(self.check(r, done(after, fallback=["x"]))[0])
        self.assertFalse(self.check(r, done(after, fallback={"from": "codex"}))[0])
        self.assertFalse(self.check(r, done(after, fallback=[{"from": []}]))[0])

    def test_fallback_cannot_pass_the_switch_cap(self):
        used = resolve.resolve(POLICY, "seoulseeing", "M", "auto", DAY, [], 2)  # 이미 두 번 전환함
        after = roster(exhausted=["codex"])
        for role in ("implement", "reviewer"):
            entry = {"role": role, "from": "codex", "to": "claude", "reason": "usage"}
            self.assertFalse(self.check(used, done(after, fallback=[entry]))[0], role)

    def test_reviewer_fallback(self):
        r = roster()  # 리뷰어 Qwen
        after = roster(exhausted=["qwen"])
        self.assertEqual(after["roles"]["reviewer"]["family"], "deepseek")
        entry = {"role": "reviewer", "from": "qwen", "to": "deepseek", "reason": "usage"}
        self.assertEqual(self.check(r, done(after, fallback=[entry]))[:2], (True, []))

    def test_malformed_input_is_a_mismatch_not_a_crash(self):
        r = roster()
        for manifest in ({"roster": {}}, {"roster": None}, {"roster": dict(r, lane=None)},
                         {"roster": {k: v for k, v in r.items() if k != "lane"}}, [], "x"):
            self.assertFalse(receipt.validate(manifest, done(r), POLICY)[0], manifest if not isinstance(manifest, dict) else "roster")
        for change in ({"implement": "x"}, {"lane": []}, {"review": None}, {"lane": 1}):
            bad = done(r)
            bad.update(change)
            self.assertFalse(self.check(r, bad)[0], change)
        for change in ({"session_id": True}, {"url": 123}, {"unresolved_valid_findings": False}, {"rounds": True},
                       {"model": ""}):
            self.assertFalse(self.check(r, done(r, review=change))[0], change)
        self.assertFalse(self.check(r, done(r, implement={"session_id": ["x"]}))[0])
        self.assertFalse(receipt.validate({"roster": r}, [], POLICY)[0])

    def test_review_session_must_differ_from_implementer(self):
        for r in (roster(), roster(switch="off", exhausted=["claude"])):
            self.assertTrue(any("세션" in x for x in self.check(r, done(r, review={"session_id": "impl-1"}))[1]))

    def test_policy_snapshot_is_used_for_recompute(self):
        import json
        r = roster()
        after = roster(exhausted=["codex"])
        switched = done(after, fallback=[{"role": "implement", "from": "codex", "to": "claude", "reason": "usage"}])
        changed = copy.deepcopy(POLICY)
        changed["version"] = 2
        changed["families"]["claude"]["models"]["std"] = "new-std-model"
        # 정책이 바뀌어도 명세에 담긴 발송 때 정책으로 대조한다.
        snapshot = json.loads(json.dumps({"roster": r, "policy": POLICY}))
        self.assertEqual(receipt.validate(snapshot, switched, changed)[:2], (True, []))
        # 정책이 없는 명세는 현재 정책이 달라졌으면 대조하지 않고 거부한다.
        ok, why, _ = receipt.validate({"roster": r}, done(r), changed)
        self.assertTrue(not ok and "정책" in why[0])
        # 명세의 정책이 roster를 계산한 정책이 아니어도 거부한다.
        self.assertFalse(receipt.validate({"roster": r, "policy": changed}, done(r), POLICY)[0])

    def test_cli_exit_codes(self):
        import io
        import json
        import tempfile
        from unittest import mock

        def cli(manifest, rc):
            with tempfile.TemporaryDirectory() as folder:
                paths = []
                for name, value in (("manifest.json", manifest), ("receipt.json", rc)):
                    paths.append(os.path.join(folder, name))
                    with open(paths[-1], "w", encoding="utf-8") as f:
                        f.write(value if isinstance(value, str) else json.dumps(value))
                out = io.StringIO()
                with mock.patch("sys.stdout", out), mock.patch.object(resolve, "LOCAL_OVERRIDE", None):
                    code = receipt.main(["validate", "--manifest", paths[0], "--receipt", paths[1]])
                return code, json.loads(out.getvalue())

        r = roster()
        self.assertEqual(cli({"roster": r, "policy": POLICY}, done(r))[0], 0)
        self.assertEqual(cli({"roster": r, "policy": POLICY}, done(r, review={"rounds": 9}))[0], 2)
        self.assertEqual(cli({"roster": {}}, {"status": "completed"})[0], 2)
        self.assertEqual(cli({"roster": r}, "not json")[0], 2)
        self.assertEqual(cli({}, {"status": "completed"}), (0, {"ok": True, "reasons": [], "note": "legacy_manifest_without_roster"}))

    def test_same_family_review_must_be_allowed_and_marked(self):
        r = roster(switch="off", exhausted=["claude"])
        self.assertTrue(r["roles"]["reviewer"]["same_family"])
        self.assertTrue(self.check(r, done(r))[0])
        unmarked = done(r)
        del unmarked["review"]["same_family"]
        self.assertTrue(any("same_family 표시" in x for x in self.check(r, unmarked)[1]))

    def test_round_cap_and_unresolved_findings(self):
        r = roster()
        self.assertTrue(self.check(r, done(r, review={"rounds": 3}))[0])
        self.assertTrue(any("상한" in x for x in self.check(r, done(r, review={"rounds": 4}))[1]))
        self.assertFalse(self.check(r, done(r, review={"unresolved_valid_findings": 1}))[0])
        small = roster(lane="S")
        self.assertFalse(self.check(small, done(small, review={"rounds": 2}))[0])

    def test_transcript_verification_and_alias_exception(self):
        r = roster(switch="off")  # Claude 리뷰어
        alias = {"verified_from_transcript": False, "alias_only": True}
        self.assertFalse(self.check(r, done(r, review={"verified_from_transcript": False}))[0])
        self.assertTrue(self.check(r, done(r, review=alias))[0])
        high = roster(lane="L", switch="off")
        self.assertFalse(self.check(high, done(high, review=alias))[0])
        # 별칭만 확인됐다는 표시는 검증 플래그와 함께 있어도 L 줄에서는 인정하지 않는다.
        self.assertFalse(self.check(high, done(high, review={"alias_only": True}))[0])
        # 진행 중에 L로 올라간 실행도 마찬가지다.
        self.assertFalse(self.check(r, done(r, lane="L", review=alias))[0])
        qwen = roster()
        self.assertFalse(self.check(qwen, done(qwen, review=alias))[0])

    def test_lane_cannot_go_down_and_fields_are_required(self):
        r = roster()
        self.assertFalse(self.check(r, done(r, lane="S"))[0])
        self.assertTrue(self.check(r, done(r, lane="L"))[0])
        broken = done(r)
        del broken["review"]["session_id"]
        self.assertTrue(any("session_id" in x for x in self.check(r, broken)[1]))
        self.assertFalse(self.check(r, {"status": "completed"})[0])

    def test_roster_survives_json_round_trip(self):
        import json
        r = json.loads(json.dumps(roster(now=NIGHT)))
        switched = done(roster(now=NIGHT, exhausted=["qwen"]),
                        fallback=[{"role": "implement", "from": "qwen", "to": "codex", "reason": "usage"}])
        self.assertEqual(self.check(r, switched)[:2], (True, []))


def node(**over):
    base = {
        "identifier": "CORE-1", "title": "태그 추가",
        "description": "## 구현 범위\n- a\n## 2. 검증 방식\n- 응답에 태그가 보인다\n",
        "state": {"name": "시작 대기", "type": "unstarted"},
        "labels": {"nodes": [{"name": "server-task"}]},
        "children": {"nodes": [], "pageInfo": {"hasNextPage": False}},
        "inverseRelations": {"nodes": [], "pageInfo": {"hasNextPage": False}},
    }
    base.update(over)
    return base


class FromLinearTest(unittest.TestCase):
    def reasons(self, project="core-ser", repo="SaladLabInc/x", pr=False, **over):
        return preflight.check(preflight.from_linear(node(**over), repo, pr), POLICY, project)

    def test_project_settings_apply(self):
        self.assertEqual(self.reasons(), ("M", []))
        # 같은 이슈도 그 설정이 없는 프로젝트에서는 상태와 완료 기준에 걸린다.
        self.assertEqual(len(self.reasons(project="seoulseeing")[1]), 2)

    def test_relations_children_and_pr(self):
        blocked = {"nodes": [{"type": "blocks", "issue": {"identifier": "CORE-0", "state": {"type": "started"}}},
                             {"type": "related", "issue": {"identifier": "CORE-9", "state": {"type": "started"}}}],
                   "pageInfo": {"hasNextPage": False}}
        why = self.reasons(inverseRelations=blocked)[1]
        self.assertTrue(any("CORE-0" in r and "CORE-9" not in r for r in why))
        partial = {"nodes": [], "pageInfo": {"hasNextPage": True}}
        self.assertTrue(self.reasons(inverseRelations=partial)[1])
        self.assertTrue(self.reasons(children={"nodes": [{"id": "c"}], "pageInfo": {"hasNextPage": False}})[1])
        self.assertTrue(self.reasons(pr=True)[1])
        self.assertTrue(self.reasons(repo=None)[1])

    def test_partial_label_page_is_rejected(self):
        partial = {"nodes": [{"name": "server-task"}], "pageInfo": {"hasNextPage": True}}
        self.assertTrue(any("라벨" in r for r in self.reasons(labels=partial)[1]))

    def test_issue_ids_inside_criteria_are_not_predecessors(self):
        body = "**선행 이슈**\n- JAY-100\n완료 기준:\n- JAY-101 항목을 표시한다\n"
        linked = [{"identifier": "JAY-100", "state_type": "completed"}]
        base = {"identifier": "JAY-1", "title": "t", "description": body, "state": "Todo", "labels": [],
                "children": 0, "has_open_pr": False, "blocked_by": linked, "repo": "o/r"}
        self.assertEqual(preflight.check(base, POLICY, "seoulseeing"), ("M", []))
        self.assertTrue(preflight.check(dict(base, blocked_by=[]), POLICY, "seoulseeing")[1])

    def test_numbered_plain_heading_ends_at_the_next_number(self):
        self.assertTrue(self.reasons(description="1. 완료 기준\n\n2. 참고 자료\n- https://example.com/spec\n")[1])
        self.assertEqual(self.reasons(description="1. 완료 기준\n- 저장된다\n2. 참고 자료\n")[1], [])
        self.assertEqual(self.reasons(description="## 완료 기준\n1. 저장된다\n2. 복원된다\n")[1], [])

    def test_numbered_criteria_heading(self):
        self.assertEqual(self.reasons(description="### 3) 수용 기준\n1. 저장된다\n")[1], [])
        self.assertTrue(self.reasons(description="## 검증 방식을 정한다\n- 미정\n")[1])


if __name__ == "__main__":
    unittest.main()
