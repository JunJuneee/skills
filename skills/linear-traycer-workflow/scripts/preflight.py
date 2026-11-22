#!/usr/bin/env python3
"""발송 전 사전 점검. 모델을 부르지 않고 이슈 하나가 실행 가능한지 판정한다.

표준 입력으로 정규화한 이슈 JSON을 받는다.

    {"identifier": "JAY-1", "title": "...", "description": "...", "state": "Todo",
     "labels": ["lane-m"], "children": 0, "has_open_pr": false,
     "blocked_by": [{"identifier": "JAY-0", "state_type": "completed"}],
     "repo": "JunJuneee/seoul-seeing"}

출력은 {"ok": bool, "lane": "M", "reasons": [...], "roster": {...}} 이다.
종료 코드는 0 실행 가능, 2 이슈 문제로 실행 불가, 3 모델 대기다.
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve as resolver  # noqa: E402

DONE_TYPES = {"completed", "canceled"}
PREDECESSOR = re.compile(r"(?:선행|선결|blocked by|depends on|requires)[^\n]{0,40}?\b([A-Z][A-Z0-9]+-\d+)", re.I)
CRITERIA_HEADING = re.compile(r"^\s{0,3}(?:#{1,6}\s*|\*\*)?(?:완료\s*기준|acceptance criteria|AC)\b.*$", re.I | re.M)
LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S", re.M)


def has_criteria(description):
    found = CRITERIA_HEADING.search(description or "")
    return bool(found and LIST_ITEM.search(description[found.end():]))


def check(issue, policy):
    intake = policy["intake"]
    labels = [label.lower() for label in issue.get("labels", [])]
    title = issue.get("title", "")
    description = issue.get("description") or ""
    reasons = []

    if issue.get("state") != intake["ready_state"]:
        reasons.append("상태가 %s가 아님: %s" % (intake["ready_state"], issue.get("state")))
    held = [label for label in labels if label in intake["control_labels"]]
    if held:
        reasons.append("제어 라벨: " + ", ".join(held))
    if issue.get("children") or "epic:" in title.lower():
        reasons.append("에픽 또는 하위 이슈가 있는 상위 이슈")
    if issue.get("has_open_pr"):
        reasons.append("이미 열린 PR이 있음")

    blockers = issue.get("blocked_by", [])
    pending = [b["identifier"] for b in blockers if b.get("state_type") not in DONE_TYPES]
    if pending:
        reasons.append("선행 이슈 미완료: " + ", ".join(pending))
    known = {b["identifier"] for b in blockers} | {issue.get("identifier")}
    missing = sorted(set(PREDECESSOR.findall(description)) - known)
    if missing:
        reasons.append("본문의 선행 이슈가 blocks 관계로 연결되지 않음: " + ", ".join(missing))

    if not has_criteria(description):
        reasons.append("완료 기준을 찾을 수 없음")
    if not issue.get("repo"):
        reasons.append("대상 저장소가 하나로 정해지지 않음")

    lanes = [intake["lane_labels"][label] for label in labels if label in intake["lane_labels"]]
    if len(set(lanes)) > 1:
        reasons.append("줄 라벨이 둘 이상")
    lane = lanes[0] if lanes else policy["default_lane"]
    if lane != "L":
        text = (title + "\n" + description).lower()
        hits = [word for word in intake["high_risk_keywords"] if word.lower() in text]
        if hits:
            reasons.append("고위험 단어(%s)가 있는데 lane-l이 아님. 줄을 확인해야 함" % ", ".join(hits))
    return lane, reasons


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    p.add_argument("--exhausted", default="")
    p.add_argument("--switches", type=int, default=0)
    p.add_argument("--now")
    p.add_argument("--night-roster", choices=["auto", "on", "off"])
    p.add_argument("--policy")
    args = p.parse_args(argv)

    policy = resolver.load_policy(args.policy)
    issue = json.load(sys.stdin)
    lane, reasons = check(issue, policy)
    result = {"identifier": issue.get("identifier"), "ok": not reasons, "lane": lane, "reasons": reasons}
    code = 2 if reasons else 0
    if not reasons:
        now = datetime.datetime.fromisoformat(args.now) if args.now else datetime.datetime.now(resolver.KST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=resolver.KST)
        switch = args.night_roster or resolver.read_switch(policy)
        roster = resolver.resolve(policy, args.project, lane, switch, now,
                                  [x for x in args.exhausted.split(",") if x], args.switches)
        result["roster"] = roster
        if roster["wait"]:
            result["ok"] = False
            result["reasons"] = ["모델 대기: " + ", ".join(roster["wait"])]
            code = 3
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
