# 금융 봇 자동화 스케줄

투자 리포트·알림·숏츠 파이프라인을 자동 실행하는 잡 전체 목록과 설치·운영 방법.

> **cron이 아니라 launchd다.** macOS에서 `crontab`은 비어 있고, 모든 잡은
> `~/Library/LaunchAgents/*.plist`로 등록되어 있다. 이 디렉터리의 plist가 그 원본이다.
> cron을 쓰지 않는 이유는 (1) 슬립 복귀 후 놓친 잡 처리, (2) `KeepAlive`로 상시 프로세스
> 관리, (3) 잡별 stdout/stderr 로그 경로 분리가 launchd에서만 깔끔하게 되기 때문이다.

> 진단·복구를 Claude에게 시키려면 [`skills/finance-bot-automation`](../skills/finance-bot-automation/SKILL.md)
> 스킬을 쓴다. 이 문서는 그 스킬이 참조하는 원본이다.

---

## 전체 스케줄 한눈에

| 잡 (Label) | 실행 대상 | 시각 | cron 환산 |
|---|---|---|---|
| `com.jun.claude.premarket` | `reports/premarket_send.py` | 월~금 **08:01** | `1 8 * * 1-5` |
| `com.jun.claude.closing` | `reports/closing_send.py` | 월~금 **15:40** | `40 15 * * 1-5` |
| `com.jun.claude.monitor` | `reports/price_monitor.py` | **300초(5분)마다** | `*/5 * * * *` |
| `com.jun.claude.marketnote-kr` | `run-shorts.sh marketnote-kr` | 월~금 **16:00** | `0 16 * * 1-5` |
| `com.jun.claude.marketnote-us` | `run-shorts.sh marketnote-us` | 화~토 **07:00** | `0 7 * * 2-6` |
| `com.jun.kospi200-daily` | `stock-trading/scripts/daily_kospi200_report.py` | 월~금 **16:00** | `0 16 * * 1-5` |
| `com.jun.krx-flow-collect` | `dart-insight/src/krx_flow/auto_collect.py` | 매일 **18:00** | `0 18 * * *` |
| `com.jun.us-futures-check` | `krx_flow/us_futures.py --quiet` | 매일 **06:00, 08:00** | `0 6,8 * * *` |
| `com.jun.claude.discordbot` | `bot/bot.py` | 상시 (RunAtLoad + KeepAlive) | — |
| `com.jun.claude.keepalive` | `caffeinate -ims` | 상시 (슬립 방지) | — |

### 요일 번호 주의

launchd `Weekday`는 **1=월 … 5=금, 6=토, 0 또는 7=일**이다. cron의 `0=일`과 기준이
다르므로 plist를 직접 고칠 때 헷갈리기 쉽다. 위 표의 cron 환산은 참고용이며,
실제 등록은 전부 launchd `StartCalendarInterval` 기준이다.

### 하루 타임라인

```
06:00  us-futures-check      미국 선물 야간 흐름 점검
07:00  marketnote-us         (화~토) 미국 마감 기준 숏츠 제작·발행
08:00  us-futures-check      장 시작 전 재확인
08:01  premarket             보유 종목 프리마켓 가격 + 시황 → 디스코드
09:00~15:30
       monitor               5분마다 트리거 라인 감시 (이 시간대 밖이면 즉시 종료)
15:40  closing               종가/등락/RSI/이격도 + v1.8 5단계 분석 → 디스코드
16:00  marketnote-kr         국내 마감 기준 숏츠 제작·발행
16:00  kospi200-daily        KOSPI 200 일일 리포트
18:00  krx-flow-collect      KRX 수급 데이터 수집 → SQLite
```

---

## 잡별 상세

### `premarket` — 프리마켓 알림 (월~금 08:01)

`reports/premarket_send.py`. 장 시작 전 보유 종목 상태와 시황을 디스코드로 보낸다.

1. `kis/premarket.py` 실행 → 보유 종목 프리마켓 가격 + 수급
2. `claude -p prompts/premarket.md` 실행 → 시황 분석 (한줄요약 + 상세)
3. 봇 API로 메인 채널에 헤더(한줄요약) 전송 → `message_id` 반환
4. 같은 봇 토큰으로 그 `message_id`에 쓰레드 생성
5. 쓰레드에 시황 상세 + 보유 종목 프리마켓 정보를 분할 전송

로그: `~/claude-agents/logs/launchd.premarket.log`

### `closing` — 장 마감 알림 (월~금 15:40)

`reports/closing_send.py`. `premarket`과 동일한 4단계 패턴이고 데이터 소스와
프롬프트만 다르다.

1. `kis/closing.py` 실행 → 보유 종목 종가/등락/RSI/이격도
2. `claude -p prompts/portfolio.md` 실행 → v1.8 5단계 분석
3~5. 헤더 → 쓰레드 생성 → 상세 분할 전송 (premarket과 동일)

15:40인 이유는 정규장 마감(15:30) 직후 종가가 확정되는 시점을 잡기 위해서다.

로그: `~/claude-agents/logs/launchd.closing.log`

### `monitor` — 장중 가격 모니터 (5분 주기)

`reports/price_monitor.py`. `StartCalendarInterval`이 아니라 `StartInterval 300`으로
무조건 5분마다 깨어나고, **시간대 판정은 스크립트가 직접 한다.**

1. `data/monitor_rules.json` 로드
2. 평일 09:00~15:30 KST 이외면 즉시 종료 (그래서 5분 주기여도 부담이 없다)
3. KIS `inquire_price`로 각 종목 현재가 조회
4. 트리거 라인 매칭 (`below`: 가격 ≤ trigger.price / `above`: 가격 ≥ trigger.price)
5. 상태 파일(`logs/monitor_state.json`) 비교
   - 오늘 이미 알린 트리거는 차단 (중복 알림 방지)
   - 가격이 라인 +1% 위로 회복되면 상태 리셋
6. 새 트리거 발생 시에만 디스코드로 단발 메시지

로그: `~/claude-agents/logs/launchd.monitor.log` (5분마다 쌓여 가장 빨리 커진다)

### `marketnote-kr` / `marketnote-us` — 숏츠 자동 제작·발행

`run-shorts.sh <에이전트이름> <프롬프트파일>`로 실행된다. 읽기 전용 리포트용
`run-agent.sh`와 달리 이 러너를 쓰는 이유는:

- 허용 도구에 Write/Edit와 `npx`/`ffmpeg`/`uv`/`gh`가 포함된다 (파일 생성 · Remotion 렌더 · 유튜브/인스타 업로드에 필요)
- 타임아웃 기본 **5400초**. TTS 합성 + whisper 분석 + 렌더까지 10분으로는 안 끝난다
- launchd는 `.zshrc`를 읽지 않으므로 ELEVENLABS/INSTAGRAM 키를 직접 주입한다

`marketnote-us`가 **화~토**인 것은 미국 장 마감이 한국 시간 기준 다음 날 새벽이기
때문이다. 월요일 07:00에는 다룰 미국 장이 없고, 토요일 07:00에는 금요일 미국 장이 있다.

로그: `~/claude-agents/logs/launchd.marketnote-{kr,us}.log`

### `kospi200-daily` — KOSPI 200 일일 리포트 (월~금 16:00)

`/bin/zsh -ic`로 실행해 `.zshrc`를 읽는 유일한 잡이다. `uv run`이 PATH에 의존하기
때문인데, 그 대가로 `.zshrc` 안의 `rbenv` 같은 미설치 명령이 로그에 경고를 남긴다
(동작에는 영향 없음). 주말에는 스크립트가 자체 판정해 "주말 — 실행 생략"으로 끝난다.

로그: `~/claude-agents/logs/kospi200_daily.log`

### `krx-flow-collect` — KRX 수급 수집 (매일 18:00)

`dart-insight/src/krx_flow/auto_collect.py`. 외국인/기관 매매 데이터를 KIS API로 받아
SQLite(`data/krx_flow.db`)에 적재한다. `krx-flow` 스킬이 이 DB를 읽는다.

로그: `~/chikitaka/dart-insight/logs/auto_collect.log` (+ `_err.log` 분리)

### `us-futures-check` — 미국 선물 점검 (매일 06:00, 08:00)

`krx_flow/us_futures.py --quiet`. 야간 미국 선물 흐름을 확인해 국내 장 시작 전
참고 지표를 남긴다. 06시는 야간 흐름 마감, 08시는 장 시작 직전 재확인용이다.

로그: `~/chikitaka/dart-insight/logs/us_futures_{stdout,stderr}.log`

### `discordbot` / `keepalive` — 상시 프로세스

- `discordbot`: 위 잡들이 알림을 보내는 **수신·발신 양방향 봇**. 2026-06-19 정책으로
  webhook을 걷어내고 모든 알림을 이 봇 하나로 통일했다. 죽으면 `KeepAlive`가
  15초(`ThrottleInterval`) 후 되살린다. **이게 꺼져 있으면 스케줄 잡이 정상
  실행돼도 알림이 안 온다.**
- `keepalive`: `caffeinate -ims`. 맥이 슬립에 들어가면 예약 잡이 밀리므로 막아둔다.

---

## 시크릿 처리

**이 디렉터리의 plist에는 API 키가 들어 있지 않다.** 실제 등록본 일부에는
`EnvironmentVariables`로 `KIS_PAPER_KEY` / `KIS_PAPER_SECRET`이 평문으로 박혀 있었지만,
레포에 올릴 때 의도적으로 제거했다.

제거해도 동작에 문제가 없는 이유는 `premarket_send.py` · `closing_send.py` ·
`price_monitor.py` 세 스크립트 모두 시작 시 `_load_env()`로
`~/claude-agents/secrets.env` → `~/claude-agents/config.sh` 순서로 환경변수를 직접
읽기 때문이다. plist의 env 블록은 중복이었다.

키를 바꿀 때는 `secrets.env` 한 곳만 고치면 된다. plist에는 절대 다시 넣지 말 것.

---

## 설치

```bash
# 1. plist 복사 (경로에 하드코딩된 /Users/jun 을 본인 환경에 맞게 먼저 수정)
cp automation/launchd/*.plist ~/Library/LaunchAgents/

# 2. 등록
for f in ~/Library/LaunchAgents/com.jun.*.plist; do
  launchctl bootstrap gui/$UID "$f"
done
```

## 운영 명령

```bash
# 등록 상태 확인 (2번째 열이 마지막 종료 코드)
launchctl list | grep com.jun

# 영구 비활성 플래그 확인 — 이게 핵심이다
launchctl print-disabled gui/$UID | grep com.jun

# 잡 하나 되살리기
launchctl enable    gui/$UID/com.jun.claude.closing
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.jun.claude.closing.plist

# 잡 하나 내리기
launchctl bootout gui/$UID/com.jun.claude.closing

# 스케줄 기다리지 않고 즉시 한 번 실행 (테스트용)
launchctl kickstart -p gui/$UID/com.jun.claude.closing

# plist 문법 검증 (수정 후 필수)
plutil -lint automation/launchd/*.plist
```

---

## 트러블슈팅

### 잡이 조용히 안 돌 때 — `disabled` 플래그부터 본다

가장 자주 겪는 함정. `launchctl disable`로 끈 잡은 **재부팅해도 그대로 꺼져 있고**,
plist를 다시 `bootstrap` 해도 올라오지 않는다. `launchctl list`에는 아예 안 보여서
"등록이 풀렸나?"로 오해하기 쉽다.

```bash
launchctl print-disabled gui/$UID | grep com.jun
```

여기서 `=> disabled`로 나오면 `bootstrap` 전에 반드시 `enable`을 먼저 해야 한다.

> 실제로 2026-09-19 점검 시 금융 잡 대부분이 이 상태였다. claude-agents 계열
> (premarket · closing · monitor · discordbot · marketnote)은 09-15 21:5x에 일괄로,
> dart-insight 계열(krx-flow-collect · us-futures-check)은 07-24~25부터 멈춰 있었다.
> 정상 동작 중이던 건 `kospi200-daily` 하나뿐이었다.

### 마지막 실행 시각으로 빠르게 진단

로그 파일의 mtime이 가장 정확한 단서다.

```bash
ls -lt ~/claude-agents/logs/ | head
ls -lt ~/chikitaka/dart-insight/logs/
```

각 잡이 언제 마지막으로 돌았는지 바로 보인다. 스케줄 시각과 안 맞으면 그 잡이 죽은 것이다.

### 알림만 안 올 때

스케줄 잡은 돌았는데 디스코드에 아무것도 안 오면 `discordbot`이 죽은 경우가 많다.
`launchctl list | grep discordbot`으로 확인한다.

### `.zshrc` 관련 경고

`kospi200-daily`만 `/bin/zsh -ic`를 쓰므로 `.zshrc`의 미설치 명령 경고
(`command not found: rbenv` 등)가 로그에 섞인다. 무시해도 된다. 나머지 잡은
`.zshrc`를 읽지 않으므로 필요한 환경변수는 plist나 `secrets.env`로 직접 줘야 한다.
