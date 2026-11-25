---
name: discord-send
description: Saladlab Discord 서버에 글을 보낼 때는 Composio DISCORDBOT_*이 아니라 반드시 오박사 봇(~/automations/discord-delegate/send.mjs)으로 보낸다. "디스코드에 보내줘", "디스코드로 말씀드려", "디스코드 알려줘", "채널에 공유해줘", "스레드에 답해줘" 등 Discord로 글을 올리거나 답하는 모든 요청에 사용한다. composio-first 스킬보다 우선한다. 글 읽기·검색은 해당하지 않는다.
---

# Discord는 오박사로 보낸다

Discord 글 전송은 항상 봇 "오박사" 계정으로 한다. 2026-11-25에 Composio `DISCORDBOT_CREATE_MESSAGE`로 `⚫-알파카`에 글을 보냈다가 "오박사를 통해 보내야 한다"는 지적을 받았다. 같은 일을 되풀이하지 않는다.

## 규칙

- **보내기는 `send.mjs`만 쓴다.** Composio `DISCORDBOT_CREATE_MESSAGE`, 웹훅, 직접 API 호출로 보내지 않는다. `composio-first`가 SaaS는 Composio부터라고 해도 Discord 전송은 예외다.
- **읽기는 Composio를 써도 된다.** 채널·스레드 목록(`DISCORDBOT_LIST_GUILD_CHANNELS`)과 최근 글 읽기(`DISCORDBOT_LIST_MESSAGES`)는 보내기가 아니다.
- 규칙과 값은 `~/automations/discord-delegate/`가 맞다. 보내기 전에 `INSTRUCTIONS.md`의 "글 보내기"와 `directory.json`·`rules.json`을 읽는다. 이 문서와 다르면 그 폴더가 맞다.

## 보내는 법

```
cd ~/automations/discord-delegate
printf '%s' "본문" | doppler run -p saladlab -c dev -- node send.mjs <channel_id> [--reply <message_id>] [--mention <user_id>]
```

- 본문은 stdin으로만 넘긴다(백틱·따옴표가 셸에서 깨진다). 1~2000자.
- 알림을 보낼 사람은 `--mention <user_id>`로 준다. 본문에 `<@id>`만 적으면 알림이 가지 않는다. 한 글에 한 사람만 부른다.
- 토큰은 Doppler `saladlab/dev`의 `DISCORD_BOT_TOKEN`이다. 출력하거나 파일에 저장하지 않는다.
- 성공하면 `{"id","channel_id"}` 한 줄이 나온다. 그 글 ID를 사용자에게 알린다.

## 보내기 전에

1. **채널을 추측하지 않는다.** 사용자가 채널·스레드를 말하지 않았거나 이름이 둘 이상에 맞으면 물어본다. 틀린 채널의 글은 되돌릴 수 없다. 이름 → ID는 `directory.json`의 `channels`에 없으면 Composio로 `DISCORDBOT_LIST_GUILD_CHANNELS`(서버 ID는 `directory.json`의 `guild_id`)를 읽어 찾는다. `🚨모니터링방`의 `알파카`는 알럿 채널이라 대화용이 아니다.
2. **멘션할 사람의 ID를 확인한다.** `directory.json`의 `people`에 없으면 채널의 최근 글 작성자 목록에서 찾고, 같은 이름의 계정이 둘 이상이면(예: 이태용 / 네오-이태용 봇) 어느 쪽인지 사용자에게 알린다.
3. **오너 이름으로 결정하거나 약속하는 글을 쓰지 않는다.** 사용자가 시킨 사실 전달만 한다.
4. **근무 시간(`rules.json`의 `work_hours`, 평일 09:00–19:00) 밖에는 멘션이 들어간 글을 보내지 않고** 사용자에게 미룰지 묻는다. 멘션 없는 글은 보내도 된다.
5. **초안을 사용자가 못 봤으면 먼저 보여 준다.** 사용자가 문구까지 정해 주었거나 "그대로 보내"라고 한 경우만 바로 보낸다.

## 글머리

`rules.json`의 `prefix`(`[오한준 대리 · {issue}]`)는 Linear 이슈를 맡은 작업(`obaksa` 스킬)의 글에 붙인다. 이슈와 무관한 일회성 전달에는 이슈 번호가 없으므로 사용자에게 글머리를 붙일지 한 번 묻는다. 묻지 못하면 오박사가 보냈다는 점이 보이도록 이슈 번호 없이 `[오한준 대리]`로 시작한다.

## 이슈를 맡아 스레드로 일하는 경우

이슈 전용 스레드 생성, 수신기, 승인 판정, 재촉은 `obaksa` 스킬을 쓴다. 이 스킬은 "한 번 보내기"만 다룬다.
