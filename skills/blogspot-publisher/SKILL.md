---
name: blogspot-publisher
description: Format and publish Korean Blogger/Blogspot posts with supplied text and images, including card-news placement, reliable image delivery, schedule-series internal links, and post-publication URL/hashtag handoff. Use when the user asks to post, publish, upload, or revise an article on the configured Blogspot blog.
---

# Blogspot Publisher

Publish polished Korean posts to the configured Blogger site through the local `mcp-blogspot-posting` server. When the user supplies a complete manuscript and its card-news images, publish it publicly by default without asking a follow-up confirmation; ask only when the user requests a draft, a review, or a non-public outcome. Do not independently browse claims unless the user explicitly asks for verification. Do not create or insert CTA images. Add an outbound CTA button only when the user explicitly requests one and supplies or approves its destination URL.

## Workflow

1. Preserve the user's title, facts, tone, and section order. Do not fact-check or alter facts unless the user asks for verification or revision.
2. Use every supplied card-news image. Place cards immediately after the most relevant section; place card 01 after the introduction and distribute the remainder across the body. If the user supplies additional images such as event leaflets, optimize and insert them in the relevant section without visible captions.
   - For 홈쇼핑 시간대 편성표 posts, if a cover image (`표지` or `cover`) is supplied, place it as the first body element immediately below the title, before the introduction and table of contents. Apply the dedicated representative-product placement rule in step 6 instead of distributing representative-product images across the body.
3. Optimize supplied images to JPEG, normally 850 px wide and quality 55, matching the established layout at `https://betterpickguide.blogspot.com/2026/08/8-1-8.html`. Use every supplied card.
   - For Blogspot posts, never embed publishing images as `data:image/...` Base64 URLs. Social-preview crawlers do not reliably recognize them. When `CLOUDINARY_URL` is configured, upload every supplied body image to Cloudinary through its API and use the returned public `https://res.cloudinary.com/...` URL in the post HTML.
   - Keep the first body image (the social-preview representative image) at a 1200×630 / 1.91:1 landscape ratio so link previews use the compact thumbnail layout. When preserving a non-landscape original in Cloudinary, use `c_pad,b_white,w_1200,h_630,f_jpg,q_auto` rather than cropping important card text or subjects.
   - Do not pass large Base64 HTML through terminal stdout/stderr or another text-output buffer before calling the publishing API. That transport can truncate image data.
   - Build the HTML and Base64 payload in the publisher process, or use a publisher input that reads the local HTML/image files directly.
   - Before publishing, count the expected card `<img>` elements and their unique Korean `alt` text. After publishing, confirm the returned/stored HTML has the same count. If any image is missing, stop and fix the payload before reporting success.
   - Do not silently omit cards to reduce payload size. If the payload is too large, reduce every card to about 700 px / quality 45 and repeat the count check.
4. Build responsive HTML:
   - Introductory paragraphs
   - First card image
   - Table of Contents with working section anchors when practical
   - Readable headings, lists, responsive tables, FAQ, summary, references, and disclaimer
   - Do not invent or add outbound buttons such as `현재 편성표 자세히 보기`, `실시간 확인`, `최신 정보 보기`, or `바로 확인`. Add a button only when the user explicitly requests one and supplies or approves its destination URL.
   - Additional official links in the relevant section and references
   - No visible image descriptions, captions, source lines, `figcaption`, or placeholder image text
5. Add a real internal-link section titled `함께 보면 좋은 글`. Select 3–4 genuinely relevant already-published posts from `references/published-posts.md`, insert their actual title and URL in the body, and never invent a link. If fewer than three are genuinely relevant, insert every relevant post available.
   - For recurring 홈쇼핑 시간대 편성표 posts, always insert the immediately previous time-slot post as the first internal link (for example, the 9시 post links to the same date's 8시 post). This link is mandatory even when other recommendations are also added.
   - Use the layout of `https://betterpickguide.blogspot.com/2026/08/8-1-8.html` as the baseline for these posts, while retaining every supplied product link as a normal text link in the tables.
   - For 홈쇼핑 시간대 편성표 posts, under `## <시간>시 홈쇼핑 대표상품 편성표`, place the exact introductory sentence `대표상품은 해당 방송에서 중심으로 소개되는 구성입니다.`
   - Immediately after that sentence, insert every supplied representative-product image as one continuous image group before the representative-product table. Do not split those images across individual product sections or elsewhere in the body. Images that are specifically for other sections (such as a schedule overview, checklist, or FAQ) may remain in their matching sections.
6. Publish with `isDraft:false` when the user asks to post or supplies a complete manuscript with its card-news images, unless the user explicitly requests a draft, review, or non-public result. Prefer the configured local MCP; if unavailable, use the existing Blogger OAuth credentials and Blogger API fallback without exposing credentials.
7. Verify image integrity for every image-containing post before handoff. Compare the expected card count and unique `alt` text in the publishing payload with the stored post HTML. If direct stored-content inspection is unavailable, verify the public URL with `curl`.
   - For posts with images, also confirm the public page exposes `og:image` as a public HTTPS URL, not a `data:` URI. Do not report completion until this check passes.
   - Also confirm the final public `og:image` resolves to 1200×630 before handoff, unless the user explicitly requests another social-preview format.
   Only when the user explicitly asks to verify the full public page, additionally verify:
   - Expected count of embedded images
   - Table of Contents
   - Official URI/button
   - Key title or heading text
8. After publication succeeds, append the exact post title, public URL, and actual hashtags to `references/published-posts.md`.
9. Return the public post link. Then return exactly the internal posts inserted into the body as copy-friendly, separate three-line blocks — never a Markdown table:
    ```text
    타이틀: <title>
    URL: <full unbroken URL>
    해시태그: <hashtags>
    ```
    Leave a blank line between entries so each URL can be copied intact.
    - Return the same posts that were actually inserted into `함께 보면 좋은 글`.
    - Do not invent titles, URLs, or hashtags. If fewer than three relevant entries exist, return every relevant entry available.
    - Exclude the newly published post unless the user specifically asks to include it.
    - Include a verification checklist only when verification was requested.

## Local configuration

- MCP project: `/Users/jun/Desktop/skills/mcp-blogspot-posting`
- Server entry: `dist/src/server.js`
- Blog URL: `https://betterpickguide.blogspot.com`
- OAuth client: `/Users/jun/Downloads/client_secret.json`

Do not print tokens, credentials, or client-secret contents. Reuse the existing OAuth token.

## Quality rules

- Use the user's supplied data as-is by default. Check or correct it only when the user asks for verification.
- Do not publish placeholder text such as “표를 삽입하세요.”
- Preserve official links supplied in the manuscript as normal text links. Do not convert them into buttons unless the user explicitly requests it.
- For time-sensitive schedules or listings, do not add a `현재 편성표`, `실시간 확인`, or similar button merely because an official page exists.
- Make wide tables horizontally scrollable on mobile.
- Use cautious language for proposals, forecasts, pending rulings, changing schedules, and unverified operational details.
- Never claim publication succeeded until the MCP returns a public URL. Do not imply public-page verification unless it was requested and completed.

## File operations

Use `apply_patch` for temporary HTML or publisher scripts. Use `sips` for image optimization. Keep temporary publishing artifacts under `/private/tmp`.
