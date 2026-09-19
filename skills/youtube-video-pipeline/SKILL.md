---
name: youtube-video-pipeline
description: Plan and prototype a no-host, data/report-driven explainer YouTube video or channel end-to-end — reference-channel research, topic/niche strategy from viewcount data, verified-fact scriptwriting with duration math, storyboard/cut-sheet breakdown, a design token system, and a working HTML/JS motion-graphic prototype that is rigorously verified before handing off to ElevenLabs+Remotion production. Use this whenever the user wants to start a new YouTube channel or episode, write a script for one, storyboard or "cut" a video, design its visual look, prototype an opening or a chart animation, compare title/channel references, or asks to verify that a chart or motion graphic isn't buggy/awkward before rendering — even if they only say "이 리포트로 영상 만들어줘", "오프닝 만들어봐", "대본 써줘", "컷 시트 뽑아줘", or "이상하지 않은지 확인해줘", since each of those is one stage of this same pipeline. Do NOT use for the ElevenLabs TTS timing / Remotion render step itself — that is the separate market-note-shorts skill, which this skill hands off to at the end.
---

# YouTube Explainer Video Producer

A no-host, no-camera explainer video is built entirely out of narration + on-screen graphics (infographics, motion typography, screen captures, a little stock footage). Every stage below exists because a real project hit a real failure mode without it. Read the referenced file for a stage only when you're actually doing that stage — don't front-load all of them.

## The pipeline

1. **Reference research** → 2. **Topic/niche strategy** → 3. **Script** → 4. **Storyboard (cut sheet)** → 5. **Design system** → 6. **Motion-graphic prototype** → 7. **Verification** → 8. **Handoff to production**

Stages 1–2 are one-time per *channel*. Stages 3–7 repeat per *episode*. Never skip straight to stage 6 (building animated HTML) without a script — the cut timing, the on-screen text, and even the color semantics (what counts as "good news" vs "bad news" in this episode) all derive from the script's actual content and actual character count, not from vibes.

## 1. Reference research

Before designing anything, find 2–4 real YouTube channels in the target genre and actually watch them — don't guess at "what YouTube explainers look like" from training data, because the genre's visual conventions (dark vs. light backgrounds, how title cards work, where the source label sits) drift and vary by niche, and guessing produces the generic "AI slop" look.

For each reference channel:
- Open the channel's `/videos` tab, scroll to load 20–30 videos, and record title + view count + upload date + length for each. Sort by views to see what actually works vs. what flops in *this specific channel's* audience — don't assume a format that works for one niche (e.g. AI tool tutorials) works for another (e.g. AI economics analysis) just because both say "AI".
- Extract 3–5 **title formulas** as `[pattern] — [example]` pairs directly from real titles, not invented ones.
- Open 1–2 of the top-performing videos, scrub the video element to several timestamps (`video.currentTime = t`), and screenshot each. Note concretely: background color, where the source/watermark sits, how captions are styled, how much of the runtime is talking-head vs. B-roll vs. graphics, average shot length. Skip ads by clicking `.ytp-skip-ad-button` / `.ytp-ad-skip-button-modern`; if an ad won't skip, reload the page rather than fighting it.

If this research would take more than a couple of tool calls, delegate it to a fork or fresh agent so the raw scrolling/scrubbing/screenshot noise doesn't fill the main context — bring back only the distilled findings (title formulas, view distribution, concrete visual notes). See `references/research-and-strategy.md` for the fuller checklist and for how to survey a *second* reference channel with a different visual style (useful when the first reference alone feels flat — see the "add motion graphics" note in that file).

## 2. Topic / niche strategy

Don't pick a topic by intuition — classify the reference channels' recent videos into topic buckets and compare median view count per bucket. This session's actual finding across three unrelated channels: AI-tool-demo/tutorial content and pure macro/investment commentary both landed at the bottom of their own channel's own distribution, while "an authoritative primary source (a company's own report, a conference talk, an internal dataset) analyzed for a concrete numeric reversal" was consistently the top bucket — regardless of the specific niche. That pattern is worth checking for *your* topic before committing, but don't assume it's universal; verify it against the actual reference channels you researched.

Once a bucket is chosen, actively avoid every specific topic the reference channels have already covered (list them out) — a new channel competing head-on with a 200+ video incumbent on its own best topic loses by default. Full method and the "why an underdog niche can beat the top bucket" reasoning is in `references/research-and-strategy.md`.

## 3. Script

Two rules, both learned from getting them wrong:

**Only write numbers you can point to a source for.** When a fact comes from an interactive report/tool rather than a single static page, don't trust a text-summarization tool's paraphrase of it — the precise figures (exact percentages, sample sizes, dollar amounts) often live inside client-rendered charts that a text-only fetch never sees. Open the page in a real browser, scroll/click through every chart and tab, and read the numbers directly off the rendered SVG/DOM (`document.querySelectorAll('svg text')`, or just careful screenshots) before writing them into a script. Keep a running fact table of `{item, value, source, how confirmed}` as you go — this becomes the episode's fact-check appendix and the thing you cite when a graphic needs a caption.

**Duration is a real calculation, not a guess.** Narration runs at roughly **5.5–5.7 Korean characters per second** for a calm explainer voice. Count characters in the actual narration text (strip HTML/markup, strip whitespace) and divide — don't eyeball it. A first draft is very often 40–50% short of the target length; that's fine, it means you found the draft's actual length rather than assuming a target. Close the gap by adding *more verified content* (a deeper worked example, the names of who reviewed/built the source material, a related statistic from the same source, a caveat the source itself states) — never by padding with filler sentences, and never by writing the target runtime as if it were already achieved. Recompute the character count after every substantive edit and be honest with the user about the actual number, not the number you were aiming for.

Structure the script as timestamped blocks, each with: the narration text, and a one-line visual note (what type of graphic, referencing stage 4's type system). See `references/script-writing.md` for the block format and for what NOT to put on screen (methodology you didn't verify, a demographic generalization the source didn't make, an absolute claim the source itself hedges).

## 4. Storyboard (cut sheet)

Break the script into cuts, each tagged with one of four types:

| Type | Meaning |
|---|---|
| **I** infographic | A number, chart, or diagram is the point of the shot |
| **T** typography | A short phrase or quote, on its own, no chart |
| **C** capture | A screenshot of the actual source document/page/tweet, with a visible URL/date |
| **S** stock footage | Illustrative B-roll (or a hand-drawn line icon — see stage 5) |

**Derive every cut's duration from the actual script, proportionally, per section — never hand-pick absolute timestamps that you then hope sum correctly.** The reliable way: note each script section's real start/end time (from stage 3's character-count timing), assign each cut a *relative* weight within that section, then scale the weights so they sum to the section's real duration. Hand-picking cut timestamps directly reliably drifts — a few seconds of slack per section compounds across a dozen sections into a cut sheet that's a minute or more short of the real script, discovered only after the fact.

A report/data-heavy episode naturally runs a much longer average shot length (~8s) than a fast-cut lifestyle episode (~5s) — captures and multi-stage charts need dwell time to be read, not just seen. Don't force a fast-cut rhythm onto content that needs to be read.

Full type-budget guidance and the "same-type-three-in-a-row" rule (and its exception — see stage 6) are in `references/storyboard.md`.

## 5. Design system

Load the `artifact-design` skill before designing anything — it has the general craft guidance (token system, typography pairing, both-themes support) that applies here too. On top of that, this genre has specific patterns:

- Pick an accent color (or a two-color good/bad semantic pair) that doesn't collide with the reference channels you researched in stage 1 — if every existing channel in the niche uses the same accent hue, a new one reads as a copy, not an entry.
- A recurring **source watermark** (top-left, small mono caps, e.g. `SOURCE · <name>`) that's visible in every graphic cut builds more trust in a report-explainer than a channel logo does, because the claim being made is "look, here's exactly where this came from."
- When you're not sure a design direction lands, build 3–4 *real, side-by-side, switchable* variants of the same key moment rather than describing options in prose — a design decision about motion or color is much easier to make by toggling a tab than by reading a paragraph. `references/design-and-motion.md` has the tab-switcher pattern used for this.

## 6. Motion-graphic prototype

Build the actual moving preview in one self-contained HTML file per chunk of the episode (an opening, then the next section, etc. — one giant file for a 10-minute video gets unwieldy). This is a *prototype*, not the final render — its job is to nail down timing and look before anyone touches Remotion.

The single most important rule, learned from repeated bugs: **anything with a direction — an arrow, a line connecting two points, a trend line — must be built in SVG from the very first draft, never as a rotated/skewed CSS div.** CSS rotation tricks for arrowheads (`border-right + border-top, rotate(45deg)`) get the direction backwards or misaligned essentially every time they're tried, across multiple independent attempts in this project. SVG's `<line marker-end="url(#arrowhead)">` computes direction and position automatically from the line's own coordinates — use it from the start. Same for any line connecting more than two points: draw it as one continuous `<path>` with `stroke-dasharray`/`stroke-dashoffset` for a "drawing itself in" reveal, never as separate rotated segments that are supposed to meet at a joint (they visibly don't, at the pixel level, even when the underlying data is correct).

Second rule: **the render engine takes a single time value and computes the whole frame from it** — `render(t)` that shows/hides scenes and animates each one based on its own local progress `(t - cutStart)/(cutEnd - cutStart)`, rather than a chain of `setTimeout`s or per-cut re-renders. This is what makes it possible to scrub, to re-time everything later against real TTS timestamps without rewriting logic, and to verify precisely (stage 7).

Third: don't let on-screen big text and the caption/subtitle say the same full sentence — that reads as "just a wall of text," reported directly by feedback on an early draft. Split the labor: on-screen text carries 2–4 keywords or a short phrase; the caption bar carries the full sentence.

Fourth: if you're building several overlays that only apply to specific scenes (like variant-switcher buttons for three different key graphics), explicitly hide each overlay except when its scene is active. Don't assume "it's only visually near the right scene" is the same as "it's only shown during the right scene" — see stage 7 for how this exact mistake surfaced.

Full patterns (count-up numbers, diverging 0-baseline bars, dot-grid pictograms, camera push-in reveals, and the hand-drawn-line-icon substitute for stock photos — external image hosts are blocked by the Artifacts CSP, so real photos usually aren't an option there) are in `references/design-and-motion.md`.

## 7. Verification

**A screenshot at one moment is not verification of a chart.** A chart can look plausible in a still frame while (a) the numbers on screen are simply wrong, (b) two bars that should be proportional aren't, or (c) an element is fine on its own but silently overlapping another element that's only supposed to be visible in a different scene — none of which show up reliably in an eyeballed screenshot at normal size.

The method that actually catches these, in order of how often it's paid off:

1. **Expose a debug hook on `window`** — a `setT(t)` that jumps to an exact time (bypassing real-time playback drift) and a `getState()` that reads back the actual rendered DOM: text content of every label, `getBoundingClientRect().width` of every bar, count of every "lit" dot in a pictogram grid.
2. **Drive it from a real headless browser, not just visual inspection.** If Playwright's own browser tools aren't available in the session, a local Chromium binary is very likely already cached by Playwright (check `~/Library/Caches/ms-playwright/`) and can be driven directly with `puppeteer-core` (`npm install puppeteer-core` in a scratch directory, point `executablePath` at the cached binary). This has repeatedly been the fallback when the primary browser tool disconnected mid-session.
3. **Compute the expected value in the verification script itself** (e.g. `expectedRatio = 32.4/11.5`) **and diff it against the value read back from the DOM** — don't just print the DOM value and eyeball whether it looks right.
4. **Zoom in on small UI elements specifically.** A full-stage screenshot compresses small things like button labels or overlapping 12px text into a handful of pixels — a real bug (two absolutely-positioned overlays stacked at the same coordinates) was invisible at normal screenshot size and only became legible at 3–4× device-scale-factor on a cropped element.
5. **A debug hook that sets internal state directly is not the same as a real user interaction.** If a hook like `setVariant('B')` bypasses the click handler that also updates a button's visual "selected" state, a screenshot taken right after calling the hook will show correct content with a stale-looking button — that's a test-harness artifact, not a bug. Confirm with an actual `page.click()` before concluding either way.

Full checklist and the exact bugs this caught in practice (a label that never updated its text while its width animated correctly; three variant-switcher UIs rendering permanently stacked on top of each other) are in `references/verification.md` — read it before writing a verification script, since it saves re-deriving the same debug-hook pattern from scratch.

Always clean up scratch verification files (`node_modules`, screenshot PNGs, throwaway `.cjs` scripts, local dev servers you started) once a stage is confirmed working — they're not part of the deliverable.

## 8. Handoff to production

Once an episode's script and cuts are locked, the actual TTS + timing-alignment + Remotion render is handled by the **market-note-shorts** skill (built for vertical shorts, but its TTS/timing pipeline applies directly to horizontal long-form too — resolution and scene-count are the only real differences). Load that skill for the specifics; the short version:

- Generate ElevenLabs audio for the *entire* narration in one call, not sentence-by-sentence (unnatural seams otherwise), preferably via the `with-timestamps` endpoint (returns per-character alignment directly — faster and more reliable than running a separate transcription/alignment pass on the audio afterward).
- Real spoken audio reliably runs meaningfully longer than the character-count estimate from stage 3 (especially once numbers are spelled out phonetically for the TTS engine) — always re-derive final cut timing from the *measured* audio, never ship a render built on the estimate.
- Port the stage-6 prototype's `render(t)` logic into Remotion scene-by-scene rather than rewriting from scratch — the "one time value, everything derives locally" structure translates directly to `useCurrentFrame()`.
