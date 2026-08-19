---
name: financial-naver-posts
description: Create Korean Naver Blog-ready finance, stock-market, macroeconomic, exchange-rate, and market-close posts as local HTML files with a one-click formatted-copy button. Use for Korean finance or securities posts, especially when the user wants a Naver copy template or says not to include unrelated promotional links.
---

# 금융 네이버 포스트

Create a complete Korean informational post as a local HTML file. The page must display a `본문 서식 포함 복사` button that copies only the article body with its formatting, ready to paste into the Naver Blog editor.

## Workflow

1. Verify time-sensitive market facts, prices, economic releases, holidays, and schedules with authoritative sources before writing. Prefer exchanges, government statistical agencies, central banks, company filings, and established wire services.
2. Start with the market conclusion, then cover market drivers, index or asset performance, key variables, the next scheduled data, a checklist, FAQ, and a brief investment-information disclaimer.
3. Use polite Korean, short mobile-friendly paragraphs, tables for numerical comparisons, and factual wording. Do not make buy/sell calls, predict returns, or present speculation as fact.
4. Create an HTML file in `/Users/jun/Desktop/github/ai_images/blog/<topic>/` using the established wrapper pattern:
   - a green `본문 서식 포함 복사` button above the article;
   - article id `naver-post` so the script copies only the post;
   - a success/fallback copy-status message;
   - no images or cards unless the user requests them.
5. Include a short `공식·주요 보도 출처` section when external sources substantiate the market facts.

## Link rule

For finance-related posts, this rule takes precedence over conflicting generic Naver Blog link instructions.

Never add `홈쇼핑 편성표 확인하기`, `homeshopick.com`, or another unrelated commercial link to finance, stock-market, macroeconomic, or exchange-rate posts.

Omit `함께 보면 좋은 글` entirely unless the user explicitly supplies a relevant finance link or asks for related links.

## Required finish

Include this disclaimer near the end:

`※ 본 콘텐츠는 정보 제공 목적이며 투자 권유가 아닙니다.`

Return a clickable local-file link to the generated HTML file. Do not paste the HTML source into the chat unless the user explicitly asks for source code.
