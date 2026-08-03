---
name: "lilys-daily"
description: "Lilys 로그인 세션에서 Bearer 토큰을 안전하게 갱신해 등록 채널의 최근 영상을 자동 요약하는 일일 작업. 사용자가 '릴리스 실행', 'lilys 돌려줘', '/lilys-daily'라고 요청할 때 사용."
---

# Lilys Daily

## 경로

- 작업 디렉토리: `/Users/jun/Desktop/skills/skills/lilys-daily/`
- 실행 스크립트: `/Users/jun/Desktop/skills/skills/lilys-daily/lilys_daliy.py`
- 보조 스크립트: `lilys_channel_all.py`, `lilys_channel_all_seq.py`

스크립트 파일명 `lilys_daliy.py`의 오타는 실제 파일명이므로 그대로 사용한다.

## 보안 원칙

- 사용자에게 Bearer 토큰을 채팅으로 요청하지 않는다.
- 토큰 원문, 일부 문자열, JWT payload의 개인 식별 정보는 채팅과 도구 로그에 출력하지 않는다.
- 토큰을 `SKILL.md`, `token.txt`, 셸 명령문, 소스 코드에 하드코딩하지 않는다.
- Lilys 로그인 세션에서 실행 시점마다 토큰을 가져온다.
- 토큰은 권한 `0600`의 임시 파일에 잠깐 저장하고, 스크립트 종료 시 성공 여부와 관계없이 삭제한다.

## 워크플로우

### 1. Lilys 로그인 상태 확인

1. 현재 열린 탭 중 `lilys.ai` 탭이 있으면 연결한다.
2. 없으면 `https://lilys.ai/ko/signup`을 연다.
3. 스냅샷에서 계정 메뉴가 보이는지 확인한다.
4. 로그아웃 상태면 Google 로그인을 사용한다. 계정이 여러 개면 사용자에게 선택을 요청한다.

### 2. 토큰 유효성 확인 및 임시 파일 생성

Lilys는 로그인 후 `localStorage`의 `access_token`을 Bearer 토큰으로 사용한다. 값 자체를 출력하지 말고 존재 여부와 JWT 만료 시간만 검사한다.

- `access_token`이 없으면 로그인부터 다시 진행한다.
- JWT `exp`가 현재 시각보다 60초 이내이면 페이지를 새로고침한 뒤 다시 읽는다.
- 새로고침 후에도 유효한 토큰이 없으면 재로그인한다.
- `refresh_token` 값은 읽거나 출력하지 않는다.

REPL에서 토큰을 지역 변수로만 다루고 임시 파일 경로만 출력한다.

```js
const tokenFile = await (async () => {
  const raw = await page.evaluate(() => localStorage.getItem('access_token'));
  if (!raw) throw new Error('Lilys access_token이 없습니다. 다시 로그인하세요.');

  const parts = raw.split('.');
  if (parts.length === 3) {
    const payload = JSON.parse(
      Buffer.from(parts[1].replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8')
    );
    if (!payload.exp || payload.exp * 1000 <= Date.now() + 60_000) {
      throw new Error('Lilys access_token이 만료되었거나 곧 만료됩니다. 페이지를 새로고침한 뒤 다시 확인하세요.');
    }
  }

  const tempPath = `/tmp/lilys-daily-token-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const bearer = raw.startsWith('Bearer ') ? raw : `Bearer ${raw}`;
  await fs.writeFile(tempPath, bearer, { mode: 0o600 });
  return tempPath;
})();
console.log({ tokenFile });
```

`raw`, `bearer`, 토큰 길이, 토큰 앞부분을 `console.log`로 출력하지 않는다.

### 3. 일일 요약 스크립트 실행

위 단계에서 출력된 임시 파일 경로만 아래 `TOKEN_FILE`에 넣는다. 토큰 문자열을 셸 명령문에 직접 넣지 않는다.

```bash
set -o pipefail
TOKEN_FILE='<REPL에서 생성한 임시 파일 경로>'
cleanup() { rm -f "$TOKEN_FILE"; }
trap cleanup EXIT INT TERM

cd /Users/jun/Desktop/skills/skills/lilys-daily
BEARER_TOKEN="$(cat "$TOKEN_FILE")" python3 lilys_daliy.py
```

- 스크립트 실행 중에도 토큰이나 요청 헤더를 출력하지 않는다.
- 백그라운드 실행 시에도 종료 후 임시 파일이 삭제되도록 같은 `trap`을 유지한다.
- 실행 후 임시 파일이 삭제되었는지 확인한다.

### 4. 401 복구

Lilys API가 401을 반환하면 다음을 한 번만 수행한다.

1. Lilys 페이지를 새로고침한다.
2. 로그인 상태를 다시 확인한다.
3. 새 `access_token`으로 새 임시 파일을 만든다.
4. 실패한 실행을 한 번만 재시도한다.

재시도도 401이면 중단하고 사용자에게 Lilys 재로그인이 필요하다고 알린다. 이전 토큰을 `token.txt`로 대체하거나 보존하지 않는다.

### 5. 결과 보고

로그에서 다음만 집계해 한국어로 보고한다.

- 채널별 신규 요청 성공 건수와 실패 건수
- 스킵 사유별 카운트: 3시간 이상, 5분 미만, 이미 등록됨
- 실패 상태코드와 사유 첫 줄
- 토큰 갱신 여부와 임시 파일 삭제 여부

로그에 `Bearer ` 뒤 문자열이나 JWT 형태가 포함되면 반드시 전체를 `[REDACTED]`로 가린다. 토큰 일부도 보고하지 않는다.

## 스크립트 동작 기준

- 등록 채널 목록과 `collection_id`는 스크립트 내부 설정을 따른다.
- 최근 5일 이내 업로드 영상만 대상으로 한다.
- 3시간 이상 영상과 5분 이하 영상은 건너뛴다.
- 대상 컬렉션에 이미 등록된 `video_id`는 건너뛴다.
- 인증 우선순위는 환경변수 `BEARER_TOKEN`을 사용한다. `token.txt`는 새 인증 저장소로 사용하지 않는다.
