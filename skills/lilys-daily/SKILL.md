---
name: "lilys-daily"
description: "Aside MCP의 Lilys 로그인 세션에서 최신 Bearer 토큰을 안전하게 가져와 등록 채널의 최근 영상을 자동 요약한다. '/lilys-daily', '릴리스 실행', 'lilys 돌려줘' 요청에 사용."
---

# Lilys Daily

## 기본 원칙

- 이 `SKILL.md`가 있는 디렉토리를 `SKILL_DIR`로 사용한다.
- 실행 스크립트는 `lilys_daliy.py`이다. 파일명의 `daliy` 오타는 실제 이름이므로 유지한다.
- 사용자에게 Bearer 토큰을 채팅으로 요청하지 않는다.
- 토큰 원문이나 일부 문자열을 채팅, 도구 출력, 명령문, 소스 코드, `token.txt`에 기록하지 않는다.
- Lilys 로그인 세션에서 실행할 때마다 최신 `access_token`을 가져온다.

## 실행 절차

### 1. Aside MCP로 Lilys 로그인 상태 확인

1. Aside MCP에서 열린 `lilys.ai` 탭을 찾고 연결한다.
2. 탭이 없으면 Aside 브라우저에서 `https://lilys.ai/ko/signup`을 연다.
3. 스냅샷에서 로그인 계정 메뉴가 보이는지 확인한다.
4. 로그아웃 상태면 Google 로그인을 진행한다. 계정이 여러 개면 사용자에게 선택을 요청한다.

### 2. 최신 access token을 안전한 임시 파일로 전달

Aside MCP REPL의 파일 생성 옵션은 권한 `0600`을 보장하지 않으므로, 빈 파일을 셸에서 먼저 안전하게 만든 뒤 REPL이 토큰을 기록한다.

#### 2-1. 임시 파일 경로 생성

Aside MCP REPL에서 현재 세션 전용 임시 경로만 만든다. 이 단계에서는 토큰을 읽지 않는다.

```js
const tokenFile = await (async () => {
  const session = aside.sessions.current();
  if (!session) throw new Error('현재 Aside 세션 정보를 찾을 수 없습니다.');
  const sessionDate = new Date(session.createdAt).toISOString().slice(0, 10);
  const tempDir = path.join(pwd, 'sessions', `${sessionDate}_${session.id}`, 'tmp');
  await fs.mkdir(tempDir, { recursive: true });
  return path.join(
    tempDir,
    `lilys-daily-token-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
})();
console.log({ tokenFile });
```

#### 2-2. 권한 0600의 빈 파일 생성

```bash
TOKEN_FILE='<Aside MCP REPL이 반환한 임시 파일 경로>'
umask 077
: > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
test "$(stat -f '%Lp' "$TOKEN_FILE")" = "600"
```

#### 2-3. 최신 토큰 기록

Aside MCP REPL에서 아래 작업을 한 번에 수행한다. `tokenFile`에는 2-2에서 만든 경로를 넣는다. 토큰 값은 REPL 밖으로 반환하지 않는다.

```js
const tokenWriteResult = await (async () => {
  const tokenFile = '<권한 0600으로 미리 만든 임시 파일 경로>';
  const readToken = async () => page.evaluate(() => localStorage.getItem('access_token'));
  const getExpiry = (jwt) => {
    try {
      const part = jwt.split('.')[1];
      if (!part) return 0;
      const normalized = part.replace(/-/g, '+').replace(/_/g, '/');
      return JSON.parse(Buffer.from(normalized, 'base64').toString('utf8')).exp || 0;
    } catch {
      return 0;
    }
  };

  let raw = await readToken();
  if (!raw) throw new Error('Lilys access_token이 없습니다. 다시 로그인하세요.');
  if (getExpiry(raw) * 1000 <= Date.now() + 60_000) {
    await page.reload();
    const refreshed = await snapshot(page, { interactive: true });
    console.log(refreshed.diff);
    raw = await readToken();
  }
  if (!raw || getExpiry(raw) * 1000 <= Date.now() + 60_000) {
    throw new Error('Lilys 토큰 갱신이 필요합니다. 다시 로그인하세요.');
  }

  const bearer = raw.startsWith('Bearer ') ? raw : `Bearer ${raw}`;
  await fs.writeFile(tokenFile, bearer);
  raw = '';
  return { tokenFile, written: true };
})();
console.log(tokenWriteResult);
```

다음 값은 출력하지 않는다.

- `access_token` 또는 `refresh_token`
- 토큰 길이, 앞부분, 뒷부분
- JWT의 사용자 식별 정보

### 3. Python 실행 및 임시 파일 삭제

REPL이 반환한 임시 파일 경로만 `TOKEN_FILE`에 넣는다. 토큰 문자열을 셸 명령문에 직접 넣지 않는다.

```bash
set -o pipefail
SKILL_DIR='<이 SKILL.md가 있는 디렉토리>'
TOKEN_FILE='<Aside MCP REPL이 반환한 임시 파일 경로>'
cleanup() { rm -f "$TOKEN_FILE"; }
trap cleanup EXIT INT TERM

cd "$SKILL_DIR"
BEARER_TOKEN="$(cat "$TOKEN_FILE")" python3 lilys_daliy.py
```

실행 종료 후 `TOKEN_FILE`이 삭제되었는지 확인한다.

### 4. 401 복구

Python이 종료 코드 `2`를 반환하면 Lilys 인증 실패로 처리한다.

1. Lilys 페이지를 새로고침한다.
2. 로그인 상태를 다시 확인한다.
3. 새 토큰으로 새 임시 파일을 만든다.
4. Python 실행을 한 번만 재시도한다.

재시도도 종료 코드 `2`이면 중단하고 사용자에게 Lilys 재로그인이 필요하다고 알린다.

### 5. 결과 보고

다음 정보만 한국어로 요약한다.

- 채널별 신규 요청 성공 및 실패 건수
- 스킵 사유별 건수: 3시간 이상, 5분 이하, 이미 등록됨
- 실패 상태코드와 사유 첫 줄
- 토큰 갱신 여부
- 임시 파일 삭제 여부

로그에 `Bearer ` 문자열이나 JWT 형태가 포함되면 전체를 `[REDACTED]`로 바꾸고 보고한다.

## 스크립트 동작 기준

- 등록 채널과 `collection_id`는 `lilys_daliy.py` 설정을 따른다.
- 3시간 이상 및 5분 이하 영상은 건너뛴다.
- 대상 컬렉션에 이미 등록된 `video_id`는 건너뛴다.
- 인증은 `BEARER_TOKEN` 환경변수만 사용한다.
- `token.txt`와 `token.txt.bak`은 이전 방식의 잔여 파일이며 인증에 사용하지 않는다.
