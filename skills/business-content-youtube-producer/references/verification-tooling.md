# `verify_render.cjs` — the automated check built for this channel, and the real bug it caught

`youtube-video-pipeline` says "verify before handing off to production." This is the actual script written for that step on this channel, why each of its three checks exists, and the one real bug it found that manual screenshot review had already missed twice.

## Why screenshots weren't enough

Every bug the viewer actually reported (1:36 arrow flicker, 2:30/2:46/3:10 chart misalignment) was the kind that only exists for a handful of frames inside a continuous animation — spot-checking timestamps a human picks by eye reliably misses a problem that lives at, say, t=95.7s–95.9s. The fix was to stop looking at frames and instead sweep `render(t)` numerically across the whole timeline in a headless browser and assert invariants at every sampled instant.

## Setup

Load the render engine's `final_render.html` in Puppeteer (or the Playwright-Chromium fallback — see `youtube-video-pipeline` for the exact binary path when the extension/MCP tools are disconnected), call `window.renderAt(t)` in a loop, and read back computed styles via `page.evaluate`. No visual diffing, no screenshots needed for this pass — just numbers.

## Check 1 — opacity discontinuity sweep

Sample every `#stage [id]` element's computed `opacity` every 0.03s. Flag any jump greater than 0.35 between consecutive samples — **but only when the element's closest `.sc` (scene) ancestor was `.on` (visible) at both the previous and the current sample.**

```js
for (const el of allTrackedEls) {
  const scene = el.closest('.sc');
  if (!scene || !scene.classList.contains('on')) continue;      // guard added after v1's false positives
  const prevOp = prevOpacities.get(el.id);
  const curOp = getComputedStyle(el).opacity;
  if (prevOp != null && Math.abs(curOp - prevOp) > 0.35) flag(el.id, t, prevOp, curOp);
  prevOpacities.set(el.id, curOp);
}
```
**The guard exists because of a real false-positive run**: the first version of this check (no guard) reported 16 flagged jumps. All 16 turned out to be child elements that simply retained whatever opacity they'd last been set to while their *parent scene* was hidden (`display:none` or `.sc` without `.on`) — a completely harmless, invisible state change, not a flicker. Requiring the ancestor scene to be visible at *both* samples eliminated all 16 false positives while preserving sensitivity to real ones.

**The real bug this then caught**: with the guard in place, one genuine flag remained — the cut7→cut8 bar-chart repurposing (see `svg-first-lessons.md` #5) instantly snapping a bar from a single "1,990" value to an empty "0/+0" two-bar layout. This was the actual bug behind a flicker the viewer hadn't even reported yet for that specific spot; fixed with the sin-based dip-and-recover curve, then re-verified by re-running this exact check until it reported zero flags end to end.

## Check 2 — marker/length correlation (the "floating arrowhead" class)

For every `<line marker-end="...">` element, at every sampled instant, flag it when `opacity > 0.05 && lineLength < 0.3` (in the SVG's own coordinate units) — an arrowhead visible with essentially no shaft behind it.

```js
const len = Math.hypot(line.x2.baseVal.value - line.x1.baseVal.value, line.y2.baseVal.value - line.y1.baseVal.value);
if (parseFloat(getComputedStyle(line).opacity) > 0.05 && len < 0.3) flag(line.id, t);
```
This directly targets the bug in `svg-first-lessons.md` #2 — it's a generic check that would catch that entire bug class on any future episode's arrow diagram, not just the specific one that was manually found this time.

## Check 3 — shared-baseline check

For any group of elements meant to share a visual baseline (a bar chart's bars, a bar chart's category labels), configure a `BASELINE_GROUPS` entry: a CSS selector, and the render-time `t` at which the group should be fully revealed.

```js
const BASELINE_GROUPS = [
  { name: 'delivery-fee-bars', selector: '.barcol .bar', atTime: 42.5, tolerancePx: 1 },
  { name: 'tier-labels', selector: '.tier .tlbl', atTime: 118.0, tolerancePx: 1 },
];
```
At `atTime`, call `renderAt(atTime)`, then read `getBoundingClientRect().bottom` for every element matched by `selector`, and flag the group if `max(bottoms) - min(bottoms) > tolerancePx`. This is the check that would have caught the 2:30/2:46/3:10 misaligned-chart reports directly, and it's also what caught the `.tier .tlbl` uneven-label-wrapping bug (fixed with `min-height:3.9cqw` so a two-line label doesn't push its own bar's baseline down relative to a neighboring one-line label).

## Running order

Run all three checks across the full timeline in one pass (one `for t of samples` loop calling all three per-sample checks) rather than three separate passes — it's the same render calls, and a single combined report is easier to read against the timeline than three files. Treat **any** flag as a blocker before re-encoding the final MP4 — every flag found so far has corresponded to a real, visible defect, zero false positives once the Check-1 guard was added.
