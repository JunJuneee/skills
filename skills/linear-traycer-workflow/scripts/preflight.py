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
ISSUE_ID = re.compile(r"\b([A-Za-z][A-Za-z0-9]+-\d+)\b")
PREDECESSOR_WORD = re.compile(r"선행|선결|blocked by|depends on|requires", re.I)
HEADING = re.compile(r"^\s{0,3}(?:#{1,6}\s+.*|\*\*[^*]+\*\*:?\s*)$")
CRITERIA_HEADING = re.compile(r"^\s{0,3}(?:#{1,6}\s*|\*\*)?(?:완료\s*기준|acceptance criteria|AC)\b", re.I)
LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S")


def sections(description):
    """(제목 줄, 본문 줄들)의 목록. 첫 제목 앞의 글은 제목이 빈 문자열이다."""
    out = [("", [])]
    for line in (description or "").splitlines():
        if HEADING.match(line) or CRITERIA_HEADING.match(line):
            out.append((line, []))
        else:
            out[-1][1].append(line)
    return out


def has_criteria(description):
    """완료 기준 제목 아래, 다음 제목 전까지에 목록 항목이 있어야 한다."""
    return any(CRITERIA_HEADING.match(title) and any(LIST_ITEM.match(line) for line in body)
               for title, body in sections(description))


def predecessors(description):
    """선행을 말하는 줄과 선행 제목 아래에 적힌 모든 이슈 식별자(대문자)."""
    found = set()
    for title, body in sections(description):
        in_section = bool(PREDECESSOR_WORD.search(title))
        for line in [title] + body:
            if in_section or PREDECESSOR_WORD.search(line):
                found.update(match.upper() for match in ISSUE_ID.findall(line))
    return found


def risky_words(text, words):
    """ASCII 단어는 단어 단위로, 그 밖에는 부분 문자열로 찾는다."""
    lowered = text.lower()
    hits = []
    for word in words:
        key = word.lower()
        if key.isascii():
            if re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", lowered):
                hits.append(word)
        elif key in lowered:
            hits.append(word)
    return hits


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
    known = {str(b["identifier"]).upper() for b in blockers} | {str(issue.get("identifier")).upper()}
    missing = sorted(predecessors(description) - known)
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
        hits = risky_words(title + "\n" + description, intake["high_risk_keywords"])
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
    try:
        exhausted = resolver.parse_exhausted(args.exhausted, policy)
    except ValueError as exc:
        p.error(str(exc))
    issue = json.load(sys.stdin)
    lane, reasons = check(issue, policy)
    result = {"identifier": issue.get("identifier"), "ok": not reasons, "lane": lane, "reasons": reasons}
    code = 2 if reasons else 0
    if not reasons:
        now = datetime.datetime.fromisoformat(args.now) if args.now else datetime.datetime.now(resolver.KST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=resolver.KST)
        switch = args.night_roster or resolver.read_switch(policy)
        roster = resolver.resolve(policy, args.project, lane, switch, now, exhausted, args.switches)
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
