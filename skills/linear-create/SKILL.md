---
name: linear-create
description: Linear 이슈를 생성한다. 담당자는 기본으로 본인(오한준)이고, 상위 이슈가 완료·취소된 경우 하위 이슈를 만들지 않는다. "이슈 만들어줘", "리니어에 등록", "하위 이슈 만들어줘", "리니어 이슈 생성" 등의 요청 시 사용.
---

# Linear Create

대화 맥락을 제목·설명으로 정리해 Linear 이슈 하나를 만든다. 상태 변경·조회·PRD 일괄 생성은 이 스킬 범위가 아니다.

## 규칙

1. **담당자 기본값은 본인(토큰 소유자, 오한준)**이다. 다른 사람에게 줄 때만 `--assignee <userId>`를 준다. 이름→id 변환은 하지 않는다(동명이인 위험).
2. **완료(`completed`)·취소(`canceled`) 상위 이슈 아래에는 만들지 않는다.** `--parent`의 부모가 이 상태면 생성 전에 중단한다. 부모는 쓰기 전에 항상 조회한다.
3. **팀은 추정하지 않는다.** `--team <KEY>`(예: `JAY`)를 주거나 `LINEAR_TEAM_ID`를 설정한다. 둘 다 없으면 중단한다.

## 절차

1. 대화 맥락에서 제목과 설명을 정리한다.
2. 아래만 확인한다(AskUserQuestion, 한 번에 묶어서):
   - 제목
   - 상위 이슈 (`--parent`, 없으면 독립 이슈)
   - 담당자 — 기본 본인, 바꿀 때만 userId
   - 팀 — 환경에 `LINEAR_TEAM_ID`가 없을 때만
3. 확인된 내용으로 실행한다. 확인 질문에 이미 답이 있으면 다시 묻지 않는다.

## 실행

```bash
python3 ~/.claude/skills/linear-create/scripts/linear_create.py "<제목>" "<설명>" \
  --team JAY [--parent JAY-543] [--assignee <userId>] [--priority 1-4] [--project <id>] [--label <id>]
```

필요 환경변수: `LINEAR_API_TOKEN`(개인 API 키). 담당자 기본값은 이 토큰의 소유자로 정해지므로 별도 설정이 필요 없다.

## 출력

```
✅ 이슈 생성 완료
   JAY-600: <제목>
   🔗 https://linear.app/...
```

실패 시 이유를 한 줄로 보여 주고 `❌`로 끝낸다. 예:
- `부모 JAY-543가 '완료' 상태입니다. 완료·취소된 이슈 아래에는 하위 이슈를 만들 수 없습니다.` → 상위를 바꾸거나 독립 이슈로 만들지 확인한다.
- `팀이 없습니다.` → `--team`을 준다.

## 테스트

```bash
python3 -m pytest skills/linear-create/scripts -q
```
