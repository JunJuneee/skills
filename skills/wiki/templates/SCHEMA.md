# 위키 규약 (SCHEMA)

사람과 에이전트가 같은 페이지를 읽는다. frontmatter의 `summary`는 에이전트용 세 줄, 본문은 사람용이다. 페이지는 absorb만 쓴다. 세션 에이전트는 위키를 직접 고치지 않는다.

## 폴더

```
SCHEMA.md  domains.json  settings.json  index.md  log.md  now.md  about-me.md
work/      projects/ decisions/ people/ topics/ notes/ prefs/
personal/  projects/ decisions/ topics/ notes/ prefs/
inbox/work/  inbox/personal/     (git 제외, /wiki note가 씀)
.state/                          (git 제외, 사본·캐시·실행 기록)
.absorb-wt/                      (git 제외, absorb 전용 worktree)
.bin/<version>/                  (git 제외, 자동 실행용 고정 스크립트)
```

- `index.md`, `log.md`, 루트 `now.md`·`about-me.md`, `.state/*-cache.json`, 전역 선호 규칙 파일은 absorb의 verify(Python)가 만든다. LLM 단계는 묶음 도메인 폴더(`<domain>/**`)만 쓴다.
- 루트 `now.md`·`about-me.md`의 초안은 LLM이 `<domain>/_drafts/now.md`, `<domain>/_drafts/about-me.md` 조각으로 쓰고 verify가 조립한다. `_drafts/`는 커밋 전에 지운다.
- 다른 도메인 폴더는 읽지도 쓰지도 않는다.

## frontmatter

지원하는 문법은 아래뿐이다. 이 밖의 YAML(중첩 맵, `{}`, `>`, 앵커, 탭 들여쓰기)은 파서가 거부한다.

```yaml
title: 예시 프로젝트
aliases:
  - 예시 별칭
  - Example
repos: [<owner>/<repo>]
summary: |
  첫 줄
  둘째 줄
```

- 스칼라: 따옴표 없는 값, `"큰따옴표"`, `'작은따옴표'`(안의 `'`는 `''`). 모든 값은 문자열이다(숫자·날짜·참거짓으로 바꾸지 않음).
- 리스트: `[a, b]` 또는 블록 리스트(`- a`). Obsidian Properties가 블록 형태로 바꿔 저장해도 같은 값이다. 빈 리스트는 `[]`.
- 블록 문자열: `key: |`(끝 줄바꿈 하나) 또는 `key: |-`.

| 필드 | 값 | 대상 |
|---|---|---|
| `title` | 페이지 제목 | 모두(필수) |
| `type` | `project` `decision` `person` `topic` `pref` `note` | 모두(필수) |
| `domain` | `work` 또는 `personal`, 폴더와 같아야 함 | 모두(필수) |
| `aliases` | 같은 대상의 다른 이름 리스트 | 모두 |
| `summary` | 에이전트가 읽는 세 줄 | 모두 |
| `repos` | `<owner>/<repo>` 리스트 | project |
| `status` | `active` `paused` `done` | project |
| `scope` | `global` `domain` `repo` | pref |
| `decided` | `YYYY-MM-DD` | decision |
| `supersedes` | 대체한 결정 페이지 리스트 | decision |
| `as_of` | `YYYY-MM-DD`, handoff에서 온 상태 | project |
| `updated` | `YYYY-MM-DD` | 모두 |

원본의 상태(consumed 등)는 페이지가 아니라 `.state/sources.json`에 둔다.

## 본문 규칙

- 섹션 출처: 각 섹션 끝에 `<!-- src: <원본 id> @<YYYY-MM-DD> -->`를 둔다. 섹션의 모든 src는 페이지 도메인과 같아야 한다. 지워진 원본을 가리키는 src가 남으면 실행이 실패한다. 예외로 `## 현재 상태`는 항목(목록 항목이나 문단)마다 그 항목의 src 줄을 바로 아래에 둔다(항목별 만료 때문).
- `## 현재 상태`: absorb가 쓰는 생성 영역. 사람이 고치면 그 편집을 `manual:<page>` 원본으로 받아 다음 absorb에 반영한다(덮어쓰지 않음).
- `## 내 메모`: 제목부터 파일 끝까지 사람 전용. absorb와 링크 변환이 한 바이트라도 바꾸면 실패한다. absorb가 새로 만드는 페이지는 빈 `## 내 메모` 제목으로 끝나야 한다(그 아래 글이 있으면 실패). 루트 `now.md`·`about-me.md`의 `## 내 메모`는 `### work`, `### personal` 하위 섹션으로 나눈다. 묶음에는 그 도메인 하위 섹션만 들어가고, 하위 섹션 밖의 글은 어느 묶음에도 들어가지 않는다.
- 결정은 대체만 한다(`supersedes:`, `decided:`). 같은 실행에서 그 프로젝트의 `## 현재 상태`도 갱신한다.
- handoff에서 온 그날의 상태는 `as_of`를 달고 14일 뒤 `## 현재 상태`에서 빠진다. Python이 src가 모두 14일 지난 handoff인 항목을 지우고, 섹션 전체가 그렇다면 섹션을 비운다. src가 없는 항목은 날짜를 알 수 없어 남는다. 다른 원본으로 상태를 새로 쓰면 `as_of`를 지운다.
- 21일 동안 새 원본이 없는 프로젝트는 `status: paused`.

## 링크

- 같은 도메인 안의 이미 있는 페이지에만 건다. 형식은 `[[<domain>/<folder>/<slug>|표시 이름]]`.
- 다른 도메인으로 가는 링크는 verify가 거부한다. 도메인 접두어 없는 `[[이름]]`도 다른 도메인에 같은 파일 이름이 있으면 거부한다.
- 링크 변환은 `## 내 메모`, 코드 블록, frontmatter를 건너뛴다.
- 같은 대상의 여러 이름은 `aliases`로 묶는다. 원본 3개 이상에서 나온 이름만 새 페이지가 된다.

## 페이지 type별 섹션 순서

- project: `## 이번 주 무엇을 왜` → `## 현재 상태` → `## 실측값과 함정`(notes/로 접음) → `## 내 메모`
- decision: `## 결정` → `## 이유` → `## 대안` → `## 내 메모`
- pref: `## 선호` → `## Why` → `## How to apply` → `## 내 메모`
- topic·person·note: `## 요약` → `## 내용` → `## 내 메모`

## memory를 페이지로 옮기는 규칙

- feedback → 그 도메인의 `prefs/`. Why와 How to apply는 그대로 옮긴다. 두 도메인 모두에 있거나 personal에만 있으면서 work_terms에 걸리지 않으면 `scope: global` 후보.
- project → 프로젝트 아래 `notes/`. 프로젝트 페이지 맨 위는 "이번 주 무엇을 왜"(프롬프트가 출처).
- reference → `notes/`. user → `prefs/`.
