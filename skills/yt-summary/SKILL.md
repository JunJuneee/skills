---
name: yt-summary
description: YouTube 링크 하나를 자막 기반으로 요약해 ~/notes/youtube에 마크다운 노트로 저장한다. 질문형 도입 + 1./1.1./1. **소주제** 계층 양식으로 쓴다. "/yt-summary <url>", "이 유튜브 요약해줘", "영상 정리해줘", youtube.com·youtu.be 링크와 함께 요약·정리를 요청할 때 사용.
---

# YouTube Summary

`SKILL.md`가 있는 디렉터리를 `SKILL_DIR`로 쓴다. 영상 파일은 받지 않고 자막만 받는다.

## 1. 자막 가져오기

```bash
SKILL_DIR='<이 SKILL.md가 있는 디렉터리>'
python3 "$SKILL_DIR/scripts/fetch_transcript.py" '<URL>'
```

URL은 따옴표로 감싼다(`&list=` 같은 쿼리가 셸에서 깨진다). 플레이리스트 링크여도 그 영상 하나만 처리한다.

stdout JSON에서 쓰는 값:

| 키 | 용도 |
|---|---|
| `transcript_path` | 정리된 자막(`[mm:ss] ...` 1분 단락). Read로 전부 읽는다 |
| `transcript_chars` | 분량 판단 |
| `note_path` | 저장할 경로(`~/notes/youtube/<업로드일>_<제목>.md`) |
| `existing_note` | 같은 `video_id` 노트가 이미 있으면 그 경로 |
| `caption_kind` / `caption_track` | `manual`(사람 자막) 또는 `auto`(자동자막) / 언어 |
| 나머지 | frontmatter에 그대로 옮긴다 |

`existing_note`가 있으면 요약하지 말고 그 경로를 알려준 뒤 다시 만들지 묻는다. 사용자가 "다시"라고 했으면 그 파일을 덮어쓴다.

### 실패 처리

| exit | 의미 | 대응 |
|---|---|---|
| 2 | URL이 아님 / yt-dlp 없음 | 메시지 그대로 전달 |
| 3 | yt-dlp 실패 | `hint`가 봇 차단이면 `--cookies-from-browser chrome`을 붙여 한 번 재시도. 비공개·삭제 영상이면 중단 |
| 4 | 자막 없음 | 중단하고 알린다. 받아쓰기(`mlx-whisper`) 설치는 사용자가 원할 때만 안내한다 — 스크립트에는 없다 |

yt-dlp의 "No supported JavaScript runtime" 경고는 자막 수집에 영향이 없었다(2026-10 실측). 추출이 깨지기 시작하면 `brew install deno`를 권한다.

## 2. 요약 쓰기

[references/format.md](references/format.md)를 읽고 그 양식을 정확히 따른다. 요약 언어는 한국어다(영어 영상도 한국어로 요약).

- 자막 전체를 읽은 뒤 쓴다. 앞부분만 읽고 쓰지 않는다.
- `transcript_chars`가 120,000자를 넘으면 자막을 30분 단위로 나눠 구간별 메모를 만든 뒤 하나의 양식으로 합친다.
- **자동자막 오인식 교정**: 고유명사(사람·회사·종목·제품명)가 소리 나는 대로 깨져 있으면 문맥으로 바로잡는다. 확신이 없으면 원문 표기를 유지한다. 고친 것은 꼬리 줄에 `원문→교정`으로 남긴다.
- 화자의 주장과 사실을 섞지 않는다. 화자의 전망·의견은 "~라고 본다", "~할 것이다"처럼 화자 몫으로 쓴다.
- 영상에 없는 수치·배경 설명을 더하지 않는다.

## 3. 저장

1. `note_path`의 디렉터리가 없으면 만든다.
2. frontmatter + 본문을 Write로 `note_path`에 저장한다.
3. 사용자에게 아래만 알린다:
   - 저장 경로
   - 도입 문단(그대로)과 대주제 제목 목록
   - 자동자막이면 그 사실과 교정한 고유명사 수

본문 전체를 채팅에 붙이지 않는다. 사용자가 "보여줘"라고 하면 그때 붙인다.

## 참고

- 정리 스크립트는 `>>`(화자 전환), HTML 엔티티, 자동자막의 롤링 중복 줄을 지운다. 40분 영상 기준 VTT 338KB → 44KB.
- 자동자막에서 `<lang>-orig`가 원음 인식본이고 `<lang>`은 번역일 수 있어 `-orig`를 먼저 고른다.
- 자막 다운로드는 간헐적으로 404를 내서 한 번 자동 재시도한다.
