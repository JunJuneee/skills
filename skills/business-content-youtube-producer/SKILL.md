---
name: business-content-youtube-producer
description: Plan or extend the "AI 산업·경제 뉴스 해설" YouTube track — a no-host channel that analyzes authoritative primary sources (a company's own report, an executive's talk, a research paper) about AI's effect on work, organizations, and the economy, always anchored in a concrete numeric reversal. Use when the user wants to pick a topic, write a title, or set the look/motion for THIS specific channel/track (not a different explainer channel) — e.g. "이 AI경제 채널에 새 편 기획해줘", "AgentOS 스타일로 오프닝 만들어줘", "이 리포트로 이 트랙 영상 만들어줘". For the shared how-to (research method, script timing math, storyboard, the render-engine pattern, verification) use `ai-content-youtube-producer` — load that skill for the mechanics and load this one only for what's specific to this channel's identity: its reference channel, title formulas, color system, and motion inspiration.
---

# Business/AI-Economy YouTube Track

This is a **channel bible**, not a how-to. Everything about *how* to research, script, storyboard, prototype, and verify an explainer episode already lives in `ai-content-youtube-producer` — load that skill first for the mechanics and come back here only for what makes *this* channel this channel.

This track was deliberately split off from the other active channel ("가격표 뒤에 있는 것", a faceless price-breakdown channel) after research showed macro/AI-tool-demo content flops in *that* channel's niche — but "AI's effect on work/organizations, argued from an authoritative primary source" tested as a different, working sub-genre worth its own track.

## Reference channel & what actually works in it

**AgentOS** (@ai-AgentOS, ~20k subscribers, "AI 에이전트 시대의 생존 가이드"). Sorting its own upload history by views: everything in the 20k–180k range is an analysis of a named authority or company's own primary material (a talk, an internal document, a study) reduced to one concrete number. AI-video-generation-tool demo/tutorial videos on the same channel sit at 1k–4k — the exact same pattern the price-breakdown channel's research found in an unrelated niche, which is why it's trusted here rather than treated as a coincidence. **Never pick an AI-tool-demo topic for this track.**

### Title formulas (extracted from AgentOS's actual titles)

1. [authority/company] did [thing] — [numeric reversal]
2. [company] analyzed [large dataset] and found — [counterintuitive result]
3. [named person]'s [format] — [one-line quotable claim]
4. A clean sample size + experiment result, stated as the whole title
5. [person] did [an unexpected thing]

Run a candidate topic through all five before committing to a title — the numeric-reversal formulas (#1, #2) are the ones that actually clustered at the top of the view distribution.

## Design tokens for this track

- Background `#0A0D14` (deep navy-black).
- Two-color semantic pair, **not** a single accent: `#33B0FF` electric blue = good news/growth, `#FF5C6C` warning red = bad news/decline. Chosen specifically to not collide with AgentOS's own orange or the other channel's amber — check your own reference channels' accents before reusing either of these verbatim on a third channel.
- Hand-drawn-style single-stroke line icons (see `ai-content-youtube-producer`'s stock-photo-substitute pattern) over a persistent top-left `SOURCE · <name>` watermark.
- Report-explainer pacing runs slower than a fast-cut channel: capture cuts (report cover, reviewer list, a "v1.0" version label, a survey methodology page) need **6–7s minimum**, not the ~4s average shot length that works for a faceless price-breakdown channel — confirmed against AgentOS's own actual cut lengths, not assumed. Don't force this track's pacing to match a different channel's rhythm just because both are "no-host explainer."

## Motion inspiration beyond the reference channel

AgentOS alone under-delivers on motion variety — an early draft built entirely from it drew the specific feedback "심심하다" (flat/boring). Three more channels, each contributing one distinct technique already generalized in `ai-content-youtube-producer`'s `references/design-and-motion.md`:

| Channel | What to borrow |
|---|---|
| Johnny Harris | Camera push-in / pull-back on a single static graphic — cinematic transitions between beats |
| Wendover Productions / Economics Explained | Count-up numbers; diverging 0-baseline "bar race" reveals |
| Half as Interesting | Dot/icon-grid pictograms for a share-of-total that's hard to feel as a bar |

When a key numeric reversal is the episode's single most important graphic, build the count-up, diverging-bar, dot-grid, *and* camera-push-in treatments of it as switchable variants in one file (per `ai-content-youtube-producer`'s side-by-side comparison pattern) rather than guessing which one lands best. Episode 1 used this for two separate decision points — a GDP three-stage reveal and the labor-vs-capital-share reversal (its single most important graphic) — each with its own switcher, left unresolved (switcher still live, no variant deleted yet) until the user picks a winner.

## Episode 1 (built)

**"AI가 자기 미래를 예측한 방식"** — an explainer of Anthropic's Econ Scenario Explorer v1.0. The numeric reversal the whole episode is built around: in the extreme scenario, GDP is **+32.4%** while knowledge-worker wages are **−11.5%**, and capital's share of income rises to **54.8%**. Script: ~9:37 runtime, 3,257 characters — use this as a real reference point for this track's own pacing (compare against the character-per-second math in `ai-content-youtube-producer`'s script stage, since a report-heavy script with long capture dwell times runs slightly different from that skill's general estimate).

**How to apply for the next episode**: pick a new primary source (a report, a talk, an internal dataset — not a tool demo), run the candidate title through the five formulas above, and reuse this file's color tokens and reference-channel motion list rather than re-deriving them. Channel name/branding is still unset — decide it before publishing, not before prototyping.

See `references/motion-graphics.md` for how the four episode-1 graphics (count-up, diverging bar, dot grid, camera push-in) were actually implemented and which one won.

Relies on: `ai-content-youtube-producer` (pipeline, script timing, storyboard cut types, the `render(t)` engine pattern, SVG-first rule, verification method).
