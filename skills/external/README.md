# External Skills (외부 제공)

> ⚠️ chart-analyst 는 `skills/chart-analyst/` 로 이동했습니다 (Claude Code / Codex 자동 스캔 대상).

이 디렉토리는 **외부에서 제공받은 Claude Code Skills**의 백업입니다.

## 포함 스킬

### chart-analyst (v1.8)
- **용도**: 기술적 차트 분석 5단계 프레임워크
- **출처**: 외부 제공 (70개 방송 검증 메타분석 적용)
- **버전**: v1.8 (2026-05-15 한국주식 FDR 확정)
- **호출**: `/chart-analyst [종목명]`

### ~~financial-analyst~~ → 정식 스킬로 이동
- 이전 위치: `skills/external/financial-analyst/`
- 새 위치: `skills/financial-analyst/`
- 이유: dart-insight 통합으로 본 repo 자체 완결성 확보

## 우리가 만든 스킬과의 차이

| 항목 | 우리 스킬 (../) | 외부 스킬 (이 폴더) |
|---|---|---|
| 작성자 | 본인 | 외부 |
| 수정 권한 | 자유 수정 | 원본 유지 권장 |
| 트리거 | 자연어 + 명시 | 명시 호출 (/이름) |
| 깊이 | 일상 분석 (빠름) | 정밀 분석 (정확) |

## ⚠️ 주의

- 이 폴더의 파일은 **참고/백업용**입니다
- 실제 Claude Code가 읽는 위치는 `~/.claude/skills/`
- 외부 스킬은 원본 무단 수정 자제 (라이선스 확인 필요)

## 동기화

외부 스킬이 업데이트될 경우:
```bash
cp ~/.claude/skills/chart-analyst/SKILL.md skills/chart-analyst/
```

## 활용 예시

### chart-analyst (5단계 분석)
```
사용자: /chart-analyst SK하이닉스
사용자: 효성중공업 차트 분석해줘
사용자: BTC 지금 어때?
```
