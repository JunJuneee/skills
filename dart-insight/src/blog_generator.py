"""Blog post generator using Claude API for financial analysis reports."""
from __future__ import annotations

import logging

import anthropic

from src import db
from src.analyzer import analyze_company, get_importance_report, compare_periods

logger = logging.getLogger(__name__)


def generate_blog_post(corp_code: str, corp_name: str,
                       api_key: str, disclosure_ref: str = "") -> dict:
    """기업 재무분석 블로그 포스트를 자동 생성.

    Returns:
        dict with keys: title, content, summary
    """
    report = get_importance_report(corp_code)
    analysis = analyze_company(corp_code)

    prompt = _build_prompt(corp_name, report, analysis)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    content = message.content[0].text

    title, summary = _extract_title_summary(content, corp_name)

    post_id = db.insert_blog_post(
        corp_code=corp_code,
        corp_name=corp_name,
        title=title,
        content=content,
        summary=summary,
        disclosure_ref=disclosure_ref,
    )

    logger.info(f"Blog post created: [{post_id}] {title}")
    return {"id": post_id, "title": title, "content": content, "summary": summary}


def _build_prompt(corp_name: str, report: dict, analysis: dict) -> str:
    summary = report.get("summary", {})
    period = summary.get("period", "")

    changes_text = ""
    for c in report.get("high_changes", []):
        sign = "+" if c["change_rate"] > 0 else ""
        changes_text += f"- {c['account_name']}: {_format_amount(c['prev_amount'])} → {_format_amount(c['amount'])} ({sign}{c['change_rate']}%)\n"

    new_items_text = ""
    for item in report.get("new_items", []):
        new_items_text += f"- [{item['year']} {item['quarter']}] {item['account_name']}: {_format_amount(item.get('amount'))}\n"

    trends_text = ""
    for account, data in report.get("trends", {}).items():
        trend_line = ", ".join(f"{d['period']}: {_format_amount(d['amount'])}" for d in data[-4:])
        trends_text += f"- {account}: {trend_line}\n"

    key_metrics_text = ""
    for key, val in summary.items():
        if key == "period" or not isinstance(val, dict):
            continue
        rate = val.get("change_rate")
        rate_str = f" ({'+' if rate > 0 else ''}{rate}%)" if rate is not None else ""
        key_metrics_text += f"- {key}: {_format_amount(val.get('amount'))}{rate_str}\n"

    # 재무비율 텍스트
    ratios = analysis.get("ratios", {})
    ratios_text = ""
    ratio_labels = {
        "영업이익률": "%", "순이익률": "%", "매출총이익률": "%", "매출원가율": "%",
        "부채비율": "%", "ROE": "%", "ROA": "%", "자기자본비율": "%",
        "현금흐름_영업이익_비율": "%",
    }
    for key, unit in ratio_labels.items():
        val = ratios.get(key)
        if val is not None:
            ratios_text += f"- {key}: {val}{unit}\n"

    # 이익의 질 시그널 텍스트
    quality_signals = analysis.get("quality_signals", [])
    signals_text = ""
    for s in quality_signals:
        emoji = {"WARNING": "⚠️", "CAUTION": "🟡", "INFO": "ℹ️", "POSITIVE": "✅"}.get(s["type"], "")
        signals_text += f"- {emoji} [{s['type']}] {s['signal']}: {s['detail']}\n"

    return f"""당신은 10년 경력의 한국 주식시장 애널리스트(CFA)입니다.
기관투자자에게 보내는 수준의 분석 리포트를 작성하세요. 단순 숫자 나열이 아니라,
숫자 뒤에 숨은 의미와 비즈니스 맥락을 읽어내는 것이 핵심입니다.

## 기업: {corp_name}
## 최신 기간: {period}

---

### 📊 핵심 재무지표
{key_metrics_text or "데이터 없음"}

### 📐 재무비율 분석
{ratios_text or "계산 불가"}

### ⚡ 주요 변동사항 (±20% 이상)
{changes_text or "없음"}

### 🆕 신규 등장 항목 (이전에 없던 계정과목)
{new_items_text or "없음"}

### 📈 분기별 추이 (최근 4분기)
{trends_text or "데이터 부족"}

### 🔬 이익의 질 시그널 (자동 감지)
{signals_text or "특이사항 없음"}

---

## 작성 가이드 (엄격히 준수):

### 구조 (이 순서로 작성)

**1. 제목** (1줄)
- 핵심 변화를 숫자와 함께 요약. 뻔한 제목 금지.
- 좋은 예: "삼성전자, AI 반도체 효과로 영업이익 30% 급증…그러나 재고 리스크 부상"
- 나쁜 예: "삼성전자 3분기 실적 발표"

**2. 핵심 요약 (Executive Summary)** (3줄)
- 이 리포트를 10초 만에 읽는 사람에게 전달할 3가지 포인트.

**3. 수익성 분석**
- 매출총이익률, 영업이익률, 순이익률 추이 해석
- 원가 구조 변화가 의미하는 것 (원재료? 인건비? 감가상각?)
- 이익률 개선/악화의 지속가능성 판단

**4. 재무건전성 진단**
- 부채비율, 자기자본비율로 본 재무구조 안정성
- 유동비율 관점에서 단기 유동성 리스크
- 차입금 변동이 있다면 그 목적 추론 (설비투자? 인수합병? 운전자본?)

**5. 현금흐름 품질 분석**
- 영업CF vs 당기순이익 비교 → 이익의 현금 전환력
- 투자CF 방향 → 성장투자 중인지, 수확기인지
- 재무CF → 차입 증가? 배당 지급? 자사주 매입?

**6. 핵심 변동 딥다이브**
- 20% 이상 변동한 항목 각각에 대해 WHY 분석
- 업종/산업 맥락에서 이 변동이 갖는 의미
- 일회성 vs 구조적 변화 구분

**7. 신규 항목 해석** (있는 경우)
- 이전에 없던 계정과목이 왜 등장했는지
- 사업 확장? 구조조정? 회계기준 변경? M&A?
- 향후 이 항목이 실적에 미칠 영향

**8. 리스크 요인** (최소 2가지)
- 이익의 질 시그널에서 감지된 위험 요소
- 산업 차원의 리스크 (경쟁, 규제, 환율, 원자재)
- 기업 고유 리스크 (집중도, 거버넌스, 소송)

**9. 향후 전망 (1~2분기)**
- 현재 추이가 지속된다면 예상되는 방향
- 업황 전환 가능성이 있는 촉매 이벤트
- 컨센서스 대비 상/하방 시나리오

**10. 투자 시사점**
- 기관투자자 관점에서 이 실적이 주가에 미칠 영향
- 밸류에이션 관점 (이익 개선 → 멀티플 리레이팅 가능?)
- 모니터링할 핵심 지표 (다음 분기 체크포인트)

---

## 톤 & 스타일:
- Markdown으로 작성. 각 섹션에 ### 헤더 사용
- 숫자에 반드시 단위 포함 (억원, 조원, %)
- 추론할 때는 "~로 추정된다", "~가능성이 있다"로 표현 (단정 금지)
- 비교 시 절대금액과 변동률 모두 제시
- 업계 통상적 수준과 비교하여 해석 (예: "동종업계 평균 영업이익률 8% 대비 12%로 우위")
- 투자 추천/비추천은 하지 않으며, 판단 근거만 제시
"""


def _extract_title_summary(content: str, corp_name: str) -> tuple[str, str]:
    """블로그 콘텐츠에서 제목과 요약을 추출."""
    lines = content.strip().split("\n")

    title = f"{corp_name} 재무분석 리포트"
    for line in lines:
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            title = stripped
            break

    summary_lines = []
    in_summary = False
    for line in lines[1:]:
        stripped = line.strip()
        if "핵심 요약" in stripped or "요약" in stripped:
            in_summary = True
            continue
        if in_summary:
            if stripped.startswith("#") or (not stripped and summary_lines):
                break
            if stripped:
                summary_lines.append(stripped)

    summary = " ".join(summary_lines[:3]) if summary_lines else title

    return title, summary


def _format_amount(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1_0000_0000:
        return f"{value / 1_0000_0000:.1f}조원"
    if abs(value) >= 1_0000:
        return f"{value / 1_0000:.0f}억원"
    return f"{value:,.0f}원"
