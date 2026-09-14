# Market Note visual specification

## Canvas and alignment

- Canvas: 1080x1920, 30 fps, 9:16.
- Main horizontal margin: 54 px.
- Align every headline, card, and body block to the same 54 px guides as the progress bar.
- Do not enlarge the composition with `transform: scale(...)`; it breaks guide alignment.

## Instagram Reels and YouTube Shorts safe layout

- Preserve the standard Shorts composition and render a separate social-safe version when the user asks for Instagram or YouTube delivery.
- Keep the top 260 px and bottom 360 px free of essential text, cards, source lines, and progress indicators.
- Keep the social-safe content frame inside equal left and right margins of at least `84 px` on a 1080 px canvas. Do not create a visibly wider right-side gutter.
- Keep essential text inside approximately x=84…864. The lower-right action rail may contain the card background, but should contain no labels, values, body copy, or source text.
- In the lower-right action area, card background may extend when needed, but labels, values, body text, and other essential text must stay to its left. Reflow or left-align lower cards so the platform's like, comment, share, and remix controls never cover words or numbers.
- Hide the normal header, progress bar, section label, and footer source line in the social-safe version; platform overlays occupy those areas.
- Move and narrow the card stack with layout positioning. Never use global scale to force it into the safe area.
- Reflow or reduce the disclaimer body in the narrower safe frame so no Korean word splits across lines.

## Header

- Left: `YYYY.MM.DD · 미국 증시`.
- Right: `Market Note`.
- Header top: approximately 48 px.
- Progress bar top: approximately 99 px.
- Section label: `오늘의 미국 증시`.

## Palette

| Role | Color |
|---|---|
| Ink | `#112B45` |
| Blue | `#2E76A6` |
| Dark blue | `#155D82` |
| Muted | `#59758E` |
| Negative | `#E95B62` |
| Positive | `#20886A` |
| Background | pale blue-to-green gradient |
| Card | translucent white |

## Mobile typography

- Header: 32 px.
- Section label: 38 px.
- Headlines: 88-140 px.
- Card labels: 38-43 px.
- Primary values: 72-142 px.
- Body: 30-48 px.
- Footer: 23 px.

Use large type and fewer lines. If content does not fit at these sizes, reduce content before reducing type.

## Scene contract

| Scene | Required visual |
|---|---|
## Opening card doubles as the cover

The opening card is the video's cover on every platform, so it must state which session it
covers. Put the session date on it in `YYYY.MM.DD · 한국 증시` / `· 미국 증시` form, above the
headline, in the same eyebrow position the label line already occupies. Use the market
session date, not the render date; for U.S. closes that is the ET trading day.

Export that same frame as the cover file: `assets/thumbnail-{market}-market-close-YYYY-MM-DD.png`.
Instagram reels take frame 0 as the cover by default, which is this card — keep it that way
rather than passing a different `--thumb-offset`.

| Opening | Session date, large one-line market direction, and dark summary card |
| Indices | Three equal cards, grouped index narration |
| Russell | One dominant positive card with large green `+0.5%` and explanation |
| Key indicator | Minimal lead-in, usually `핵심은 소매판매` |
| Macro | Equal-height retail and Brent cards, then yield and interpretation |
| Movers | Cards ordered exactly as narration |
| Takeaway | One large conclusion phrase and one supporting card |
| Outlook | Monday and Tuesday schedule cards plus interpretation |
| Disclaimer | Same Market Note background, header, palette, and rounded card; static for 2 seconds |

## Disclaimer copy

```text
책임면책고시

본 자료는 작성 시점 기준의 정보와 분석을 바탕으로
제공되며 수익을 보장하거나 손실 회피를 약속하지 않습니다.
투자 결과에 대해 작성자 및 제공자는 법적 책임을 부담하지 않으며
모든 투자는 본인의 판단과 책임하에 진행하시기 바랍니다.
```
