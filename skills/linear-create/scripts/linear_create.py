#!/usr/bin/env python3
"""Linear 이슈 생성기.

규칙
- 담당자 기본값: 이 워크스페이스의 본인(viewer) — JAY 워크스페이스에서는 Jay. `--assignee <userId>`로 재지정.
- `--parent <ID>`: 부모가 completed/canceled면 생성하지 않는다(생성 전 중단).
- 팀: `--team <KEY>` 또는 LINEAR_TEAM_ID. 둘 다 없으면 중단(기본 팀을 가정하지 않는다).

실행 경로: Composio CLI(`composio execute LINEAR_RUN_QUERY_OR_MUTATION`)로 Linear GraphQL을 호출한다.
계정은 LINEAR_COMPOSIO_ACCOUNT(기본 `linear_valsa-tenino` = "Jay's workplace")로 고른다.
"""

import argparse
import json
import os
import subprocess
import sys

DEFAULT_COMPOSIO_ACCOUNT = "linear_valsa-tenino"
CLOSED_PARENT_STATE_TYPES = ("completed", "canceled")


class LinearError(RuntimeError):
    pass


def composio_post(payload):
    """GraphQL 페이로드를 Composio로 실행하고 {"data", "errors"} 모양으로 돌려준다."""
    account = os.environ.get("LINEAR_COMPOSIO_ACCOUNT") or DEFAULT_COMPOSIO_ACCOUNT
    body = json.dumps({"query_or_mutation": payload["query"], "variables": payload["variables"]})
    try:
        proc = subprocess.run(
            ["composio", "execute", "LINEAR_RUN_QUERY_OR_MUTATION", "--account", account, "-d", body],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        raise LinearError("composio CLI가 없습니다. `composio login` 후 다시 실행하세요.")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise LinearError(f"Composio 응답을 해석할 수 없습니다: {(proc.stdout or proc.stderr)[:200]}")
    if not out.get("successful"):
        raise LinearError(f"Composio 실행 실패: {out.get('error')}")
    inner = (out.get("data") or {})
    return {"data": inner.get("data"), "errors": inner.get("errors")}


def graphql(query, variables=None, post=None):
    """post: 테스트용 주입점. 기본은 Composio 경유 Linear 호출."""
    post = post or composio_post
    body = post({"query": query, "variables": variables or {}})
    if body.get("errors"):
        raise LinearError(f"Linear API 오류: {body['errors'][0].get('message')}")
    return body.get("data") or {}


def get_viewer_id(post=None):
    return graphql("{ viewer { id } }", post=post)["viewer"]["id"]


def resolve_team_id(team_key, post=None):
    data = graphql(
        "query($k: String!) { teams(filter: {key: {eq: $k}}, first: 1) { nodes { id key } } }",
        {"k": team_key}, post=post,
    )
    nodes = (data.get("teams") or {}).get("nodes") or []
    if not nodes:
        raise LinearError(f"팀을 찾을 수 없습니다: {team_key} (이 토큰의 워크스페이스에 있는지 확인)")
    return nodes[0]["id"]


def get_issue_by_identifier(identifier, post=None):
    team_key, _, number = identifier.partition("-")
    if not number.isdigit():
        raise LinearError(f"부모 식별자 형식이 올바르지 않습니다: {identifier} (예: JAY-543)")
    data = graphql(
        """query($f: IssueFilter!) {
            issues(filter: $f, first: 1) { nodes { id identifier state { type name } } }
        }""",
        {"f": {"team": {"key": {"eq": team_key}}, "number": {"eq": int(number)}}},
        post=post,
    )
    nodes = (data.get("issues") or {}).get("nodes") or []
    if not nodes:
        raise LinearError(f"해당 이슈를 찾을 수 없습니다: {identifier}")
    return nodes[0]


def assert_parent_open(parent):
    state = parent.get("state") or {}
    if state.get("type") in CLOSED_PARENT_STATE_TYPES:
        raise LinearError(
            f"부모 {parent.get('identifier')}가 '{state.get('name')}' 상태입니다. "
            "완료·취소된 이슈 아래에는 하위 이슈를 만들 수 없습니다."
        )


def create_issue(team_id, title, description="", assignee_id=None, parent_id=None,
                 project_id=None, priority=None, label_ids=None, cycle_id=None, post=None):
    inp = {"title": title, "teamId": team_id}
    optional = {
        "description": description, "assigneeId": assignee_id, "parentId": parent_id,
        "projectId": project_id, "priority": priority, "labelIds": label_ids, "cycleId": cycle_id,
    }
    inp.update({k: v for k, v in optional.items() if v not in (None, "", [])})
    data = graphql(
        """mutation($input: IssueCreateInput!) {
            issueCreate(input: $input) { success issue { identifier title url } }
        }""",
        {"input": inp}, post=post,
    )
    result = data["issueCreate"]
    if not result.get("success"):
        raise LinearError("issueCreate가 success=false를 반환했습니다.")
    return result["issue"]


def build_parser():
    p = argparse.ArgumentParser(description="Linear 이슈 생성 (담당자 기본 본인, 완료 부모 차단)")
    p.add_argument("title")
    p.add_argument("description", nargs="?", default="")
    p.add_argument("--team", help="팀 key (예: JAY). 없으면 LINEAR_TEAM_ID")
    p.add_argument("--parent", help="상위 이슈 식별자 (예: JAY-543)")
    p.add_argument("--assignee", help="담당자 userId. 없으면 토큰 소유자(본인)")
    p.add_argument("--project")
    p.add_argument("--priority", type=int, choices=[1, 2, 3, 4])
    p.add_argument("--label", action="append", dest="labels")
    return p


def run(args, post=None):
    """인자 객체를 받아 이슈를 만든다. 실패는 LinearError."""
    if args.team:
        team_id = resolve_team_id(args.team, post=post)
    else:
        team_id = os.environ.get("LINEAR_TEAM_ID", "")
        if not team_id:
            raise LinearError("팀이 없습니다. --team <KEY> 또는 LINEAR_TEAM_ID를 지정하세요.")

    parent_id = None
    if args.parent:
        parent = get_issue_by_identifier(args.parent, post=post)
        assert_parent_open(parent)  # 생성 전 중단
        parent_id = parent["id"]

    assignee_id = args.assignee or get_viewer_id(post=post)
    return create_issue(
        team_id, args.title, args.description, assignee_id=assignee_id,
        parent_id=parent_id, priority=args.priority, label_ids=args.labels, post=post,
    )


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        issue = run(args)
    except LinearError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    print("✅ 이슈 생성 완료")
    print(f"   {issue['identifier']}: {issue['title']}")
    print(f"   🔗 {issue['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
