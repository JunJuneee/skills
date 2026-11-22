"""linear_create 규칙 테스트. 실행: python3 -m pytest skills/linear-create/scripts -q"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import linear_create as lc  # noqa: E402


class FakeLinear:
    """쿼리 문자열로 응답을 고르는 가짜 Linear. 호출된 mutation 입력을 기록한다."""

    def __init__(self, parent_state_type="started", parent_state_name="개발 작업 중"):
        self.parent = {"id": "parent-uuid", "identifier": "JAY-543",
                       "state": {"type": parent_state_type, "name": parent_state_name}}
        self.created = []

    def __call__(self, payload):
        q = payload["query"]
        if "viewer" in q:
            return {"data": {"viewer": {"id": "viewer-1"}}}
        if "teams(" in q:
            return {"data": {"teams": {"nodes": [{"id": "team-jay", "key": "JAY"}]}}}
        if "issues(filter" in q:
            return {"data": {"issues": {"nodes": [self.parent]}}}
        if "issueCreate" in q:
            inp = payload["variables"]["input"]
            self.created.append(inp)
            return {"data": {"issueCreate": {"success": True,
                                             "issue": {"identifier": "JAY-600", "title": inp["title"],
                                                       "url": "https://linear.app/x"}}}}
        raise AssertionError(f"예상 밖 쿼리: {q[:60]}")


def _args(*argv):
    return lc.build_parser().parse_args(list(argv))


def test_default_assignee_is_token_owner():
    fake = FakeLinear()
    lc.run(_args("새 이슈", "--team", "JAY"), post=fake)
    assert fake.created[0]["assigneeId"] == "viewer-1"


def test_explicit_assignee_wins():
    fake = FakeLinear()
    lc.run(_args("새 이슈", "--team", "JAY", "--assignee", "user-kim"), post=fake)
    assert fake.created[0]["assigneeId"] == "user-kim"


def test_parent_sets_parent_id_when_open():
    fake = FakeLinear()
    lc.run(_args("하위", "--team", "JAY", "--parent", "JAY-543"), post=fake)
    assert fake.created[0]["parentId"] == "parent-uuid"


@pytest.mark.parametrize("state_type,name", [("completed", "완료"), ("canceled", "취소됨")])
def test_closed_parent_refused_without_create(state_type, name):
    fake = FakeLinear(parent_state_type=state_type, parent_state_name=name)
    with pytest.raises(lc.LinearError, match="하위 이슈를 만들 수 없습니다"):
        lc.run(_args("하위", "--team", "JAY", "--parent", "JAY-543"), post=fake)
    assert fake.created == []


def test_missing_team_is_refused(monkeypatch):
    monkeypatch.delenv("LINEAR_TEAM_ID", raising=False)
    with pytest.raises(lc.LinearError, match="팀이 없습니다"):
        lc.run(_args("새 이슈"), post=FakeLinear())


def test_bad_parent_identifier_refused():
    with pytest.raises(lc.LinearError, match="형식"):
        lc.run(_args("하위", "--team", "JAY", "--parent", "JAY-abc"), post=FakeLinear())
