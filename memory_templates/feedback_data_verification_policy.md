---
name: data-verification-policy
description: 종목명/코드 검증 의무 — FDR 사용, 추측 금지
metadata:
  type: feedback
---
## 종목 검증 정책

### 필수 규칙

1. **종목명/코드 추측 절대 금지**
   - 사용자가 종목명만 줘도 코드는 반드시 FDR로 검증
   - 검증 안 됐으면 `'?'`로 저장

2. **검증 방법**
   ```python
   import FinanceDataReader as fdr
   ks = fdr.StockListing('KRX')
   matches = ks[ks['Name'].str.contains('종목명', na=False)]
   ```

3. **검증된 매핑 재사용**
   - `project_verified_tickers.md`에 검증된 코드 누적
   - 동일 종목 재검증 불필요

### 자주 혼동하는 종목

#### 우선주
- 현대차우 (005385) ← **1우 (참가적/누적 X)**
- 현대차2우B (005387) ← 2우B (누적적)
- 삼성전자우 (005935)

#### ETF
- TIGER 미국필라델피아반도체나스닥 (381180) ← 1배 실물
- TIGER 미국필라델피아반도체레버리지 (423920) ← 2배 합성
- PLUS K방산 (449450) ← KODEX 아님
- TIGER TSMC파운드리 (453950) ← 488500 아님

### 검증 실패 시
- 사용자에게 정확한 종목명 재확인
- 또는 가능한 후보 목록 제시

**Why:** 종목코드 잘못 매핑하면 전체 분석 무효화 가능.

**How to apply:** 새 종목 등장 시 즉시 FDR 검증 → `project_verified_tickers.md` 기록.
