# Design system & motion-graphic prototyping

Load the `artifact-design` skill first for general craft (token system structure, typeface pairing, designing for both light/dark themes). This file covers what's specific to explainer-video motion graphics on top of that.

## Design tokens for this genre

- One accent color, or a deliberate two-color **good/bad semantic pair** when the episode's content is fundamentally a contrast (growth vs. decline, gain vs. loss). Pick colors that don't collide with your stage-1 reference channels' accents — if the whole niche uses the same orange, a new channel in the same hue reads as derivative.
- A persistent **source watermark**, small mono caps, typically top-left: `SOURCE · <name>`. This does real work in a report-explainer specifically — it's a constant, low-key credibility signal ("here's exactly where this number came from") that a channel logo alone doesn't provide.
- Reuse the same font pairing across every episode of a channel once it's chosen and approved — don't re-litigate typography per episode. Vary color/layout/motion instead when exploring a new look.

## Side-by-side variant comparison, not prose description

When a design or motion decision is genuinely open (which of several treatments for a key number/graphic looks best), build 3–4 *real, switchable* versions of that one moment rather than describing the options in words and asking the user to imagine them. A small tab UI (`A / B / C` buttons) overlaid on the preview, each button swapping which build-function renders the scene, lets the user toggle live and pick — this consistently produced better, faster decisions than a written comparison in this project.

Concrete motion techniques worth having ready (each grounded in a real, distinguishable reference-channel convention — see `research-and-strategy.md`):
- **Count-up numbers**: animate a number from 0 to its target with an eased curve; standard for data-explainer channels.
- **Diverging 0-baseline bars**: two bars growing in opposite directions from a shared zero-line — reuse this specifically for any "X went up while Y went down" beat, it's the clearest way to show a reversal without needing two separate charts.
- **100%-stacked bar / donut**: for a share-of-total that shifts across categories (e.g. labor share vs. capital share across three scenarios) — a 100%-stacked bar reads faster than a donut for this, but build both if it's the episode's single most important graphic and let the user pick.
- **Dot/icon-grid pictogram**: N-out-of-100 dots lit up, for "if this were 100 equal parts, this many changed" framing — good for percentages that are hard to feel as a raw bar (a 12-point shift is easy to miss as a bar-height difference, obvious as 12 lit dots vs. 32).
- **Camera push-in / pull-back**: start a static graphic zoomed in (only partially visible, cropped), then scale/translate out to reveal the full context — a cheap way to make a single static number feel less like a slide and more like a shot.

## Stock photo substitute: hand-drawn line icons

Many artifact/preview environments block loading images from external hosts (Pexels, Unsplash, etc.) via CSP, and even where allowed, licensed stock footage isn't something you can fetch and embed directly. Build a minimal single-color line-art SVG instead for each B-roll beat (a standing figure for "worker," a simple house/flag shape for "construction site," a headset-and-head shape for "call center"). Keep every icon in the same stroke-width, same stroke-color-from-palette, single-color style so they read as one consistent icon set rather than a grab-bag — this is closer to the actual "hand-drawn line icon" convention several real explainer channels use anyway, so it's not really a compromise.

## The render engine pattern

Build one `render(t)` function that takes a single absolute time value and:
1. Determines which "scene" (a set of DOM elements for one cut or one multi-cut composition) should be visible, and toggles an `.on` class (opacity 1) on that scene's container only, off (opacity 0) on all others.
2. For the active scene, computes a **local progress** `pr(t, cutStart, cutEnd) = clamp((t - cutStart)/(cutEnd - cutStart), 0, 1)` and drives every animated property (opacity, width, a count-up number's current value, a path's `stroke-dashoffset`) from that local progress, not from wall-clock elapsed time.

Wire a `<input type="range">` scrubber to call `render(scrubValue)` directly, plus a `requestAnimationFrame` loop that advances a `T` variable and calls `render(T)` when actually "playing." This single pattern is what makes scrubbing, precise verification (see `verification.md`), and later re-timing against real measured audio all straightforward — none of them work cleanly against a `setTimeout`-chained animation.

## The SVG-first rule for anything directional

**Build every arrow, connecting line, or multi-point trend line in SVG from the first draft.** This is not a stylistic preference — it's the single most repeated bug source in this kind of prototype:

- An arrowhead built from a rotated/skewed CSS div (`border-right + border-top; transform: rotate(45deg)`) gets the pointing direction backwards, or ends up floating disconnected from the line it's supposed to cap, essentially every time it's tried — across several independent attempts in one real project, never once correct on the first try.
- A multi-point line built as separate straight `<div>` segments, each individually rotated to the right angle and positioned to (hopefully) meet at a shared point, visibly fails to meet cleanly at the joint at the pixel level, even when the underlying numbers are correct — CSS transform math on separate boxes doesn't guarantee the geometric coincidence SVG gives you for free.

Instead:
```html
<svg viewBox="0 0 W H">
  <defs>
    <marker id="arrow" markerWidth="2.2" markerHeight="2.2" refX="1.9" refY="1.1" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,0 L2.2,1.1 L0,2.2 Z" fill="currentColor" />
    </marker>
  </defs>
  <line x1="…" y1="…" x2="…" y2="…" marker-end="url(#arrow)" stroke="currentColor" stroke-width="…" />
</svg>
```
Animate a growing arrow by moving `x2/y2` toward its target over the cut's local progress — `orient="auto"` on the marker keeps the arrowhead correctly oriented automatically, no manual angle math needed.

For a multi-point trend line, use one continuous `<path d="M x0,y0 L x1,y1 L x2,y2 …">`, get its real length via `path.getTotalLength()`, set `stroke-dasharray = length; stroke-dashoffset = length`, then animate `stroke-dashoffset` down to 0 over the reveal — this draws the *entire* line as one connected stroke, so there is no joint to misalign in the first place.

When placing an arrow or line between two on-screen elements, leave a visible gap before the destination element rather than running the line/arrowhead directly into it — arrows and lines that just barely reach an element's edge often visually merge with a label or icon sitting there.
