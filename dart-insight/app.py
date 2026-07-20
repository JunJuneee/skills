"""Streamlit dashboard for DART financial insights."""
from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from src import db
from src.analyzer import analyze_company, compare_periods
from src.dart_client import DartClient
from src.collector import collect_kospi_companies_fast, collect_financials, collect_all_kospi_financials

load_dotenv()
db.init_db()


def _format_amount(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    if abs(value) >= 1_0000_0000:
        return f"{value / 1_0000_0000:.1f}조"
    if abs(value) >= 1_0000:
        return f"{value / 1_0000:.0f}억"
    return f"{value:,.0f}"

st.set_page_config(page_title="DART Insight", page_icon="📊", layout="wide")
st.title("📊 DART Insight - KOSPI 재무분석 대시보드")

# Sidebar
st.sidebar.header("설정")
dart_key = st.sidebar.text_input("DART API Key", value=os.environ.get("DART_API_KEY", ""), type="password")

tab_search, tab_analysis, tab_blog, tab_monitor, tab_setup = st.tabs(
    ["🔍 검색", "📈 분석", "📝 블로그", "🖥️ 모니터링", "⚙️ 초기 설정"]
)

# ─── Tab 1: 검색 ───
with tab_search:
    st.header("기업 검색")
    query = st.text_input("기업명 또는 종목코드", placeholder="삼성전자, 005930")

    if query:
        results = db.search_companies(query)
        if results:
            for company in results:
                col1, col2, col3 = st.columns([3, 1, 1])
                col1.write(f"**{company['corp_name']}**")
                col2.write(company.get("stock_code", ""))
                col3.write(company.get("market", ""))

                with st.expander(f"{company['corp_name']} 재무제표"):
                    financials = db.get_financials(company["corp_code"])
                    if financials:
                        df = pd.DataFrame(financials)
                        display_cols = ["year", "quarter", "report_type", "account_name",
                                        "amount", "prev_amount", "is_new_item"]
                        available_cols = [c for c in display_cols if c in df.columns]
                        df_display = df[available_cols].copy()

                        # 금액 포맷
                        for col in ["amount", "prev_amount"]:
                            if col in df_display.columns:
                                df_display[col] = df_display[col].apply(_format_amount)

                        # 신규 항목 강조
                        if "is_new_item" in df_display.columns:
                            df_display["is_new_item"] = df_display["is_new_item"].map(
                                {1: "🆕 NEW", 0: ""}
                            )

                        st.dataframe(df_display, use_container_width=True, height=400)

                        # 신규 항목만 필터
                        new_items = db.get_new_items(company["corp_code"])
                        if new_items:
                            st.warning(f"⚠️ 신규 등장 항목 {len(new_items)}건 발견!")
                            st.dataframe(pd.DataFrame(new_items), use_container_width=True)
                    else:
                        st.info("수집된 재무데이터가 없습니다. '초기 설정' 탭에서 데이터를 수집하세요.")
        else:
            st.warning("검색 결과가 없습니다.")

# ─── Tab 2: 분석 ───
with tab_analysis:
    st.header("재무 분석")

    company_query = st.text_input("분석할 기업 검색", key="analysis_search", placeholder="삼성전자")
    if company_query:
        companies = db.search_companies(company_query)
        if companies:
            selected = st.selectbox(
                "기업 선택",
                options=companies,
                format_func=lambda x: f"{x['corp_name']} ({x.get('stock_code', '')})",
            )

            if selected:
                analysis = analyze_company(selected["corp_code"])

                # 주요 재무지표 요약
                summary = analysis.get("summary", {})
                if summary:
                    st.subheader(f"📊 {summary.get('period', '')} 주요 지표")
                    metrics_cols = st.columns(3)
                    i = 0
                    for key, val in summary.items():
                        if key == "period" or not isinstance(val, dict):
                            continue
                        rate = val.get("change_rate")
                        delta_str = f"{rate:+.1f}%" if rate is not None else None
                        metrics_cols[i % 3].metric(
                            label=key,
                            value=_format_amount(val.get("amount")),
                            delta=delta_str,
                        )
                        i += 1

                # 재무비율
                ratios = analysis.get("ratios", {})
                if ratios:
                    st.subheader("📐 재무비율")
                    ratio_col1, ratio_col2, ratio_col3 = st.columns(3)
                    profitability = ["영업이익률", "순이익률", "매출총이익률", "매출원가율"]
                    stability = ["부채비율", "자기자본비율", "ROE", "ROA"]
                    cashflow = ["현금흐름_영업이익_비율"]

                    with ratio_col1:
                        st.markdown("**수익성**")
                        for r in profitability:
                            if r in ratios:
                                st.metric(r, f"{ratios[r]}%")
                    with ratio_col2:
                        st.markdown("**안정성**")
                        for r in stability:
                            if r in ratios:
                                st.metric(r, f"{ratios[r]}%")
                    with ratio_col3:
                        st.markdown("**현금흐름**")
                        for r in cashflow:
                            if r in ratios:
                                label = "영업CF/영업이익"
                                st.metric(label, f"{ratios[r]}%")

                # 이익의 질 시그널
                quality_signals = analysis.get("quality_signals", [])
                if quality_signals:
                    st.subheader("🔬 이익의 질 시그널")
                    for s in quality_signals:
                        emoji = {"WARNING": "🔴", "CAUTION": "🟡", "INFO": "🔵", "POSITIVE": "🟢"}.get(s["type"], "⚪")
                        if s["type"] == "WARNING":
                            st.error(f"{emoji} **{s['signal']}**: {s['detail']}")
                        elif s["type"] == "CAUTION":
                            st.warning(f"{emoji} **{s['signal']}**: {s['detail']}")
                        elif s["type"] == "POSITIVE":
                            st.success(f"{emoji} **{s['signal']}**: {s['detail']}")
                        else:
                            st.info(f"{emoji} **{s['signal']}**: {s['detail']}")

                # 추이 차트
                trends = analysis.get("trends", {})
                if trends:
                    st.subheader("📈 분기별 추이")
                    for account_name, data in trends.items():
                        if data:
                            trend_df = pd.DataFrame(data)
                            fig = px.line(
                                trend_df, x="period", y="amount",
                                title=account_name,
                                labels={"period": "기간", "amount": "금액"},
                            )
                            fig.update_layout(height=300)
                            st.plotly_chart(fig, use_container_width=True)

                # 주요 변동
                changes = analysis.get("changes", [])
                if changes:
                    st.subheader("⚡ 주요 변동사항 (±20% 이상)")
                    changes_df = pd.DataFrame(changes)
                    changes_df["amount"] = changes_df["amount"].apply(_format_amount)
                    changes_df["prev_amount"] = changes_df["prev_amount"].apply(_format_amount)
                    changes_df["change_rate"] = changes_df["change_rate"].apply(
                        lambda x: f"{x:+.1f}%" if x else "-"
                    )
                    st.dataframe(changes_df, use_container_width=True)

                # 신규 항목
                new_items = analysis.get("new_items", [])
                if new_items:
                    st.subheader("🆕 신규 등장 항목")
                    st.warning("이전 동일 분기에 없던 계정과목이 새로 등장했습니다.")
                    st.dataframe(pd.DataFrame(new_items), use_container_width=True)

                # AI 애널리스트 리포트 (DB에서 조회)
                st.divider()
                st.subheader("🤖 AI 애널리스트 리포트")
                saved_reports = db.get_blog_posts(
                    corp_code=selected["corp_code"], tag="재무분석", limit=10
                )
                if saved_reports:
                    for rpt in saved_reports:
                        rpt_tags = rpt.get("tags", "")
                        tags_badges = " ".join(
                            f"`{t.strip()}`" for t in rpt_tags.split(",") if t.strip()
                        ) if rpt_tags else ""
                        with st.expander(
                            f"📄 {rpt['title']}  {tags_badges}  ({rpt.get('created_at', '')[:10]})",
                            expanded=(rpt == saved_reports[0]),
                        ):
                            st.markdown(rpt["content"])
                else:
                    st.info(
                        f"{selected['corp_name']}의 애널리스트 리포트가 없습니다. "
                        "Claude Code에서 분석을 요청하면 자동 저장됩니다."
                    )

                # 기간 비교
                st.subheader("🔄 기간 비교")
                comp_col1, comp_col2 = st.columns(2)
                with comp_col1:
                    y1 = st.number_input("비교 기준 연도", value=2024, min_value=2024, key="y1")
                    q1 = st.selectbox("비교 기준 분기", ["1Q", "2Q", "3Q", "4Q"], key="q1")
                with comp_col2:
                    y2 = st.number_input("비교 대상 연도", value=2025, min_value=2024, key="y2")
                    q2 = st.selectbox("비교 대상 분기", ["1Q", "2Q", "3Q", "4Q"], key="q2")

                if st.button("비교 실행"):
                    comparisons = compare_periods(selected["corp_code"], y1, q1, y2, q2)
                    if comparisons:
                        comp_df = pd.DataFrame(comparisons)
                        comp_df["prev_amount"] = comp_df["prev_amount"].apply(_format_amount)
                        comp_df["curr_amount"] = comp_df["curr_amount"].apply(_format_amount)

                        new_in_period = comp_df[comp_df["is_new"] == True]
                        removed = comp_df[comp_df["is_removed"] == True]

                        if not new_in_period.empty:
                            st.success(f"🆕 신규 항목 {len(new_in_period)}건")
                            st.dataframe(new_in_period, use_container_width=True)
                        if not removed.empty:
                            st.error(f"❌ 삭제된 항목 {len(removed)}건")
                            st.dataframe(removed, use_container_width=True)

                        st.dataframe(comp_df, use_container_width=True, height=500)
                    else:
                        st.info("비교할 데이터가 없습니다.")

# ─── Tab 3: 블로그 ───
with tab_blog:
    st.header("📝 분석 리포트")

    # 필터 영역
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        all_tags = db.get_all_tags()
        filter_tag = st.selectbox("태그 필터", ["전체"] + all_tags, key="blog_tag")
    with filter_col2:
        all_posts = db.get_blog_posts(limit=200)
        corp_names = sorted({p["corp_name"] for p in all_posts if p.get("corp_name")})
        filter_corp = st.selectbox("기업 필터", ["전체"] + corp_names, key="blog_corp")

    # 필터 적용 조회
    query_tag = filter_tag if filter_tag != "전체" else None
    query_corp = None
    if filter_corp != "전체":
        match = [c for c in all_posts if c.get("corp_name") == filter_corp]
        if match:
            query_corp = match[0]["corp_code"]
    blog_posts = db.get_blog_posts(corp_code=query_corp, tag=query_tag, limit=50)

    if blog_posts:
        for post in blog_posts:
            tags_display = ""
            post_tags = post.get("tags", "")
            if post_tags:
                tags_display = " ".join(f"`{t.strip()}`" for t in post_tags.split(",") if t.strip())

            with st.expander(
                f"📄 {post['title']}  {tags_display}  ({post.get('created_at', '')[:10]})"
            ):
                if tags_display:
                    st.markdown(f"**태그**: {tags_display}")
                st.markdown("---")
                st.markdown(post["content"])
    else:
        st.info("조건에 맞는 리포트가 없습니다.")

# ─── Tab 4: 모니터링 ───
with tab_monitor:
    st.header("🖥️ 시스템 상태")

    conn = db.get_connection()

    col1, col2, col3, col4 = st.columns(4)
    company_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    financial_count = conn.execute("SELECT COUNT(*) FROM financials").fetchone()[0]
    disclosure_count = conn.execute("SELECT COUNT(*) FROM disclosures").fetchone()[0]
    blog_count = conn.execute("SELECT COUNT(*) FROM blog_posts").fetchone()[0]

    col1.metric("등록 기업", f"{company_count:,}")
    col2.metric("재무 데이터", f"{financial_count:,}")
    col3.metric("공시 수", f"{disclosure_count:,}")
    col4.metric("블로그 포스트", f"{blog_count:,}")

    # 최근 공시
    st.subheader("최근 공시")
    recent = conn.execute(
        "SELECT * FROM disclosures ORDER BY rcept_dt DESC LIMIT 20"
    ).fetchall()
    if recent:
        st.dataframe(pd.DataFrame([dict(r) for r in recent]), use_container_width=True)
    else:
        st.info("공시 데이터가 없습니다.")

    conn.close()

# ─── Tab 5: 초기 설정 ───
with tab_setup:
    st.header("⚙️ 초기 데이터 수집")

    st.markdown("""
    ### 사용법
    1. 사이드바에 DART API Key를 입력하세요
    2. 아래 버튼으로 기업 목록을 먼저 수집하세요
    3. 그 다음 재무데이터를 수집하세요 (시간이 걸립니다)
    """)

    if not dart_key:
        st.warning("사이드바에 DART API Key를 입력하세요.")
    else:
        st.subheader("1단계: 기업 목록 수집")
        if st.button("📥 상장 기업 목록 수집", key="collect_corps"):
            with st.spinner("DART에서 기업 목록을 가져오는 중..."):
                client = DartClient(dart_key)
                corps = collect_kospi_companies_fast(client)
                st.success(f"✅ {len(corps)}개 상장 기업 등록 완료!")

        st.subheader("2단계: 특정 기업 재무데이터 수집")
        corp_search = st.text_input("기업 검색", key="setup_search", placeholder="삼성전자")
        if corp_search:
            found = db.search_companies(corp_search)
            if found:
                selected_corp = st.selectbox(
                    "기업 선택",
                    found,
                    format_func=lambda x: f"{x['corp_name']} ({x.get('stock_code', '')})",
                    key="setup_corp",
                )
                if st.button("📥 이 기업 재무데이터 수집"):
                    with st.spinner(f"{selected_corp['corp_name']} 데이터 수집 중..."):
                        client = DartClient(dart_key)
                        result = collect_financials(
                            client, selected_corp["corp_code"],
                            selected_corp["corp_name"], start_year=2024,
                        )
                        st.success(
                            f"✅ {result['collected']}건 수집 완료! "
                            f"(신규 항목: {result['new_items']}건)"
                        )

        st.subheader("3단계: 전체 KOSPI 재무데이터 수집 (대량)")
        st.warning("⚠️ 전체 수집은 DART API 호출 제한(일 10,000건)에 주의하세요. 수 시간 소요될 수 있습니다.")
        if st.button("📥 전체 KOSPI 재무데이터 수집", key="collect_all"):
            with st.spinner("전체 KOSPI 재무데이터 수집 중... (오래 걸릴 수 있습니다)"):
                client = DartClient(dart_key)
                result = collect_all_kospi_financials(client, start_year=2024)
                st.success(
                    f"✅ 수집 완료! "
                    f"기업: {result['companies']}개, "
                    f"데이터: {result['total_collected']}건, "
                    f"신규 항목: {result['total_new_items']}건, "
                    f"오류: {result['errors']}건"
                )
