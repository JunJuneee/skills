---
name: google-seo-blog-writer
description: Orchestrate a complete Korean Google SEO blog workflow by coordinating keyword-based post writing, card-news generation, and optional Google Blogger API publishing. Use when the user asks to create a complete Google blog post, make its cards, and/or publish the approved result.
---

# Google SEO Blog Orchestrator

Coordinate these independent skills in order. Treat each output as the input contract for the next skill.

1. Use `$google-seo-content-writer` with the keyword, user context, and requested angle.
2. Use `$google-seo-card-generator` with the approved post package.
3. Use `$google-blog-api-publisher` only when the user explicitly asks to create a Blogger draft or publish it.

## Post package

Keep one package containing `keyword`, `title`, `updated_at`, `body_markdown`, `body_html`, `labels`, `source_urls`, `card_briefs`, `card_paths`, target blog, mode (`draft` or `publish`), and any public image URLs.

Do not alter approved facts, title, or card copy while handing off. Ask only for a missing required value.

## Modes

- **Write only:** content writer only.
- **Write + cards:** content writer, then card generator.
- **Publish existing package:** publisher only after validation.
- **Full pipeline:** writing → cards → publishing. Default to a draft unless the user expressly requests public publication.

## Safety

- Live publication is consequential: require an explicit target blog and mode before publishing publicly.
- Never provide local image paths to Blogger. For an explicitly requested public post, automatically upload supplied local card images to the configured public image host (Cloudinary when `CLOUDINARY_URL` is available), then pass only the returned public HTTPS URLs. Do not pause for a separate image-host confirmation. If no configured host is available or upload fails, report that prerequisite instead of mutating Blogger.
- Report returned post URL, ID, and final state. If API access is unavailable, state the exact prerequisite rather than claiming a post was published.
