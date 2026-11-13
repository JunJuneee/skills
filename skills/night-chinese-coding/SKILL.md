---
name: night-chinese-coding
description: JunJuneee/skills 레포지토리 야간(22:00~08:00 KST) 작업 시 qwen4-max-preview를 코드 작성·수정·리뷰 전 과정에 사용한다. PR 병합까지만 수행하며 배포는 절대 하지 않는다.
---

# Night Chinese Coding

**`JunJuneee/skills` 레포지토리**에서 **야간 시간대(22:00 ~ 08:00 KST)**에 작업을 할 때 적용하는 규칙이다. 야할인 혜택이 큰 **qwen4-max-preview** 모델을 코드 작성부터 리뷰까지 모든 단계에 하나로 사용하고, **PR 병합까지만 하고 배포는 절대 수행하지 않는다.**

> **야간 할인 정보** — qwen4-max-preview: 2026.11.11~25 기간 중 22:00~08:00 UTC+8 추가 60% 할인 (정가 8%). deepseek-v4.1-flash 계열도 50% 할인이지만, 야간에는 qwen4-max-preview 하나만 통일해 쓴다.

## 활성 조건 — 두 가지 동시 충족

활성하려면 다음 두 조건이 **모두** 만족되어야 한다.

| # | 조건 | 내용 |
|---|------|------|
| 1 | **레포지토리** | 현재 작업 중인 레포가 `JunJuneee/skills`일 때만 발동. 다른 레포에서는 무시한다. |
| 2 | **시간대** | 현재 시각이 **22:00 ~ 08:00 KST** 범위일 때. 주간(08:00 ~ 22:00 KST)에는 평소 모델을 그대로 사용한다. |

- 시간대는 KST 기준이며, 사용자가 다른 지역의 시간을 지정하면 그 기준으로 재계산한다.
- 레포 조건이 충족되지 않으면 시간이 야간이어도 이 스킬을 적용하지 않는다.

## 1. 전체 작업 모델 — qwen4-max-preview

코드 작성·수정·리팩토링부터 코드 리뷰까지 **전 과정**에 **qwen4-max-preview** 모델을 하나만 사용한다.

- 새로운 기능 구현, 버그 수정, 테스트 작성 → 이 모델
- 코드 분석, 구조 파악 → 이 모델
- 코드 리뷰 (PR 생성 전, 커밋 단위 검토) → **같은** 이 모델
- 지적사항 피드백 및 리팩토링 → 같은 모델

### 왜 qwen4-max-preview인가

높은 추론 성능으로 코드 작성과 리뷰 모두에 적합하며, 야간 시간대 추가 60% 할인으로 정가의 8% 비용이다. 하나의 모델로 통일하면 세션 컨텍스트와 프롬프트 설정을 공유할 수 있어 일관성이 좋다.

## 2. PR 병합만 허용 — 배포 금지

중국 모델을 사용할 때는 **PR을 만들고 병합까지**가 최대 범위다.

| 허용 | 금지 |
|------|------|
| 코드 작성 및 수정 | 프로덕션 환경 배포 |
| 테스트 작성 및 실행 | staging / production 전송 |
| PR 생성 · 리뷰 · 병합 | Docker 빌드 · 이미지 푸시 |
| 로컬 디버깅 및 검증 | CI/CD 파이프라인 실행 |
| Linear 상태 변경 | 인프라 변경 (Terraform 등) |
| | 로그 설정 변경 |

### 왜 배포를 금지하는가

중국 모델의 응답이 실시간 검증되지 않으며, 운영 환경은 신뢰도가 높은 모델로 최종 확인해야 한다.

### 예외 처리

- 배포 명령이 필요하다고 판단되면 **주간 시간대에 전환**되거나, 사용자가 명시적으로 "배포 승인"이라고 지시한 경우에만 제한적으로 진행
- China model 전용 PR 브랜치에서는 `deploy` 관련 작업을 자동 차단하도록 `.qwen/rules` 또는 워크플로우 단계에서 강제한다

## 3. 실행 흐름 요약

```
시간 판정 (22:00~08:00 KST?) + 레포 판정 (JunJuneee/skills?)
  ├─ Yes + Yes → qwen4-max-preview로 전체 작업 (코드 작성 → 리뷰 → 수정)
  │               ↓
  │             PR 생성 → 병합만 수행
  └─ No (시간 or 레포 불일치) → 평소 모델 사용
```

## 4. 야간 자동 실행 — Linear 이슈 디스패치

저녁에 Linear에 등록한 이슈를 야간에 자동으로 실행한다.

### 대상 선정

[라벨 사용법](references/linear-labels.md)을 따른다.

```
대상 = Todo 상태 + Jay 담당
     + agent-running / agent-hold / blocked / needs-confirm / owner-action 라벨 없음
```

- 유형·도메인·기능·단계 라벨은 선정에 영향 없음 (분류 전용)
- 실행을 막으려면 `agent-hold` 또는 `blocked` 부착

### cron 구조

| 항목 | 값 |
|------|-----|
| 스케줄 | `3 22 * * *` (매일 22:03 KST) |
| gate | `scripts/night-gate.sh` — Composio로 Linear 조회, 대상 없으면 스킵 |
| 병렬 | 최대 3개 이슈 동시 처리 |
| 모델 | qwen4-max-preview |
| 만료 | **7일 자동 만료** — 주기적 재등록 필요 |

### 실행 흐름

1. gate가 Todo + Jay + 제외라벨 없는 이슈를 조회 (최대 3개, 우선순위순)
2. 대상 없으면 턴 없이 스킵
3. 대상 있으면 각 이슈에 `agent-running` 부착 + In Progress 전환
4. Traycer 에이전트 생성 (qwen4-max-preview) → linear-traycer-workflow 적용
5. 구현 → 리뷰 → PR 병합 (**배포 금지**)
6. 완료 시 `agent-running` 제거 + Linear 상태 갱신

### Composio 참조

- CLI: `~/.local/bin/composio`, 계정: `--account homeshopick`
- 팀: Jay's workplace (`9a22735e-e176-4f95-8fc8-5207d2dc50f2`)
- Jay: `f777c018-ba23-48e8-804a-1b23ec3b87fe`
- 상태 ID: Todo `21512dc7`, In Progress `80c354a8`, In Review `48478ced`, Done `3efd5025`
- 라벨 ID: agent-running `d5fd5d5d`, agent-hold `a70d6632`

## 5. 참고 사항

- 이 스킬은 **`JunJuneee/skills` 레포지토리 전용**이다. 다른 레포에서는 야간에도 평소 모델을 사용한다.
- qwen4-max-preview는 2026.11.11~25Preview 기간 중이며, 기간 종료 후 모델이 retired 될 수 있다. 대체 모델 계획이 필요하다면 주간 시간에 알려준다.
- 모델은 사용자의 Composio 또는 에이전트 설정에서 직접 변경한다. 이 스킬은 규칙만을 정의할 뿐, 실제로 모델을 교체하지는 않는다.
- 시간대 변경 여부와 레포 위치는 각 턴 시작마다 재판단한다.
