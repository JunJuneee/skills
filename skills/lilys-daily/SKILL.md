---
name: lilys-daily
description: Lilys 일일 요약 실행 — 사용자가 Bearer 토큰을 제공하면 스킬 폴더의 token.txt를 교체하고 lilys_daliy.py를 실행해 등록 채널의 최근 영상을 Lilys로 자동 요약 요청. "/lilys-daily [토큰]" 트리거.
type: skill
version: 1.0
---

# Lilys Daily — 토큰 교체 & 일일 요약 실행

## 트리거 조건

- 사용자가 Lilys Bearer 토큰을 제공하며 "/lilys-daily" 또는 "릴리스 실행", "lilys 돌려줘" 요청
- 키워드: "lilys", "릴리스", "토큰 교체", "일일 요약 실행"

## 경로

스크립트와 토큰은 이 스킬 폴더 안에 함께 있다 (self-contained).

- 작업 디렉토리: `/Users/jun/Desktop/skills/skills/lilys-daily/`
- 토큰 파일: `/Users/jun/Desktop/skills/skills/lilys-daily/token.txt`
- 실행 스크립트: `/Users/jun/Desktop/skills/skills/lilys-daily/lilys_daliy.py`
- 함께 있는 보조 스크립트: `lilys_channel_all.py`, `lilys_channel_all_seq.py`

## 워크플로우

### 1단계 — 토큰 교체

사용자가 제공한 토큰을 `token.txt`에 한 줄로 덮어쓴다.

- 토큰이 `Bearer `로 시작하면 그대로 사용
- 그렇지 않으면 앞에 `Bearer ` 를 붙여 저장
- 앞뒤 공백/줄바꿈 제거 후 저장 (스크립트가 `.strip()` 으로 읽음)

```bash
# SKILL_DIR = 이 스킬 폴더, TOKEN = 사용자가 준 토큰(JWT 또는 "Bearer eyJ...")
SKILL_DIR=/Users/jun/Desktop/skills/skills/lilys-daily
case "$TOKEN" in
  Bearer\ *) printf '%s' "$TOKEN" > "$SKILL_DIR/token.txt" ;;
  *)         printf 'Bearer %s' "$TOKEN" > "$SKILL_DIR/token.txt" ;;
esac
```

> 토큰은 민감 정보다. 채팅에 토큰 전문을 다시 출력하지 말고, 저장 확인은 앞 12자 + `...` 마스킹으로만 보고한다.

### 2단계 — 스크립트 실행

```bash
cd /Users/jun/Desktop/skills/skills/lilys-daily && python3 lilys_daliy.py
```

- 실행 시간이 길 수 있으므로 백그라운드 실행을 권장한다.
- 출력에는 컬렉션별 기존 등록 건수, 채널별 최근 영상 수, Lilys 요청 성공/실패가 줄 단위로 찍힌다.

### 3단계 — 결과 보고

실행 로그에서 다음을 집계해 한국어로 요약한다.

- 채널별 신규 요청 성공 건수 / 실패 건수
- 스킵 사유별 카운트 (3시간 이상 / 5분 미만 / 이미 등록됨)
- 실패가 있으면 상태코드와 사유 첫 줄을 그대로 인용

## 동작 메모 (lilys_daliy.py)

- 등록 채널 목록과 `collection_id` 는 스크립트 내부에 하드코딩되어 있다.
- 최근 **5일** 이내 업로드 영상만 대상 (`timedelta(days=5)`).
- 길이 필터: **3시간 이상 스킵**, **5분 이하 스킵**.
- 이미 해당 컬렉션에 등록된 `video_id` 는 중복 스킵.
- 토큰 우선순위: 환경변수 `BEARER_TOKEN` > `token.txt`.
  - 일회성 실행이면 `BEARER_TOKEN=...` 로 넘겨 token.txt를 건드리지 않을 수도 있다.
- 토큰 만료 시 Lilys API가 401을 반환한다 → 사용자에게 새 토큰 요청.

## 주의

- `token.txt` 는 절대 git에 커밋하지 않는다 (자격 증명).
- 스크립트 파일명 오타(`lilys_daliy.py`)는 의도된 실제 파일명이므로 그대로 호출한다.
