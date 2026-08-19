---
name: google-seo-card-generator
description: Create a 5–6 image Korean card-news set from an approved Google SEO post package, with Korean copy rendered directly inside AI-generated images and uniform 1254×1254 PNG output. Use when a post needs card images or when the user asks to create or revise Korean blog card news.
---

# Korean Google SEO Card Generator

Create cards only from the approved post package. Preserve approved facts, numbers, and units exactly. Do not write or publish the post.

## Deliverables

- Create five or six 1254×1254px square PNGs.
- Card 1 is a cover: `topic + most important conclusion or question` in large text.
- Cards 2 onward have distinct roles—fact, comparison, route, preparation, effect, or checklist—and do not repeat the cover.
- Save `/Users/jun/Desktop/github/ai_images/blog/<topic>/<topic>_카드_01.png` onward unless another path is supplied. Create the topic directory when needed. Verify dimensions and inspect the full set together.

## Type and overlays

- Include the approved Korean title, numbers, and descriptions directly in every image-generation prompt by default. Ask the image generator to render the text verbatim, then inspect every character and regenerate any card with incorrect or garbled text. Do not add a Python overlay afterward unless the user explicitly asks for deterministic text correction.
- Default to Apple SD Gothic Neo; use Pretendard or Noto Sans KR only if unavailable.
- Use 800 for headings, 800–900 for key figures, 600–650 for body, 500–600 for captions. Do not mix typefaces within a card.
- For a rounded box, label, or speech bubble, calculate actual glyph bounds and center them horizontally and vertically. Maintain visually equal top, bottom, left, and right padding; do not bias text to an edge.

## Visual system

- Keep palette, frame thickness, margins, corner radius, type hierarchy, and icon style consistent across the set.
- Select layouts by information: visual-first, conclusion-first, comparison, or flow/diagram. Never reuse a top-title-plus-bottom-image layout by default.
- Keep titles within three lines and supporting text within two. The main fact, conclusion, or relevant image must be first-read and largest.
- For travel, regional, and culture topics, use muted colors and symbolic/simple illustrations. Do not present invented landmarks as factual places.

## Generation and QA

- Image-generation prompts must include `square 1:1 canvas`, `same design system across the full card set`, and `no extra unrequested text, logo, watermark, page number`.
- Resize only square source images to 1254×1254; never stretch or crop non-square sources.
- Before delivery, verify frame consistency, card relevance, box-text centering, readable copy, correct values/units, no unintended or garbled text, and 1254×1254 dimensions.
