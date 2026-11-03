# 환경변수와 Doppler 우선 조회

사용자는 앞으로 환경변수·토큰을 **Doppler project `jay`, config `shared`**에 모은다. 이 워크플로에서 필요한 환경변수는 이 경로를 먼저 확인한다. 기존 로컬 `.env`가 비어 있거나 현재 셸에 변수가 없다는 이유만으로 토큰 미설정이라고 단정하거나 사용자에게 다시 입력을 요청하지 않는다.

## 조회·사용 순서

1. 기존 작업 전용 capability나 승인된 서비스 연결이 있으면 그 제한된 경로를 사용한다. 하위 작업자가 서비스 토큰을 직접 가져와야 한다는 뜻은 아니다. 제이지 보고 capability만 받은 작업자는 그대로 보고 명령을 사용한다.
2. 실행 프로세스에 환경변수 주입이 필요하면 **Doppler `jay/shared`**에서 필요한 키를 먼저 찾는다. 현재 디렉터리의 Doppler 기본 scope가 다른 프로젝트를 가리키더라도 project/config를 명시한다. 같은 키가 로컬 env나 `.env`에도 있으면 Doppler 값을 우선하며 `--preserve-env=true`로 오래된 값을 우선하지 않는다.
3. 키가 없거나 Doppler CLI·인증·접근에 문제가 있으면 원인과 누락 키 이름만 기록한다. 이미 승인된 프로젝트별 별도 config·기존 환경변수·로컬 비밀 저장소로의 대체가 명시돼 있을 때만 그 경로를 사용하고 선택한 출처를 기록한다. 다른 회사·프로젝트 config, 다른 봇, 오래된 `.env`로 조용히 대체하지 않는다.
4. 승인된 대체 경로도 없으면 실제로 필요한 설정만 사용자에게 모아 알린다. 토큰 값을 채팅으로 받거나 환경 전체를 덤프하지 않는다. Slack 전달 장애와 코드 구현·검증 상태는 구분한다.

Doppler 접근 자체는 기존 CLI 로그인 또는 승인된 실행 환경의 인증을 사용한다. Doppler 인증 토큰을 공용 스킬·작업 계약·명령 인자·로그에 복사하지 않는다. 이 스킬은 비밀을 새로 발급·수정하거나 기존 비밀을 자동 이관하라는 지시가 아니다.

## 제이지 Slack 토큰

- `SLACK_BOT_TOKEN`: 제이지 봇 발신·인증용.
- `SLACK_APP_TOKEN`: Socket Mode 연결용. 이벤트 수신기를 실행하는 경우에만 필요하다.

위 두 키의 우선 출처는 모두 `jay/shared`다. 토큰이 존재한다는 사실과 올바른 봇·워크스페이스의 인증 성공은 다르다. 실제 발송 전에 기존 알림 계약의 bot identity·workspace·channel·요청자를 확인한다.

값을 출력하지 않고 키 목록만 확인한다.

```sh
doppler secrets --project jay --config shared --only-names
```

비밀은 파일로 export하지 말고 **필요한 키만 승인된 자식 프로세스의 환경에 주입**한다. 기존 제이지 실행 진입점이 `node src/main.mjs`라면 해당 프로그램 디렉터리에서 다음처럼 주입할 수 있다.

```sh
doppler run --project jay --config shared \
  --only-secrets SLACK_BOT_TOKEN,SLACK_APP_TOKEN \
  --no-fallback -- node src/main.mjs
```

이 예시는 이미 승인된 제이지 프로세스를 실행할 때의 환경 주입 방식이다. 이슈 작업자가 보고 capability 대신 봇 데몬을 새로 켜거나 기존 데몬을 재시작하지 않는다. 단순 발신처럼 하나의 키만 필요한 프로세스에는 그 키만 주입하며 `jay/shared` 전체를 하위 에이전트에 전달하지 않는다.

존재·비어 있지 않음 같은 boolean만으로 주입을 검사할 수 있다. `env`·`printenv`, 값이 나오는 `doppler secrets` 조회, secret download, shell tracing, 원문 HTTP 인증 로그로 값을 노출하지 않는다. `.env`·임시 JSON·TC 자료·PR·Slack에 비밀을 복사하지 않는다. `--no-fallback`은 로컬 fallback 캐시 읽기·쓰기를 사용하지 않는 예시이며 별도 승인된 캐시 정책이 있으면 그 계약을 따른다.

## 기록할 것

작업 기록에는 선택한 project/config, 필요한 **키 이름**, 사용한 제한된 주입·capability 경로, 존재/주입/인증의 성공 여부와 시각만 남긴다. 값·토큰 일부·환경 전체는 남기지 않는다. 스킬의 조회 우선순위 변경과 실제 운영 프로세스의 실행 환경 변경·재시작 여부를 구분해 보고한다.
