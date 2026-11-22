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


def criteria_pattern(headings):
    """완료 기준 제목을 찾는 정규식. 앞의 #·굵은 글씨·번호(1.)를 허용한다."""
    words = "|".join(re.escape(h).replace(r"\ ", r"\s*") for h in headings)
    return re.compile(r"^\s{0,3}(?:#{1,6}\s*|\*\*)?(?:\d+[.)]\s*)?(?:" + words + r")(?!\w)", re.I)

NUMBERED_TITLE = re.compile(r"^\d+[.)]\s+\S")
LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S")


def level(line):
    """제목 줄의 깊이. # 개수이고, 굵은 글씨나 표식 없는 제목은 가장 깊은 7이다."""
    hashes = re.match(r"\s{0,3}(#{1,6})\s", line)
    return len(hashes.group(1)) if hashes else 7


def sections(description, criteria=None):
    """(깊이, 제목 줄, 그 제목 바로 아래 줄들)의 목록. 첫 제목 앞의 글은 깊이 0이다.

    criteria를 주면 표식 없이 적은 완료 기준 제목 줄도 제목으로 본다.
    """
    out = [(0, "", [])]
    for line in (description or "").splitlines():
        if HEADING.match(line) or (criteria and criteria.match(line)):
            out.append((level(line), line, []))
        else:
            out[-1][2].append(line)
    return out


def under(parts, index):
    """index번 제목에 속한 모든 줄. 같은 깊이나 상위 제목이 나오면 끝나고 하위 제목의 글은 포함한다."""
    depth = parts[index][0]
    lines = list(parts[index][2])
    for deeper, title, body in parts[index + 1:]:
        if deeper <= depth:
            break
        lines += [title] + body
    return lines


CHECKED_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\[[xX]\]\s")


def criteria_state(description, headings):
    """완료 기준 제목 아래(하위 제목 포함)의 목록 상태.

    "missing"은 목록이 없음, "done"은 모든 항목이 체크된 체크박스라 남은 일이 없음, "open"은 할 일이 있음이다.
    """
    criteria = criteria_pattern(headings)
    parts = sections(description, criteria)
    items = []
    for i, (_, title, _) in enumerate(parts):
        if not criteria.match(title):
            continue
        lines = under(parts, i)
        if NUMBERED_TITLE.match(title.lstrip()):
            # "1. 완료 기준"처럼 번호로 쓴 제목이면 다음 번호 줄("2. 참고")이 다음 제목이다.
            end = next((n for n, line in enumerate(lines) if NUMBERED_TITLE.match(line)), len(lines))
            lines = lines[:end]
        items += [line for line in lines if LIST_ITEM.match(line)]
    if not items:
        return "missing"
    return "done" if all(CHECKED_ITEM.match(line) for line in items) else "open"


def predecessors(description, headings=()):
    """선행으로 선언된 이슈 식별자(대문자).

    선행 제목 아래(하위 제목 포함)에 적힌 식별자는 모두, 그 밖의 줄에서는 선행을 뜻하는 말 뒤에
    나오는 식별자만 센다. "JAY-1, JAY-2의 계약·선행을 확인한다"처럼 앞에 나열된 것은 참조로 본다.
    완료 기준 제목에서 선행 섹션이 끝나도록 같은 제목 규칙으로 나눈다.
    """
    parts = sections(description, criteria_pattern(headings) if headings else None)
    found = set()

    def after_word(line):
        word = PREDECESSOR_WORD.search(line)
        return ISSUE_ID.findall(line[word.end():]) if word else []

    for i, (_, title, body) in enumerate(parts):
        if PREDECESSOR_WORD.search(title):
            found.update(after_word(title))
            for line in under(parts, i):
                found.update(ISSUE_ID.findall(line))
        for line in body:
            found.update(after_word(line))
    return {match.upper() for match in found}


def risky_words(text, words):
    """ASCII 단어는 단어 단위로, 그 밖에는 부분 문자열로 찾는다."""
    lowered = text.lower()
    hits = []
    for word in words:
        key = word.lower()
        if key.isascii():
            # 뒤에 붙는 숫자는 허용한다(OAuth2). author처럼 글자가 이어지면 다른 단어다.
            if re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z])", lowered):
                hits.append(word)
        elif key in lowered:
            hits.append(word)
    return hits


def from_linear(node, repo, has_open_pr):
    """실행기가 Linear에서 읽은 이슈 노드를 사전 점검 입력 모양으로 바꾼다."""
    relations = node.get("inverseRelations") or {}
    children = node.get("children") or {}
    blocked_by = [{"identifier": r["issue"]["identifier"], "state_type": r["issue"]["state"]["type"]}
                  for r in relations.get("nodes", []) if r.get("type") == "blocks"]
    # 관계나 하위 이슈를 다 읽지 못했으면 실행하지 않도록 미완료로 본다.
    if (relations.get("pageInfo") or {}).get("hasNextPage"):
        blocked_by.append({"identifier": "(관계 일부만 조회됨)", "state_type": "unknown"})
    return {
        "identifier": node.get("identifier"),
        "title": node.get("title") or "",
        "description": node.get("description") or "",
        "state": (node.get("state") or {}).get("name"),
        "labels": [label["name"] for label in (node.get("labels") or {}).get("nodes", [])],
        "labels_partial": bool(((node.get("labels") or {}).get("pageInfo") or {}).get("hasNextPage")),
        "children": len(children.get("nodes", [])) + int(bool((children.get("pageInfo") or {}).get("hasNextPage"))),
        "has_open_pr": bool(has_open_pr),
        "blocked_by": blocked_by,
        "repo": repo,
    }


def check(issue, policy, project=None):
    intake = dict(policy["intake"])
    # 프로젝트가 따로 정한 ready 상태와 완료 기준 제목이 있으면 그것을 쓴다.
    for key in ("ready_states", "criteria_headings"):
        override = policy["projects"].get(project, {}).get(key)
        if override:
            intake[key] = override
    labels = [label.lower() for label in issue.get("labels", [])]
    title = issue.get("title", "")
    description = issue.get("description") or ""
    reasons = []

    if issue.get("state") not in intake["ready_states"]:
        reasons.append("상태가 %s가 아님: %s" % ("·".join(intake["ready_states"]), issue.get("state")))
    if issue.get("labels_partial"):
        reasons.append("라벨을 일부만 조회해 제어 라벨이 없는지 알 수 없음")
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
    missing = sorted(predecessors(description, intake["criteria_headings"]) - known)
    if missing:
        reasons.append("본문의 선행 이슈가 blocks 관계로 연결되지 않음: " + ", ".join(missing))

    state = criteria_state(description, intake["criteria_headings"])
    if state == "missing":
        reasons.append("완료 기준을 찾을 수 없음")
    elif state == "done":
        reasons.append("완료 기준이 모두 체크돼 있어 남은 작업이 없음")
    if not issue.get("repo"):
        reasons.append("대상 저장소가 하나로 정해지지 않음")

    lanes = [intake["lane_labels"][label] for label in labels if label in intake["lane_labels"]]
    if len(set(lanes)) > 1:
        reasons.append("줄 라벨이 둘 이상")
    lane = lanes[0] if lanes else policy["default_lane"]
    # 사람이 줄 라벨을 직접 붙였으면 그 판단을 따른다. 라벨이 없을 때만 단어로 확인을 요청한다.
    if not lanes:
        hits = risky_words(title + "\n" + description, intake["high_risk_keywords"])
        if hits:
            reasons.append("고위험 단어(%s)가 있는데 줄 라벨이 없음. lane-m 또는 lane-l로 확인해야 함" % ", ".join(hits))
    return lane, reasons


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    p.add_argument("--exhausted", default="")
    p.add_argument("--switches", type=int, default=0)
    p.add_argument("--now")
    p.add_argument("--night-roster", choices=["auto", "on", "off"])
    p.add_argument("--policy")
    p.add_argument("--from-linear", action="store_true", help="입력이 실행기가 읽은 Linear 이슈 노드다")
    p.add_argument("--repo", help="--from-linear일 때 확정된 대상 저장소")
    p.add_argument("--has-open-pr", action="store_true", help="--from-linear일 때 이 이슈의 열린 PR이 있음")
    args = p.parse_args(argv)

    policy = resolver.load_policy(args.policy)
    try:
        exhausted = resolver.parse_exhausted(args.exhausted, policy)
    except ValueError as exc:
        p.error(str(exc))
    issue = json.load(sys.stdin)
    if args.from_linear:
        issue = from_linear(issue, args.repo, args.has_open_pr)
    lane, reasons = check(issue, policy, args.project)
    result = {"identifier": issue.get("identifier"), "ok": not reasons, "lane": lane, "reasons": reasons}
    code = 2 if reasons else 0
    if not reasons:
        now = datetime.datetime.fromisoformat(args.now) if args.now else datetime.datetime.now(resolver.KST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=resolver.KST)
        switch = args.night_roster or resolver.read_switch(policy)
        roster = resolver.resolve(policy, args.project, lane, switch, now, exhausted, args.switches)
        result["roster"] = roster
        # 영수증을 발송 때의 정책으로 대조할 수 있게 병합된 정책을 함께 돌려준다.
        result["policy"] = policy
        if roster["wait"]:
            result["ok"] = False
            result["reasons"] = ["모델 대기: " + ", ".join(roster["wait"])]
            code = 3
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
