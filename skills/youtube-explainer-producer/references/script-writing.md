# Script writing

## Fact-gathering: verify against the rendered page, not a summary of it

A text-extraction/summarization tool can paraphrase a page correctly in prose while still missing or garbling the *precise numbers*, especially when those numbers live inside client-side-rendered charts (SVG/canvas built by JavaScript after page load) rather than in the initial HTML. Before trusting a specific figure that will be spoken on screen:

1. Open the actual page in a real browser session.
2. If the page has tabs/toggles that change which numbers are displayed (e.g. "Modest / Substantial / Extreme" scenario buttons), click through *every* one and capture the numbers for each state — don't assume the default state is the only one that matters.
3. Read the numbers directly: `document.querySelectorAll('svg text, svg tspan')` for chart labels, or a careful full-page screenshot scrolled to the right section if the chart is canvas-based.
4. Keep a running fact table as you go: `{item, value, source/section, how confirmed}`. This becomes both the script's grounding and the "don't say this" checklist (see below) — anything you *couldn't* confirm this way goes on that checklist instead of into the script.

If an earlier summarization pass already gave you numbers, treat them as a hypothesis to re-confirm this way, not as ground truth — they are frequently right, but the failure mode when they're wrong is invisible until you actually check.

## What NOT to put on screen

Write this list explicitly (as its own script section, or a callout in the design doc) rather than trusting yourself to remember it while writing:
- Any methodology detail from a technical report you didn't actually read (only the interactive summary/explainer page) — attribute it as "the company's explanation," not as verified methodology.
- Any hedge or limitation the source itself states (e.g. "this model excludes policy responses") — include it, don't quietly drop it because it complicates the narrative.
- A specific demographic or occupational claim broader than what the source actually said (e.g. don't compress "coders and call-center agents" from an example into "knowledge workers are all X").
- Two data points computed from different, incompatible bases presented as if directly additive (a classic version: a platform's take-rate percentage that already includes delivery-fee revenue, added on top of a rider's separate per-delivery rate, double-counts the delivery fee). If you're not sure two numbers are on the same base, don't combine them in one graphic — say so explicitly instead, or present them in separate beats.

## Duration math

Korean narration for a calm/explainer voice runs at roughly **5.5–5.7 characters per second**, counting non-whitespace characters only (strip `<br>`/HTML tags and all whitespace before counting). To estimate a script's spoken length:

```
seconds ≈ (character_count_no_whitespace) / 5.7
```

Recompute this after every real edit to the narration — not once at the end. A first full draft is commonly 40–60% of a 10-minute target; that's a normal starting point, not a problem to hide. When you need to add length, add *content*, prioritized in this order:
1. A worked example that makes an already-cited fact concrete (if the source has one, e.g. a named case in the underlying report)
2. Named credibility for the source (who built it, who reviewed it, when it was published) — this is usually genuinely interesting and doubles as an authority signal for the title formula
3. A related, separately-confirmed statistic from the same source that adds a new angle rather than restating the headline number
4. An explicit caveat/limitation the source states — this is real content, not filler, and it's the kind of thing that makes an explainer feel trustworthy rather than credulous

Never pad with connective filler sentences that don't add information, and never write a runtime in a document (or say it out loud to the user) that hasn't actually been recomputed from the current draft's character count.

## Script block format

Write the script as a sequence of blocks, each with:
- A timecode range (computed by walking forward through the script cumulatively from each block's character count — see the storyboard doc for how this feeds cut timing)
- A short label for what the block is doing narratively (e.g. "훅 · 반전 제시", "검증한 사람들")
- The narration text itself, with the 2–4 numbers/phrases that should appear on screen wrapped in `<em>` or similar so they're easy to find later when building cuts
- One line naming the visual treatment: which cut-type (I/T/C/S — see storyboard doc) and roughly what's on screen

Keep the display-text version (normal notation: `32.4%`, `$44.4조`) and the eventual TTS-input version (numbers spelled out phonetically, e.g. `삼십이 점 사 퍼센트`) as two separate passes — write the display version first and confirmed, then do the phonetic pass only once the script itself is locked, since TTS phrasing changes the character count again (see the production-handoff stage — real ElevenLabs audio reliably comes out longer than the phonetic-text estimate, so don't over-optimize this pass by hand-tuning against the estimate).
