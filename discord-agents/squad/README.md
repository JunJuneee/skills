# 앱인토스 스쿼드 (멀티 역할 봇)

5개 역할이 각자 Discord 봇으로 로그인해, 전용 채널에서 작업/의사결정을 기록하고 `#squad`에서
양방향으로 토론·핸드오버하며 토스 앱인토스 미니앱을 함께 만든다.
페르소나: **PO=스티브(Jobs) · Designer=디터(Rams) · Frontend=댄(Abramov) · Backend=마틴(Fowler) · QA=켄트(Beck)**.

작업 저장소: `/Users/jun/Desktop/toss-miniapp/` (claude -p 의 cwd)

## 파일
- `role_bot.py` — 단일 프로그램, `ROLE` 환경변수로 5회 기동(po/designer/frontend/backend/qa).
- `squad_rules.py` — 레지스트리 + 멘션 치환 + 자율토론 루프 가드.
- `prompts/_common.md` + `prompts/{role}.md` — 시스템 프롬프트(공통 + 역할).
- `state/registry.json` — 각 봇이 on_ready 때 기록하는 role→user_id (멘션 해석/봇 상호인증용).

## 셋업 (사용자 수동)
1. Discord 개발자포털에서 **봇 앱 5개** 생성 → 토큰 발급(**MESSAGE CONTENT intent 필수**) → 서버 초대.
   (봇 이름 예: 스티브 / 디터 / 댄 / 마틴 / 켄트)
2. 채널 6개 생성: `#po #designer #frontend #backend #qa #squad`. 각 채널 ID 확보.
3. `~/claude-agents/secrets.env` 에 토큰/채널ID 채우기:
   `PO_BOT_TOKEN/DESIGNER_BOT_TOKEN/FRONTEND_BOT_TOKEN/BACKEND_BOT_TOKEN/QA_BOT_TOKEN`,
   `CH_PO/CH_DESIGNER/CH_FRONTEND/CH_BACKEND/CH_QA/CH_SQUAD`.

## 로컬 테스트 (봇 1개)
```bash
ROLE=po ~/claude-agents/.venv/bin/python ~/claude-agents/squad/role_bot.py
```
→ #po 에 "PO 봇 가동" 메시지. #po 또는 #squad 에서 봇 멘션 + 질문 → claude 응답.

## 상주화 (launchd, 4봇 모두)
```bash
for r in po designer frontend backend qa; do
  cp ~/claude-agents/launchd/com.jun.claude.squad-$r.plist ~/Library/LaunchAgents/
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jun.claude.squad-$r.plist
done
```
재시작: `launchctl kickstart -k gui/$(id -u)/com.jun.claude.squad-po`
로그: `~/claude-agents/logs/squad-<role>.log`

## 자율토론 가드 (squad_rules.py)
- 본인 메시지/멘션 없는 메시지 무시. 사람=ALLOWED_USER_IDS, 봇=레지스트리 등록 봇만 트리거.
- `#squad` 사람 개입 없이 봇-대-봇 `MAX_BOT_TURNS`(기본 6)턴 초과 → 정지 + "🛑 사람 결정 필요".
  사람이 메시지를 보내면 카운터 리셋. 봇당 응답 최소 간격 `MIN_REPLY_GAP`(기본 4초).
