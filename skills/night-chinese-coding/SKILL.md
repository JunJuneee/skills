---
name: night-chinese-coding
description: JunJuneee/skills 레포지토리 야간(22:00~08:00 KST) 작업 시 코딩은 qwen4-max-preview, 리뷰는 deepseek-v4-pro-0813을 사용한다. PR comment 기반 리뷰 루프로 문제가 없을 때까지 반복 후 병합하며 배포는 절대 하지 않는다.
---

# Night Chinese Coding

**`JunJuneee/skills` 레포지토리**에서 **야간 시간대(22:00 ~ 08:00 KST)**에 작업을 할 때 적용하는 규칙이다.

- **코딩**: qwen4-max-preview (야간 정가 8% 할인)
- **리뷰**: deepseek-v4-pro-0813 (야간 50% 할인)
- **PR comment 기반 리뷰 루프**: 문제가 없을 때까지 반복 → 병합
- **배포 절대 금지**

> **야간 할인 정보** — qwen4-max-preview: 2026.11.11~25 기간 중 22:00~08:00 UTC+8 추가 60% 할인 (정가 8%). deepseek-v4-pro-0813: 22:00~08:00 UTC+8 50% 할인.

## 활성 조건 — 두 가지 동시 충족

| # | 조건 | 내용 |
|---|------|------|
| 1 | **레포지토리** | 현재 작업 중인 레포가 `JunJuneee/skills`일 때만 발동. 다른 레포에서는 무시한다. |
| 2 | **시간대** | 현재 시각이 **22:00 ~ 08:00 KST** 범위일 때. 주간(08:00 ~ 22:00 KST)에는 평소 모델을 그대로 사용한다. |

- 시간대는 KST 기준이며, 사용자가 다른 지역의 시간을 지정하면 그 기준으로 재계산한다.
- 레포 조건이 충족되지 않으면 시간이 야간이어도 이 스킬을 적용하지 않는다.

## 1. 코딩 모델 — qwen4-max-preview

코드 작성·수정·리팩토링·테스트는 **qwen4-max-preview** 모델을 사용한다.

- 새로운 기능 구현, 버그 수정, 테스트 작성, 기존 코드 개선
- 코드 분석, 구조 파악
- 리뷰 지적사항 수정 및 리팩토링

## 2. 리뷰 모델 — deepseek-v4-pro-0813

코드 리뷰는 **deepseek-v4-pro-0813** 모델에게 요청한다. 코딩 모델과 **별도**의 리뷰 전용 모델을 사용한다.

- PR 생성 후 deepseek-v4-pro-0813에게 리뷰 요청
- 리뷰 결과는 **PR comment**로 남긴다
- 코드 품질, 논리적 오류, 경계 조건, 보안, 일관성 검토
- 지적사항은 실제 수정 가능한 형태로 구체적으로 남긴다

## 3. PR 리뷰 루프 — comment 기반

**문제가 없을 때까지 리뷰를 반복한다.** 한 번의 리뷰로 끝내지 않는다.

### 흐름

```
qwen4-max-preview로 구현 완료
  ↓
PR 생성 (draft 또는 regular)
  ↓
deepseek-v4-pro-0813에게 리뷰 요청
  ↓
리뷰 결과를 PR comment로 게시
  ├─ 지적 있음 → qwen4-max-preview로 수정 → push → 재리뷰 요청 (반복)
  └─ 지적 없음 → "작업 완료" comment 게시 → PR 병합
```

### 규칙

1. **리뷰 요청**: PR이 생성되면 deepseek-v4-pro-0813에게 리뷰를 요청한다. 리뷰어는 구현에 참여하지 않은 별도 세션/에이전트여야 한다.
2. **comment 게시**: 리뷰 결과(지적사항, 승인, 반려)는 반드시 **PR comment**로 남긴다. 로컬 보고나 Linear 요약만으로 대체하지 않는다.
3. **수정 후 재리뷰**: 지적사항을 수정하고 push한 뒤, 반드시 deepseek-v4-pro-0813에게 **재리뷰**를 요청한다. 이전 리뷰의 승인으로 새 변경을 통과시키지 않는다.
4. **완료 comment**: 모든 지적이 해소되고 리뷰어가 승인하면, PR에 **"작업 완료"** comment를 남긴다.
5. **병합**: 완료 comment 게시 후 PR을 병합한다. 병합 전 최신 head·필수 체크·저장소 정책을 확인한다.
6. **반복 제한 없음**: 문제가 없을 때까지 반복한다. 라운드 수를 채웠다는 이유로 끝내지 않는다.

### comment 형식 예시

```markdown
## 리뷰 결과 (deepseek-v4-pro-0813)

**대상 SHA**: abc1234
**결론**: 변경 요청

### 지적사항
1. [파일:라인] 설명...
2. [파일:라인] 설명...

---
수정 후 재리뷰를 요청합니다.
```

```markdown
## 작업 완료

모든 리뷰 지적사항이 해소되었습니다.
- 리뷰어: deepseek-v4-pro-0813
- 최종 SHA: def5678
- 리뷰 라운드: 3
- 결론: 승인

PR을 병합합니다.
```

## 4. 배포 금지 — 절대 규칙

**중국 모델을 사용하는 야간 작업에서 배포는 절대 수행하지 않는다.**

| 허용 | 금지 |
|------|------|
| 코드 작성 및 수정 | 프로덕션 환경 배포 |
| 테스트 작성 및 실행 | staging / production 전송 |
| PR 생성 · 리뷰 · 병합 | Docker 빌드 · 이미지 푸시 |
| 로컬 디버깅 및 검증 | CI/CD 파이프라인 트리거 |
| Linear 상태 변경 | 인프라 변경 (Terraform 등) |
| PR comment 게시 | 로그 설정 변경 |

배포가 필요하면 **주간 시간대에 전환**하거나 사용자가 명시적으로 "배포 승인"이라고 지시한 경우에만 진행한다. 야간 자동 실행에서는 어떤 경우에도 배포하지 않는다.

## 5. 실행 흐름 요약

```
시간 판정 (22:00~08:00 KST?) + 레포 판정 (JunJuneee/skills?)
  ├─ Yes + Yes
  │    ↓
  │  qwen4-max-preview로 구현
  │    ↓
  │  PR 생성
  │    ↓
  │  deepseek-v4-pro-0813 리뷰 요청 ←──────────┐
  │    ↓                                       │
  │  PR comment로 리뷰 결과 게시                │
  │    ├─ 지적 있음 → 수정 → push → 재리뷰 ────┘
  │    └─ 지적 없음 → "작업 완료" comment → 병합
  │
  └─ No → 평소 모델 사용
```

## 6. 야간 자동 실행 — Linear 이슈 디스패치

저녁에 Linear에 등록한 이슈를 야간에 자동으로 실행한다.

### 대상 선정

[라벨 사용법](references/linear-labels.md)을 따른다.

```
대상 = Todo 상태
     + agent-running / agent-hold / blocked / needs-confirm / owner-action 라벨 없음
```

- **담당자 조건 없음** — Todo 이슈는 모두 사용자 소유이므로 담당자로 필터링하지 않는다.
- 유형·도메인·기능·단계 라벨은 선정에 영향 없음 (분류 전용)
- 실행을 막으려면 `agent-hold` 또는 `blocked` 부착
- 우선순위순(긴급→높음→보통→낮음→없음)으로 최대 3개 선정

### cron 구조

| 항목 | 값 |
|------|-----|
| 스케줄 | `3 22 * * *` (매일 22:03 KST) |
| gate | `scripts/night-gate.sh` — Composio로 Linear 조회, 대상 없으면 스킵 |
| 병렬 | 최대 3개 이슈 동시 처리 |
| 코딩 모델 | qwen4-max-preview |
| 리뷰 모델 | deepseek-v4-pro-0813 |
| 만료 | **7일 자동 만료** — 주기적 재등록 필요 |

### 실행 흐름

1. gate가 Todo + 제외라벨 없는 이슈를 조회 (최대 3개, 우선순위순)
2. 대상 없으면 턴 없이 스킵
3. 대상 있으면 각 이슈에 `agent-running` 부착 + In Progress 전환
4. Traycer 에이전트 생성 (qwen4-max-preview) → 구현
5. PR 생성 → deepseek-v4-pro-0813 리뷰 → comment → 수정 → 재리뷰 반복
6. 문제 없으면 "작업 완료" comment → PR 병합 (**배포 금지**)
7. 완료 시 `agent-running` 제거 + Linear 상태 갱신

### Composio 참조

- CLI: `~/.local/bin/composio`, 계정: `--account homeshopick`
- 팀: Jay's workplace (`9a22735e-e176-4f95-8fc8-5207d2dc50f2`)
- 상태 ID: Todo `21512dc7`, In Progress `80c354a8`, In Review `48478ced`, Done `3efd5025`
- 라벨 ID: agent-running `d5fd5d5d`, agent-hold `a70d6632`

## 7. 참고 사항

- 이 스킬은 **`JunJuneee/skills` 레포지토리 전용**이다. 다른 레포에서는 야간에도 평소 모델을 사용한다.
- qwen4-max-preview는 2026.11.11~25 Preview 기간 중이며, 기간 종료 후 모델이 retired 될 수 있다.
- deepseek-v4-pro-0813은 야간 50% 할인 대상이다.
- 모델은 사용자의 Composio 또는 에이전트 설정에서 직접 변경한다. 이 스킬은 규칙만을 정의할 뿐, 실제로 모델을 교체하지는 않는다.
- 시간대 변경 여부와 레포 위치는 각 턴 시작마다 재판단한다.
