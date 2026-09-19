# The four candidate treatments for a numeric reversal

Built once as a standalone A/B/C/D comparison file for the episode-1 GDP-vs-wages reversal (`+32.4%` GDP, `−11.5%` wages), then reused as the pattern for every other key-graphic decision in the episode. Each variant's code below is the actual working implementation, not a description — copy the shape, not just the idea.

Shared setup: `var GOOD = 32.4, BAD = -11.5;` and the usual `pr(t,a,b)` / `outCubic(x)` local-progress helpers from `youtube-explainer-producer`'s render-engine pattern. A `showTab(t)` function toggles which `<div class="layer">` is `display:flex` vs `none` and resets `T = 0` on switch, so scrubbing one variant never leaves stale animation state bleeding into the next.

## A — Count-up

```js
var p1 = outCubic(pr(t,0.2,1.6));
el('cuA1').textContent = '+' + (GOOD*p1).toFixed(1) + '%';
var op2 = pr(t,2.0,2.3);                 // second number fades in only after the first settles
var p2 = outCubic(pr(t,2.0,3.4));
el('cuA2').style.opacity = op2;
el('cuA2').textContent = (BAD*p2).toFixed(1) + '%';
```
Both numbers are computed from the *live* progress value on every frame (`GOOD*p1`), never set once and left — this is what makes the final-frame text exactly match the target without a separate "snap to final value" step. Stagger the second number's start (`2.0`) well after the first's animation window closes (`1.6`) so they don't visually compete for attention at the same instant.

## B — Diverging bar (0-baseline)

```js
var maxV = 40, maxW = 34; // cqw — maxV is a *headroom* value, not the larger of the two data points
var wGood = (GOOD/maxV)*maxW*p1;
el('barGood').style.width = wGood+'cqw';
el('barGood').style.left = '50%';
var wBad = (Math.abs(BAD)/maxV)*maxW*p2;
el('barBad').style.width = wBad+'cqw';
el('barBad').style.left = (50-wBad)+'%';         // grows leftward from center, not from a fixed left edge
```
Pick `maxV` as a round number bigger than the larger magnitude (here 40, vs. the actual max of 32.4) so both bars have visible headroom rather than one pinned at the track's edge. Verify by measuring rendered `getBoundingClientRect().width` and checking the ratio against `GOOD/Math.abs(BAD)` (≈2.8) — this project's price-breakdown channel had already hit a bug where a diverging bar's height was hardcoded instead of computed from the value, so this ratio check is a standing requirement, not optional polish here.

## C — Dot-grid pictogram

```js
var GOOD_N = Math.round(GOOD);            // 32
var BAD_N = Math.round(Math.abs(BAD));    // 12
var nOn = Math.floor(GOOD_N * p1);        // reveal count-of-100 dots progressively, not all at once
goodDots.forEach(function(d,i){ d.style.background = i<nOn ? 'var(--v-good)' : 'var(--v-line)'; });
el('gLabel').textContent = nOn;           // the number label tracks the same nOn, never drifts from the dot count
```
Build all 100 cells once (`buildGrid`), never rebuild the grid per frame — only flip each cell's background based on its index against the current reveal count. Verifying this one is a pure DOM read: `document.querySelectorAll('.dot').filter(lit).length === Math.round(targetValue)` at the final frame, per `youtube-explainer-producer`'s verification method — don't trust that the code "looks like" it rounds correctly, count the actual lit elements.

## D — Camera push-in

```js
var scale = 3.4 - 2.4*p1;   // starts zoomed to 3.4x, eases down to 1.0x
el('pushWrap').style.transform = 'scale('+scale+') translateY('+((1-p1)*2)+'cqw)';
el('pushCap').style.opacity = pr(t,1.2,2.0);   // the caption/context label only appears once the zoom-out is mostly done
```
Put `overflow:hidden` on the outer layer — at `scale(3.4)` the content extends well past the frame, and without clipping it visibly overflows the stage during the first half-second. The caption text (what the big number actually means) stays hidden until the zoom-out has revealed enough context for it to make sense — showing it immediately, while still zoomed in, defeats the reveal.

## Two more switchers built the same way, in the actual episode

Beyond this standalone 4-variant demo, the episode itself needed two more graphic decisions, each following the identical switcher pattern (own tab UI, own `showTab`, own local render branches) rather than reusing this file directly:

- **GDP three-stage reveal** — A: a horizontal bar fills in per scenario in sequence (same visual grammar as the other channel's bars, for consistency across this producer's channels); B: three numbers count up simultaneously; C: each scenario enlarges in turn (camera-push-in family).
- **Labor-vs-capital-share reversal** — marked in the storyboard as *this episode's single most important graphic*, so it got three candidate treatments: A: a 100%-stacked bar across three scenarios; B: a pie/donut that splits differently per scenario; C: a 0-baseline diverging bar (same grammar as variant B above, reused for a different metric).

Neither of these two was resolved to a single final version as of the last working session — both switchers are still live in the prototype. Before shipping, pick one variant per switcher, delete the losing branches and the tab UI itself, and re-verify the survivor alone (a leftover switcher button is exactly the kind of small stacked-overlay element `youtube-explainer-producer`'s verification method warns about).
