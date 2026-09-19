---
name: finance-bot-automation
description: 금융 봇 정기 실행 잡(프리마켓·마감·가격모니터·숏츠·KRX수급) 진단과 복구 — launchd 등록 상태 확인, disabled 잡 되살리기, 스케줄 조회, 새 잡 추가. "알림이 안 와", "크론 어떻게 걸려있지", "잡이 안 돈다" 류 질문에 사용.
type: skill
version: 1.0
---

# Finance Bot Automation — 정기 잡 진단·복구

## 트리거 조건

- "금융 봇 cron 어떻게 걸려있지", "스케줄 뭐뭐 있어"
- "프리마켓/마감 알림이 안 와", "잡이 안 돈다", "봇이 죽었나"
- launchd / plist / 자동 실행 관련 질문
- 새 정기 잡을 추가하거나 기존 잡 시각을 바꾸려 할 때

## 가장 먼저 알아야 할 것

**cron이 아니라 launchd다.** `crontab -l`은 비어 있다. 사용자가 "크론"이라고
말해도 실제 등록처는 `~/Library/LaunchAgents/*.plist`다. `crontab`만 보고
"등록된 게 없다"고 답하면 오답이다.

레포 원본: `automation/launchd/*.plist`
스케줄·잡별 상세 설명: **[`automation/SCHEDULES.md`](../../automation/SCHEDULES.md)**

## 스케줄 요약

| 잡 | 시각 | cron 환산 |
|---|---|---|
| `com.jun.claude.premarket` | 월~금 08:01 | `1 8 * * 1-5` |
| `com.jun.claude.closing` | 월~금 15:40 | `40 15 * * 1-5` |
| `com.jun.claude.monitor` | 5분마다 | `*/5 * * * *` |
| `com.jun.claude.marketnote-kr` | 월~금 16:00 | `0 16 * * 1-5` |
| `com.jun.claude.marketnote-us` | 화~토 07:00 | `0 7 * * 2-6` |
| `com.jun.kospi200-daily` | 월~금 16:00 | `0 16 * * 1-5` |
| `com.jun.krx-flow-collect` | 매일 18:00 | `0 18 * * *` |
| `com.jun.us-futures-check` | 매일 06:00, 08:00 | `0 6,8 * * *` |
| `com.jun.claude.discordbot` | 상시 (KeepAlive) | — |
| `com.jun.claude.keepalive` | 상시 (caffeinate) | — |

launchd `Weekday`는 **1=월 … 5=금, 6=토, 0/7=일**. cron(`0=일`)과 기준이 다르다.

---

## 진단 절차

잡이 안 돈다는 신고를 받으면 **이 순서대로** 확인한다. 2번을 건너뛰면 대부분 오진한다.

### 1. 등록 상태

```bash
launchctl list | grep com.jun
```

2번째 열이 마지막 종료 코드다. 목록에 **안 보이면 미등록이거나 disabled**인데,
둘은 조치가 다르므로 2번으로 넘어간다.

### 2. disabled 플래그 ← 핵심

```bash
launchctl print-disabled gui/$UID | grep com.jun
```

`launchctl disable`로 끈 잡은 **재부팅해도 그대로 꺼져 있고, plist를 다시
`bootstrap` 해도 올라오지 않는다.** `launchctl list`에 안 보여서 "등록이 풀렸나"로
오해하기 쉬운 게 이 상태다. 여기서 `=> disabled`가 나오면 `enable`이 먼저다.

### 3. 마지막 실행 시각

로그 파일 mtime이 가장 정확한 단서다. 스케줄 시각과 안 맞으면 그 잡이 죽은 것이다.

```bash
ls -lt ~/claude-agents/logs/ | head
ls -lt ~/chikitaka/dart-insight/logs/
```

### 4. 알림만 안 오는 경우

스케줄 잡은 정상인데 디스코드에 아무것도 안 오면 `discordbot`이 죽은 것이다.
이 봇이 모든 알림의 발신 경로라서, 꺼져 있으면 잡이 다 성공해도 조용하다.

```bash
launchctl list | grep discordbot
```

### 상태 일괄 점검 스니펫

```bash
DIS=$(launchctl print-disabled gui/$UID 2>/dev/null)
LOADED=$(launchctl list 2>/dev/null)
for f in ~/Library/LaunchAgents/com.jun.*.plist; do
  L=$(basename "$f" .plist)
  echo "$LOADED" | awk '{print $3}' | grep -qx "$L" && ld="YES" || ld="no"
  echo "$DIS" | grep -q "\"$L\" => disabled" && d="DISABLED" || d="-"
  printf "%-34s %-6s %s\n" "$L" "$ld" "$d"
done
```

---

## 잡 되살리기

`enable` → `bootstrap` 순서가 중요하다. 반대로 하면 조용히 실패한다.

```bash
launchctl enable    gui/$UID/com.jun.claude.closing
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.jun.claude.closing.plist
```

여러 개를 한 번에:

```bash
for L in claude.premarket claude.closing claude.monitor claude.discordbot \
         claude.marketnote-kr claude.marketnote-us claude.keepalive \
         krx-flow-collect us-futures-check; do
  launchctl enable    gui/$UID/com.jun.$L
  launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.jun.$L.plist
done
```

내리기 / 즉시 1회 실행(테스트):

```bash
launchctl bootout   gui/$UID/com.jun.claude.closing
launchctl kickstart -p gui/$UID/com.jun.claude.closing
```

---

## 새 잡 추가 / 시각 변경

1. `automation/launchd/`에 plist를 만든다 (기존 파일 복사해서 수정)
2. **`plutil -lint` 통과 확인** — 문법 오류가 있으면 launchd가 조용히 무시한다
3. `automation/SCHEDULES.md`의 스케줄 표·타임라인·잡별 상세에 추가한다
4. `~/Library/LaunchAgents/`로 복사 후 `enable` → `bootstrap`
5. `launchctl kickstart -p`로 1회 실행해 로그를 확인한다

```bash
plutil -lint automation/launchd/*.plist
```

시각만 바꿀 때도 plist 수정 후 `bootout` → `bootstrap`으로 다시 올려야 반영된다.

---

## 시크릿 규칙

**plist에 API 키를 넣지 않는다.** 과거 premarket·closing·monitor plist에
`EnvironmentVariables`로 `KIS_PAPER_KEY` / `KIS_PAPER_SECRET`이 평문으로 박혀
있었으나 레포 편입 시 제거했다.

제거해도 되는 이유는 `premarket_send.py` · `closing_send.py` · `price_monitor.py`
세 스크립트 모두 시작 시 `_load_env()`로 `~/claude-agents/secrets.env` →
`~/claude-agents/config.sh` 순서로 환경변수를 직접 읽기 때문이다. plist의 env
블록은 중복이었다.

키 교체는 `secrets.env` 한 곳만 고친다. plist에 되돌려 넣지 말 것.

---

## 주의사항

- **launchd는 `.zshrc`를 읽지 않는다.** 예외는 `/bin/zsh -ic`를 쓰는
  `kospi200-daily` 하나뿐이고, 그 대가로 `.zshrc` 안의 미설치 명령 경고
  (`command not found: rbenv` 등)가 로그에 섞인다. 동작에는 영향 없으니
  그것 때문에 잡이 죽었다고 오진하지 말 것.
- 나머지 잡은 필요한 환경변수를 plist나 `secrets.env`로 직접 줘야 한다.
- `monitor`는 5분마다 깨어나지만 **평일 09:00~15:30 KST 밖이면 스크립트가 즉시
  종료**한다. 장외 시간에 로그가 비어 있는 건 정상이다.
- `kospi200-daily`도 주말이면 자체 판정으로 "주말 — 실행 생략"을 남기고 끝난다.
- plist 경로는 전부 `/Users/jun` 하드코딩이다. 다른 환경에 옮기면 먼저 고쳐야 한다.
- `marketnote-*`는 타임아웃 5400초짜리 긴 잡이다(TTS + whisper + Remotion 렌더).
  실행 중으로 보인다고 멈춘 걸로 판단하지 말 것.
