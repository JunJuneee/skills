#!/usr/bin/env python3
"""완료 영수증이 실행 명세의 배정대로 수행됐는지 대조한다. 모델을 부르지 않는다.

    receipt.py validate --manifest runs/<id>/manifest.json --receipt runs/<id>/receipt.json

명세의 `roster`는 발송 때 `preflight.py`가 돌려준 값이다. PR 상태나 Linear 상태는 보지 않는다.
그 확인은 실행기가 한다. 종료 코드는 0 통과, 2 불일치다.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve as resolver  # noqa: E402

LANE_RANK = {"S": 0, "M": 1, "L": 2}


def same_role(actual, expected):
    return bool(expected) and actual.get("family") == expected["family"] and actual.get("model") == expected["model"]


def expected_roster(roster, fallback, policy):
    """영수증의 전환 기록을 반영해 다시 계산한 배정. 전환이 없으면 명세 그대로다."""
    if not fallback:
        return roster
    inputs = roster["inputs"]
    exhausted = set(inputs["exhausted"]) | {entry["from"] for entry in fallback}
    switches = inputs["switches"] + sum(1 for entry in fallback if entry.get("role") == "implement")
    now = datetime.datetime.fromisoformat(inputs["now"])
    return resolver.resolve(policy, roster["project"], roster["lane"], roster["night_roster"], now,
                            resolver.parse_exhausted(",".join(sorted(exhausted)), policy), switches)


def validate(manifest, receipt, policy):
    """(통과 여부, 사유 목록, 참고). roster가 없는 옛 명세는 대조하지 않고 통과시킨다."""
    roster = manifest.get("roster")
    if not roster:
        return True, [], "legacy_manifest_without_roster"
    if receipt.get("status") != "completed":
        return True, [], "not_a_completed_receipt"

    reasons = []
    lane = receipt.get("lane")
    if lane not in LANE_RANK:
        reasons.append("lane 없음")
    elif LANE_RANK[lane] < LANE_RANK[roster["lane"]]:
        reasons.append("줄이 명세(%s)보다 낮음: %s" % (roster["lane"], lane))

    implement = receipt.get("implement") or {}
    review = receipt.get("review") or {}
    for name, value, keys in (("implement", implement, ("family", "model", "session_id")),
                              ("review", review, ("url", "family", "model", "session_id"))):
        missing = [key for key in keys if not value.get(key)]
        if missing:
            reasons.append("%s 필드 없음: %s" % (name, ", ".join(missing)))
    if reasons:
        return False, reasons, None

    fallback = receipt.get("fallback") or []
    try:
        expected = expected_roster(roster, fallback, policy)
    except (KeyError, ValueError) as exc:
        return False, ["전환 기록으로 배정을 다시 계산할 수 없음: %s" % exc], None
    roles = expected["roles"]

    # 구현은 배정된 모델이거나, 리뷰 2회째 이후 올린 모델이어야 한다.
    if not (same_role(implement, roles.get("implement")) or same_role(implement, expected.get("escalation"))):
        reasons.append("구현 모델이 배정과 다름: %s/%s" % (implement["family"], implement["model"]))
    reviewer = roles.get("reviewer")
    if not same_role(review, reviewer):
        reasons.append("리뷰 모델이 배정과 다름: %s/%s" % (review["family"], review["model"]))

    if review["family"] == implement["family"]:
        if not (reviewer and reviewer.get("same_family")):
            reasons.append("리뷰어가 구현과 같은 계열인데 배정이 허용하지 않음")
        elif review.get("same_family") is not True:
            reasons.append("같은 계열 리뷰인데 영수증에 same_family 표시가 없음")

    if review.get("verified_from_transcript") is not True:
        alias_ok = review.get("alias_only") is True and review["family"] == "claude" and roster["lane"] != "L"
        if not alias_ok:
            reasons.append("리뷰 실행 모델을 transcript로 확인하지 않음")

    rounds, limit = review.get("rounds"), expected["limits"]["review_rounds"]
    if type(rounds) is not int or rounds < 1:
        reasons.append("리뷰 횟수 없음")
    elif rounds > limit:
        reasons.append("리뷰 횟수 %d회가 상한 %d회를 넘음. 완료가 아니라 차단으로 넘겨야 함" % (rounds, limit))
    if review.get("unresolved_valid_findings") != 0:
        reasons.append("미해결 유효 지적이 0건이 아님")
    return not reasons, reasons, None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--manifest", required=True)
    v.add_argument("--receipt", required=True)
    v.add_argument("--policy")
    args = p.parse_args(argv)

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)
    with open(args.receipt, encoding="utf-8") as f:
        receipt = json.load(f)
    ok, reasons, note = validate(manifest, receipt, resolver.load_policy(args.policy))
    result = {"ok": ok, "reasons": reasons}
    if note:
        result["note"] = note
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
