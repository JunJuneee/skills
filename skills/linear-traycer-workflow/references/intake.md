# 인입과 줄

어떤 이슈를 집고 어느 줄로 처리할지 정한다. 감시 실행기와 조율자가 같은 규칙을 쓰도록 판정은 `scripts/preflight.py`에 있고, 값은 [policy.json](../policy.json)의 `intake`에 있다. 라벨의 뜻은 [Linear 라벨 사용법](linear-labels.md)을 따른다.

## ready의 정의

아래를 모두 만족하는 이슈만 시작한다.

- 상태가 Todo다. Backlog 전체를 승인된 큐로 보지 않는다.
- 제어 라벨(`owner-action`, `needs-confirm`, `agent-hold`, `hold`, `blocked`, `agent-running`)이 없다.
- 에픽이나 하위 이슈가 있는 상위 이슈가 아니다.
- 이 이슈의 열린 PR이 없다. 있으면 새로 구현하지 않고 그 작업을 이어간다.
- blocks 관계의 선행 이슈가 모두 완료 또는 취소 상태다.
- 본문에서 완료 기준 목록을 찾을 수 있고, 체크되지 않은 항목이 하나 이상 있다.
- 대상 저장소가 하나로 정해진다.
- 이번 실행의 역할을 모두 채울 수 있다(`resolve.py`의 `wait`가 비어 있다).

## 선행 관계

선행 이슈는 Linear의 blocks 관계로만 인정한다. 본문에 "선행: JAY-N"처럼 적혀 있는데 관계가 없으면 사전 점검이 걸러낸다. 선행 제목 아래의 식별자는 모두, 그 밖의 줄에서는 "선행"·"requires" 같은 말 뒤에 나오는 식별자만 선행 선언으로 본다. 이때 실행하지 않고 관계를 연결하거나 문구를 고쳐야 한다고 남긴다. 이슈를 만드는 쪽(`linear-create`)은 선행 이슈를 본문에 적을 때 관계도 함께 만든다.

## 줄 정하기

| 줄 | 라벨 | 대상 |
| --- | --- | --- |
| S | `lane-s` | 원인이 이미 특정됐고 변경이 국소적이며 기존 테스트나 작은 회귀 테스트로 확인되는 수정 |
| M | `lane-m` 또는 라벨 없음 | 이슈가 목표·범위·완료 기준을 담고 있고 영향이 한정된 작업 |
| L | `lane-l` | 데이터 삭제나 복구가 어려운 마이그레이션, 인증·권한의 중대한 변경, 결제·금전 처리, 광범위한 구조 변경 |

- 줄은 사람이 라벨로 정한다. 라벨이 없으면 M이다. 실행기와 조율자는 줄을 S로 낮추지 않는다.
- 본문이나 제목에 정책의 고위험 단어가 있는데 줄 라벨이 없으면 실행하지 않고 줄 확인을 요청한다. 사람이 `lane-s`·`lane-m`·`lane-l` 중 하나를 붙이면 그 판단을 따른다. 단어는 자동 분류가 아니라 확인을 요청하는 계기다. 실제 영향과 복구 가능성으로 판단하며, 불명확하고 피해가 클 수 있으면 L로 본다.
- 진행 중에 영향이 커진 것을 알게 되면 줄을 올리고 올라간 줄의 critique와 승인을 채운다.

## 사전 점검 실행

실행기는 Linear에서 읽은 이슈를 아래 모양으로 바꿔 표준 입력으로 넘긴다. 모델을 부르지 않는다.

```json
{"identifier": "JAY-1", "title": "...", "description": "...", "state": "Todo",
 "labels": ["lane-m"], "children": 0, "has_open_pr": false,
 "blocked_by": [{"identifier": "JAY-0", "state_type": "completed"}],
 "repo": "JunJuneee/seoul-seeing"}
```

```bash
python3 scripts/preflight.py --project seoulseeing --exhausted codex < issue.json
```

| 종료 코드 | 뜻 | 처리 |
| --- | --- | --- |
| 0 | 실행 가능 | 출력의 `lane`과 `roster`로 계약을 만들어 시작한다 |
| 2 | 이슈 쪽 문제 | 시작하지 않는다. `reasons`를 한 줄로 기록하고, 이슈가 갱신될 때까지 다시 고르지 않는다 |
| 3 | 모델 대기 | 시작하지 않는다. 사용량이 회복되면 다시 점검한다 |

사람이 고쳐야 풀리는 사유(완료 기준 없음, 선행 관계 누락, 줄 확인)는 하루 두 번의 결정 목록에 올린다. 선행 이슈 대기와 모델 대기는 기계가 풀 수 있으므로 알리지 않는다.

## 실행기 연결

실행기는 원장의 스크립트를 명령으로 부르고 JSON만 주고받는다. 원장 코드를 import하지 않는다.

**프로젝트별 설정.** 상태 이름이나 완료 기준 제목이 다른 프로젝트는 정책의 `projects.<이름>`에 `ready_states`, `criteria_headings`를 적는다. 없으면 `intake`의 기본값을 쓴다.

**Linear 응답을 그대로 넘기기.** 실행기가 읽은 이슈 노드(`state{name type}`, `labels{nodes}`, `children`, `inverseRelations`)는 바꾸지 않고 넘길 수 있다. 대상 저장소와 열린 PR 여부는 실행기가 판정해 인자로 준다. 관계나 라벨을 일부만 읽었으면(`pageInfo.hasNextPage`) 실행하지 않는다.

```bash
python3 scripts/preflight.py --project core-ser --from-linear --repo SaladLabInc/x < node.json
```

**명세에 배정을 적는다.** 점검이 통과하면 출력의 `lane`, `roster`, `policy`를 실행 명세(manifest)에 같은 이름으로 적어 조율자에게 넘긴다. `policy`는 발송 때의 병합된 정책이고, 나중에 정책이 바뀌어도 영수증을 그때 정책으로 대조하는 데 쓴다. 조율자는 `roster.roles`와 `roster.limits`를 따르며 모델을 문장으로 고르지 않는다. 조율자 자신도 `roster.roles.coordinator`로 띄운다.

**완료 영수증.** 조율자는 끝낼 때 실제로 수행한 내용을 영수증에 적는다. 프로젝트의 기존 필드(`run_id`, `pr_number`, `head_sha` 등)는 그대로 두고 아래를 더한다.

```json
{"status": "completed", "lane": "M",
 "implement": {"family": "codex", "model": "gpt-6.1-terra", "session_id": "..."},
 "review": {"url": "https://github.com/o/r/pull/1#issuecomment-1", "family": "qwen",
            "model": "qwen4-max-preview(openai)", "session_id": "...",
            "verified_from_transcript": true, "rounds": 2, "unresolved_valid_findings": 0}}
```

실행 도중 모델이 바뀌었으면 일어난 순서대로 `fallback`에 적고, `implement`·`review`에는 마지막에 실제로 수행한 계열과 모델을 적는다. `role`은 `implement`·`reviewer`·`critic`이다. `reason`은 사용량 소진이면 `usage`, 리뷰 2회째에 구현 모델을 `roster.escalation`으로 올렸으면 `escalation`이다(구현만, 한 번만).

```json
{"implement": {"family": "claude", "model": "sonnet", "session_id": "..."},
 "fallback": [{"role": "implement", "from": "codex", "to": "claude", "reason": "usage", "at": "..."}]}
```

```bash
python3 scripts/receipt.py validate --manifest manifest.json --receipt receipt.json
```

| 대조 | 통과 조건 |
| --- | --- |
| 구현 모델 | 전환 기록을 따라간 끝의 모델과 정확히 같음. 기록이 없으면 배정된 모델. 올린 모델은 `escalation` 기록이 있고 리뷰가 2회 이상일 때만 인정 |
| 리뷰 모델 | 배정된 리뷰어와 같음 |
| 전환 | `fallback`을 순서대로 다시 계산한다. 각 기록의 `from`이 그 시점에 실제로 돌던 계열이고 `to`가 다시 계산한 배정이어야 한다. 사용량 전환 횟수는 상한에 포함된다. 올린 뒤의 구현 전환은 다시 계산한 상향 대상으로만 갈 수 있고, 갈 곳이 없으면 완료가 아니라 대기다 |
| 같은 계열 리뷰 | 배정이 `same_family`를 허용했고 영수증에도 `same_family: true`가 있음 |
| 실행 모델 확인 | `verified_from_transcript`가 참. Claude 별칭만 확인됐으면 `alias_only: true`를 적으며 최종 줄이 L이 아닐 때만 인정 |
| 리뷰 세션 | 구현 세션과 다른 `session_id` |
| 리뷰 횟수 | `limits.review_rounds` 이하이고 미해결 유효 지적 0건. 상한을 넘겼으면 완료가 아니라 차단으로 넘긴다 |
| 줄 | 명세의 줄과 같거나 높음 |

종료 코드는 0 통과, 2 불일치다. 형식이 틀리거나 읽을 수 없는 입력도 2다. PR 상태·head·Linear 상태는 이 스크립트가 보지 않고 실행기가 확인한다. `roster` 키가 아예 없는 명세(이 규칙 전에 발송된 실행)와 완료가 아닌 영수증은 대조하지 않고 통과시킨다. 명세에 `policy`가 없으면 현재 정책이 발송 때와 같을 때만 대조한다.

## 실행 중 지킬 것

- 이슈 하나에 실행은 하나다. 같은 이슈를 고르는 실행기를 둘 이상 두지 않으며, 야간에도 같은 실행기가 같은 규칙으로 고른다.
- 시작할 때 `agent-running`을 붙이고, 완료·차단·대기로 끝날 때 반드시 뗀다.
- 완료 확인이 정책의 `intake.slot_timeout_hours`를 넘겨 실패하면 알리고 슬롯을 비운다. 무기한 점유하지 않는다.
- 실행 결과 기록은 덮어쓰지 않고 이어 쓴다. 차단으로 끝난 실행이 나중에 완료되면 새 기록으로 남긴다.
