# The concrete bugs behind "anything with a direction must be SVG"

`youtube-video-pipeline` states the rule abstractly. This is the channel where every one of these was actually hit, with the actual fix — copy the fix pattern, not just the warning.

## 1. CSS-rotated arrowheads get the direction wrong

A two-way "money flows from consumer and from merchant into the platform" diagram was first built with a div `line` plus a `::after` pseudo-element rotated 45° (`border-right + border-top, rotate(45deg)`) for the arrowhead. Screenshotting it mid-animation showed the arrowhead pointing the *wrong direction* on one side. This wasn't a one-off typo — the same trick, tried again on a second diagram (a "→ blackbox →" flow) and a third (a rising/falling percentage line), got the direction or position wrong every time it was attempted fresh.

**Fix**: `<line marker-end="url(#arrow)">` with the marker defined once and reused. The marker orients itself from the line's own `(x1,y1)→(x2,y2)` vector — there is no direction to get wrong, because there's nothing to compute by hand.

```html
<marker id="mArrow" markerWidth="2.4" markerHeight="2.4" refX="2.1" refY="1.2" orient="auto" markerUnits="userSpaceOnUse">
  <path d="M0,0 L2.4,1.2 L0,2.4 Z" fill="#E9A13B" />
</marker>
<line id="lnL" x1="10" y1="15" x2="10" y2="15" stroke="#E9A13B" stroke-width="0.45" marker-end="url(#mArrow)" />
```
Animate only `x2` (or `y2`) per frame — the marker's angle and tip position update automatically as the line grows.

## 2. A growing arrow's *marker* must never be opaque while its *length* is ~0

Fixing the direction above didn't fully fix the diagram: the receiving node's circle and the arrow's marker both faded in on independent timers, and for a few frames the arrowhead was fully opaque while the line itself had zero length — a lone triangle floating with no visible shaft, reported by the viewer as "왜 깨지는거야" before the exact cause was known. Screenshotting a few widely-spaced timestamps missed it; only sampling every ~0.1s of the transition and printing `{opacity, x2-x1}` side by side made the mismatch obvious.

**Fix**: tie the marker's opacity to the *same* eased progress value that drives the line's length — never a separate, independently-timed fade.
```js
var pr2 = outCubic(pr(p, 0.28, 0.85));   // one progress value
lnR.setAttribute('x2', 50 - pr2*15.5);   // drives length
lnR.setAttribute('opacity', pr2);        // and opacity — same variable, never out of sync
```
Also sequence entrance order: let the node itself finish fading in first (`pr(p, 0, 0.22)`), *then* start the arrow's growth (`pr(p, 0.28, 0.85)`) — starting both from the same instant made the node still look "half there" while an arrow was already reaching for it.

## 3. A point on a chart is not automatically drawn *at* its own coordinate

A line-chart's dot markers were built as `<div class="lcpt">` flex columns containing a value label, a dot, and a date label stacked in that order, with the *container's* `left`/`bottom` set to the intended data point. The dot visually sat noticeably above the line, because the label sitting above it in the flex flow pushed the container's effective visual center away from its own anchor coordinate — the anchor was correct, but nothing in the layout actually placed the dot *there*.

**Fix**: make the dot itself the zero-size anchor, and position every decoration (value label, date label) as an absolutely-positioned sibling offset from that same anchor via `transform`, never via normal document flow:
```css
.lcpt { position:absolute; width:0; height:0; }         /* pure anchor, no box */
.lcpt .dot { position:absolute; left:0; bottom:0; width:1.4cqw; height:1.4cqw; border-radius:50%; transform:translate(-50%,50%); }
.lcpt .val { position:absolute; left:0; bottom:2.6cqw; transform:translateX(-50%); }
```
The same bug, same fix, showed up again on a second chart (a "rate down / fee up" comparison) where a percentage label was hardcoded 4 units away from where its own line actually ended — always derive a label's position from the same coordinate that drew the geometry, never a separately hand-tuned number.

## 4. A persistent multi-cut scene must not re-fade at every internal cut boundary

Several graphics (a receipt, a two-node arrow diagram, a bar chart) stay on screen across more than one narration cut, revealing progressively — cut A shows step 1, cut B (same scene, different narration) reveals step 2, etc. The outer container's fade-in/fade-out was originally computed from *the current cut's own* start/end, which meant it silently replayed a fresh fade-in every time the cut number ticked over *inside* an already-visible scene — a flicker at 1:36 the viewer caught immediately but that no single spot-checked screenshot showed (opacity briefly dipping to ~0.1 for 0.1–0.2s is invisible unless you're looking at exactly that instant).

**Fix**: precompute the *display window of the whole contiguous run* of cuts sharing one scene (first cut's start → last cut's effective end), and fade the outer container only against that window; drive each cut's own internal reveal (a bar's height, a node's opacity) from that cut's own local progress as before. A generic sweep that samples every element's opacity every ~0.03s and flags any jump bigger than one legitimate fade step (while both frames' scene container was actually visible) catches this whole bug class before it ever reaches a full render — see `references/verification-tooling.md`.

## 5. Repurposing the same DOM element between two different meanings needs its own transition, not an instant swap

A chart element (`bA`, one bar) was reused between cut 7 (a single absolute-value bar: "배달비 1,990원") and cut 8 (one of two diverging comparison bars: "−1,010" vs "+2,990") — same div, completely different meaning and position. Swapping instantly reset the whole chart to an empty "0 / +0" frame for one visible instant, confirmed on screenshot, before the new bars grew in.

**Fix**: a short symmetric dip (`opacity = 1 - 0.85*sin(π·p)` over the repurposing window) that is worth exactly 1 at both p=0 and p=1 — it starts and ends at the *same value the neighbouring frames already have*, so there's no jump at either edge, only a deliberate quick dim-and-recover in between that reads as an intentional beat rather than a glitch. Verified by re-running the opacity-discontinuity sweep until it reported zero jumps across this exact boundary.
