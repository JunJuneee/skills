#!/usr/bin/env python3
"""완료 영수증이 실행 명세의 배정대로 수행됐는지 대조한다. 모델을 부르지 않는다.

    receipt.py validate --manifest runs/<id>/manifest.json --receipt runs/<id>/receipt.json

명세의 `roster`와 `policy`는 발송 때 `preflight.py`가 돌려준 값이다. PR 상태나 Linear 상태는 보지 않는다.
그 확인은 실행기가 한다. 종료 코드는 0 통과, 2 불일치(읽을 수 없는 입력 포함)다.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve as resolver  # noqa: E402

LANE_RANK = {"S": 0, "M": 1, "L": 2}
FALLBACK_ROLES = ("implement", "reviewer", "critic")


class Mismatch(Exception):
    pass


def text(value):
    return isinstance(value, str) and bool(value.strip())


def same_role(actual, expected):
    return bool(expected) and actual["family"] == expected["family"] and actual["model"] == expected["model"]


def family_of(result, role):
    roles = result["roles"]
    if role == "critic":
        return roles["critics"][0]["family"] if roles.get("critics") else None
    return (roles.get(role) or {}).get("family")


def replay(roster, fallback, policy):
    """전환 기록을 순서대로 다시 계산한다. 기록이 실제 배정의 흐름과 맞지 않으면 Mismatch다."""
    inputs = roster["inputs"]
    now = datetime.datetime.fromisoformat(inputs["now"])
    exhausted, switches = list(inputs["exhausted"]), inputs["switches"]

    def compute():
        return resolver.resolve(policy, roster["project"], roster["lane"], roster["night_roster"], now,
                                resolver.parse_exhausted(",".join(exhausted), policy), switches)

    current = compute()
    for index, entry in enumerate(fallback, 1):
        if not isinstance(entry, dict):
            raise Mismatch("fallback %d번이 객체가 아님" % index)
        role, source, target = entry.get("role"), entry.get("from"), entry.get("to")
        if role not in FALLBACK_ROLES or entry.get("reason") != "usage":
            raise Mismatch("fallback %d번의 role 또는 reason이 올바르지 않음" % index)
        if source not in policy["families"] or target not in policy["families"]:
            raise Mismatch("fallback %d번의 계열을 알 수 없음" % index)
        if family_of(current, role) != source:
            raise Mismatch("fallback %d번: 그 시점의 %s 배정은 %s가 아님" % (index, role, source))
        before = family_of(current, "implement")
        if source not in exhausted:
            exhausted.append(source)
        if role == "implement":
            switches += 1
        current = compute()
        if role != "implement" and family_of(current, "implement") != before:
            raise Mismatch("fallback %d번: 구현 계열이 바뀌는데 구현 전환으로 기록하지 않음" % index)
        if family_of(current, role) != target:
            raise Mismatch("fallback %d번: 다시 계산한 %s 배정은 %s가 아님" % (index, role, target))
    return current


def validate(manifest, receipt, current_policy):
    """(통과 여부, 사유 목록, 참고). roster 키가 아예 없는 옛 명세는 대조하지 않고 통과시킨다."""
    if not isinstance(manifest, dict) or not isinstance(receipt, dict):
        return False, ["명세 또는 영수증이 객체가 아님"], None
    if "roster" not in manifest:
        return True, [], "legacy_manifest_without_roster"
    if receipt.get("status") != "completed":
        return True, [], "not_a_completed_receipt"
    try:
        reasons = compare(manifest, receipt, current_policy)
    except Mismatch as exc:
        reasons = [str(exc)]
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        reasons = ["명세나 영수증의 형식이 올바르지 않음: %s" % type(exc).__name__]
    return not reasons, reasons, None


def compare(manifest, receipt, current_policy):
    roster = manifest["roster"]
    if not isinstance(roster, dict) or roster.get("lane") not in LANE_RANK or not isinstance(roster.get("roles"), dict):
        raise Mismatch("명세의 roster가 올바르지 않음")
    # 발송 때의 정책으로 대조한다. 명세에 정책이 없으면 지금 정책이 그때와 같은지 지문으로 확인한다.
    policy = manifest.get("policy")
    if policy is None:
        policy = current_policy
        if resolver.policy_digest(policy) != roster.get("policy_digest"):
            raise Mismatch("명세에 정책이 없고 현재 정책이 발송 때와 달라 대조할 수 없음")
    elif resolver.policy_digest(policy) != roster.get("policy_digest"):
        raise Mismatch("명세의 정책이 roster를 계산한 정책과 다름")

    reasons = []
    lane = receipt.get("lane")
    if not isinstance(lane, str) or lane not in LANE_RANK:
        raise Mismatch("lane이 없거나 올바르지 않음")
    if LANE_RANK[lane] < LANE_RANK[roster["lane"]]:
        reasons.append("줄이 명세(%s)보다 낮음: %s" % (roster["lane"], lane))

    implement, review = receipt.get("implement"), receipt.get("review")
    if not isinstance(implement, dict) or not isinstance(review, dict):
        raise Mismatch("implement 또는 review가 객체가 아님")
    for name, value, keys in (("implement", implement, ("family", "model", "session_id")),
                              ("review", review, ("url", "family", "model", "session_id"))):
        bad = [key for key in keys if not text(value.get(key))]
        if bad:
            reasons.append("%s의 문자열 필드가 없거나 올바르지 않음: %s" % (name, ", ".join(bad)))
    if reasons:
        return reasons

    fallback = receipt.get("fallback", [])
    if not isinstance(fallback, list):
        raise Mismatch("fallback이 목록이 아님")
    expected = replay(roster, fallback, policy) if fallback else roster
    roles = expected["roles"]

    # 구현은 배정된 모델이거나, 리뷰 2회째 이후 올린 모델이어야 한다.
    if not (same_role(implement, roles.get("implement")) or same_role(implement, expected.get("escalation"))):
        reasons.append("구현 모델이 배정과 다름: %s/%s" % (implement["family"], implement["model"]))
    reviewer = roles.get("reviewer")
    if not same_role(review, reviewer):
        reasons.append("리뷰 모델이 배정과 다름: %s/%s" % (review["family"], review["model"]))

    if review["session_id"] == implement["session_id"]:
        reasons.append("리뷰 세션이 구현 세션과 같음")
    if review["family"] == implement["family"]:
        if not (reviewer and reviewer.get("same_family")):
            reasons.append("리뷰어가 구현과 같은 계열인데 배정이 허용하지 않음")
        elif review.get("same_family") is not True:
            reasons.append("같은 계열 리뷰인데 영수증에 same_family 표시가 없음")

    # alias_only는 "별칭만 확인됐고 버전은 모른다"는 뜻이다. Claude이고 최종 줄이 L이 아닐 때만 인정한다.
    if review.get("alias_only") is True:
        if review["family"] != "claude" or lane == "L" or roster["lane"] == "L":
            reasons.append("별칭만 확인된 리뷰는 L 줄이 아닌 Claude 리뷰에서만 인정함")
    elif review.get("verified_from_transcript") is not True:
        reasons.append("리뷰 실행 모델을 transcript로 확인하지 않음")

    rounds, limit = review.get("rounds"), expected["limits"]["review_rounds"]
    if type(rounds) is not int or rounds < 1:
        reasons.append("리뷰 횟수가 없거나 올바르지 않음")
    elif rounds > limit:
        reasons.append("리뷰 횟수 %d회가 상한 %d회를 넘음. 완료가 아니라 차단으로 넘겨야 함" % (rounds, limit))
    unresolved = review.get("unresolved_valid_findings")
    if type(unresolved) is not int or unresolved != 0:
        reasons.append("미해결 유효 지적이 정수 0이 아님")
    return reasons


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--manifest", required=True)
    v.add_argument("--receipt", required=True)
    v.add_argument("--policy")
    args = p.parse_args(argv)

    try:
        with open(args.manifest, encoding="utf-8") as f:
            manifest = json.load(f)
        with open(args.receipt, encoding="utf-8") as f:
            receipt = json.load(f)
        ok, reasons, note = validate(manifest, receipt, resolver.load_policy(args.policy))
    except (OSError, ValueError) as exc:
        ok, reasons, note = False, ["명세·영수증·정책을 읽을 수 없음: %s" % type(exc).__name__], None
    result = {"ok": ok, "reasons": reasons}
    if note:
        result["note"] = note
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
