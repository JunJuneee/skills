# 훅 캐시 형식 (`.state/context-cache.json`, `.state/alias-cache.json`)

훅(`scripts/session_context.py`, `scripts/prompt_nudge.py`)이 읽는 파일은 이 두 개뿐이다(계약 5). 위키 본문과 `domains.json`은 읽지 않는다. 두 파일은 absorb의 verify가 만들고, 병합이 성공한 뒤 main의 `.state/`에 쓴다. `.absorb-wt` 안에는 쓰지 않는다.

## 공통 규칙

- UTF-8 JSON 객체 하나. 크기는 2 MB 이하. 넘으면 훅은 아무것도 출력하지 않는다.
- `version`은 정수 `1`. 다르면 훅은 아무것도 출력하지 않는다. 형식을 바꾸면 올리고 훅도 같이 고친다.
- `domains`의 키는 `work`, `personal`만. 키는 도메인 이름이고, 그 아래 값에는 그 도메인 내용만 둔다.
- `page`는 위키 루트 기준 상대 경로이고 `/`로 구분한다. 반드시 `<domain>/`로 시작하고 `.md`로 끝나야 한다. `..`, 빈 조각, `\`가 있으면 훅은 그 항목을 버린다. 그래서 다른 도메인 경로는 캐시가 잘못돼도 새지 않는다.
- 문자열 필드는 사람이 읽는 평문이다. 훅은 제어 문자를 지우고 NFC로 맞춘 뒤 섹션별 상한에서 자른다.
- 쓰기는 임시 파일 후 `os.replace`(`common.atomic_write_text`), 권한은 0600. 훅이 반쯤 쓴 파일을 읽지 않게 한다.
- verify는 쓰기 전에 두 파일 전체에 계약 4 비밀값 검사를 한다. personal 블록에는 work_terms 검사도 한다.

## context-cache.json

```json
{
  "version": 1,
  "generated_at": "2026-01-01T02:15:00+09:00",
  "as_of": "2026-01-01 02:15",
  "run_id": "2026-01-01T0215",
  "owners": {"<work-github-org>": "work", "<your-github-user>": "personal"},
  "domains": {
    "personal": {
      "projects": [
        {
          "title": "<project-name>",
          "page": "personal/projects/<project-name>.md",
          "repos": ["<owner>/<repo>"],
          "status": "active",
          "summary": "<세 줄 summary, 줄바꿈 유지>",
          "this_week": "<## 이번 주 무엇을 왜 요약 한 줄>"
        }
      ],
      "prefs": [
        {
          "title": "<preference-title>",
          "page": "personal/prefs/<preference-title>.md",
          "scope": "domain",
          "repos": [],
          "text": "<에이전트가 따를 규칙 한 줄>"
        }
      ]
    },
    "work": {"projects": [], "prefs": []}
  },
  "pending": {
    "updated_at": "2026-01-01T12:00:00+09:00",
    "unresolved": 0,
    "domains": {"personal": {"count": 0, "titles": []}, "work": {"count": 0, "titles": []}}
  }
}
```

| 필드 | 필수 | 뜻 |
|---|---|---|
| `owners` | 예 | `domains.json`의 `owners` 사본. 훅은 이것으로 cwd remote의 도메인을 정한다. 없거나 비어 있으면 훅은 아무것도 출력하지 않는다. 캐시 내용과 같은 시점의 owners라서, 사용자가 `domains.json`을 고치면 다음 absorb부터 반영된다. |
| `as_of` | 예 | 마지막 absorb 시각. 헤더 `wiki as of …`에 그대로 나온다. 없으면 `generated_at`. |
| `projects` | 예(빈 리스트 가능) | 그 도메인의 project 페이지. 활동순(원본 날짜 기준, `paused`는 뒤)으로 정렬해 둔다. `repos`가 cwd remote의 `owner/repo`(대소문자 무시, 앞의 호스트 조각과 `.git`은 무시)와 겹치는 항목은 요약과 이번 주를, 나머지는 제목만 보인다. |
| `projects[].summary` | 아니오 | frontmatter `summary`. handoff에서 온 상태는 `as_of` 14일이 지나고 `## 현재 상태`에 그보다 새 src가 없으면 verify가 빼고 쓴다(D10). 페이지의 `## 현재 상태`도 src가 모두 14일 지난 handoff이면 병합 전에 비운다. |
| `prefs` | 예(빈 리스트 가능) | 그 도메인의 pref 페이지 중 `scope`가 `domain` 또는 `repo`인 것. `repo`는 `repos`가 cwd와 겹칠 때만 보인다. `global`은 넣지 않는다(전역 선호 규칙 파일로만 간다). |
| `pending` | 아니오 | 그 absorb에서 반영되지 못한 원본(계약 2의 반영 대기 N). `domains.<d>.count`·`titles`는 병합되지 않은 묶음(실패, 보류, 병합 실패)의 원본 수와 제목, `unresolved`는 그 실행에서 상태나 해시가 바뀐 판정 불가 원본의 건수만(30일 창 안의 누적이 아님). 없으면 그 줄을 생략한다. |

`pending`은 absorb가 끝날 때만 쓴다. 실행 사이(30분 깨우기 포함)에는 갱신하지 않는다. 그래서 다음 absorb 전까지 새로 생긴 원본은 세지 않는다. 지금 대기 수가 필요하면 `wiki status`가 prepare의 차이 계산만 돌려 숫자로 보여 준다.

### 출력 모양과 상한

```
wiki as of <as_of> · domain: <domain> (위키는 읽기만 한다. 쓰기는 /wiki absorb)
<project-name> — ~/wiki/<domain>/projects/<project-name>.md
<summary 세 줄>
이번 주: <this_week>
선호:
- <repo 선호>
- <domain 선호>
같은 도메인 다른 프로젝트: <a>, <b>, …
지난 absorb에서 반영되지 못한 원본 <N>건 (판정 안 된 것 <n>건): <제목>, …
```

| 섹션 | SessionStart | SubagentStart |
|---|---|---|
| 헤더 | 200 | 150 |
| 이 레포 프로젝트 | 2,000 | 700 |
| 선호 | 2,400 | 800 |
| 다른 프로젝트 제목 | 600 | 150 |
| 반영되지 못한 원본 | 600 | 150 |
| 합계 | 6,000 | 2,000 |

## alias-cache.json

```json
{
  "version": 1,
  "generated_at": "2026-01-01T02:15:00+09:00",
  "domains": {
    "personal": [
      {
        "page": "personal/projects/<project-name>.md",
        "title": "<project-name>",
        "aliases": ["<other-name>", "<한글 이름>"]
      }
    ],
    "work": []
  }
}
```

- 항목은 페이지 하나에 하나. 이름은 `title`과 `aliases` 전체다. D9에서 같은 대상으로 합친 이름도 `aliases`에 넣는다.
- 계약 4 비밀값에 걸리는 이름과, personal 블록에서 work_terms(NFKC·대소문자 무시)에 걸리는 이름은 빼고 쓴다. 제목이 걸리면 그 항목 전체를 뺀다. LLM의 `merges`·`mentions` 이름도 같은 검사를 거친 뒤에만 aliases와 `sources.json`에 들어간다.
- 넛지는 세션 도메인의 리스트만 본다. 다른 도메인 이름이 프롬프트에 나와도 아무것도 나오지 않는다.
- 매칭 전에 프롬프트와 이름 둘 다 NFKC 정규화와 casefold를 한다. 정규화 뒤 2자 이하인 이름은 버린다. 한글이 들어간 이름은 부분 문자열(조사가 붙어도 매칭), 라틴 이름은 단어 경계(앞뒤가 라틴 글자·숫자·`_`가 아니어야 함, 한글 조사는 경계로 봄), 그 밖의 문자는 부분 문자열로 찾는다.
- 한 프롬프트에 페이지 최대 3개, 처음 나온 위치 순. 출력은 한 줄에 하나: `관련 위키: ~/wiki/<page> (<title>)`.
- 프롬프트는 앞 20,000자만 본다. 이름은 전체 5,000개까지만 본다.

## 훅이 아무것도 출력하지 않는 경우

- `LLM_WIKI_HOOK=0`, 위키 폴더 없음(셸 가드에서 Python도 안 뜸).
- Claude Code라는 긍정 신호가 없음: 환경변수 `CLAUDECODE=1`이면서 stdin `transcript_path`가 Claude 설정 폴더(`CLAUDE_CONFIG_DIR`, 없으면 `~/.claude`) 안에 있어야 한다. Codex도 플러그인 `hooks.json`을 읽지만 이 조건을 넘지 않는다.
- stdin이 JSON 객체가 아님, `hook_event_name`이 `--event`와 다름, `cwd`가 절대 경로가 아님.
- cwd가 홈 폴더 자체, `/`, Traycer epic 폴더(`.traycer/epics/` 아래). epic 폴더는 v1에서 워크스페이스 레포로 풀지 않는다.
- `git -C <cwd> remote -v`가 실패하거나 1초를 넘김, remote가 없음, 도메인 판정 불가.
- 캐시 없음, JSON 오류, `version` 불일치, `owners` 없음, 해당 도메인 블록 없음.
