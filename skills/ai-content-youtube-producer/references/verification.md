# Verifying a motion-graphic prototype

A still screenshot at one arbitrary moment tells you almost nothing reliable about whether a chart is correct — it can look plausible while the underlying numbers, ratios, or scene-switching logic are actually wrong. Verification needs to (a) hit an *exact* known time, and (b) check the *actual rendered values*, not just how it looks.

## The debug-hook pattern

Add a small object to `window` in the prototype itself (safe to leave in — it doesn't affect normal playback):

```js
window.__debug = {
  setT: function(t){ playing = false; T = t; render(T); },
  getState: function(){
    return {
      someLabel: document.getElementById('someLabel').textContent,
      barWidth: document.getElementById('someBar').getBoundingClientRect().width,
      litDots: [...document.querySelectorAll('.dot')].filter(d => d.style.background === 'var(--accent)').length
    };
  }
};
```

`setT` bypasses real-time playback entirely, so a verification script can land on the *exact* frame it wants instead of hoping a `setTimeout`/wait lands close enough — this matters a lot once a prototype has several minutes of runtime, since real-time drift between puppeteer round-trips can otherwise land you in a different scene than intended without any error being raised.

## Driving it headlessly

If the session's own browser-automation tool isn't available (disconnected mid-session, or not installed), check whether Playwright's own Chromium is already cached locally — it very likely is if Playwright has been used at all in this environment:

```bash
find ~/Library/Caches/ms-playwright -maxdepth 2 -iname "*chrome*"
```

Then drive it directly with `puppeteer-core` (works with any Chromium-family binary, doesn't need its own bundled browser download):

```bash
mkdir -p /tmp/verify-scratch && cd /tmp/verify-scratch
npm init -y >/dev/null 2>&1 && npm install puppeteer-core@23 --no-save >/dev/null 2>&1
```

```js
const puppeteer = require('puppeteer-core');
const browser = await puppeteer.launch({
  executablePath: '/Users/…/ms-playwright/chromium-XXXX/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
  headless: 'new', args: ['--no-sandbox']
});
const page = await browser.newPage();
await page.setViewport({ width: 956, height: 538 });
await page.goto('http://127.0.0.1:PORT/preview.html?v=' + Date.now(), { waitUntil: 'networkidle0' });
await page.evaluate((t) => window.__debug.setT(t), 147.9);
const state = await page.evaluate(() => window.__debug.getState());
```

Serve the file with a plain local HTTP server (`python3 -m http.server`) rather than opening it as `file://` — some browser automation tools refuse `file://` navigation. Note: an artifact-format HTML file (with no `<!doctype>`/`<html>`/`<head>`/`<body>`) needs those wrapped around it for a standalone local preview to render correctly outside the Artifact host.

## What to actually assert

Don't just print the DOM state and eyeball it — compute what it *should* be and diff:

```js
const expectedRatio = 32.4 / 11.5;
const actualRatio = state.barGoodWidth / state.barBadWidth;
console.log(Math.abs(actualRatio - expectedRatio) < 0.01 ? 'PASS' : 'FAIL', actualRatio, expectedRatio);
```

Things worth checking this way for every chart before considering it done:
- Every label's **text** matches its target value exactly at the cut's final frame (not just that *some* number is showing).
- Every bar/segment's **rendered pixel width** is proportional to its data value — recompute the expected ratio from the actual numbers and compare, don't trust that "the code looks right" is the same as "the pixels are right."
- A 100%-stacked bar's segments actually sum to the full track width at every row (catches a common off-by-something in how segments are positioned).
- A dot-grid's lit-dot **count** matches `Math.round(value)`, read by filtering the actual DOM elements — not asserted from the code that set them.

## Bugs this method actually caught (so you know what to look for)

- **A label frozen at its placeholder value.** A bar's *width* animated correctly to the right proportion, but its *text* label was never updated past its initial `"+0.0%"` placeholder — easy to miss visually because the bar itself looked completely correct. Caught by reading `textContent` at the final frame and diffing against the target number, not by looking at the bar.
- **Multiple overlay UIs permanently stacked on top of each other.** Three variant-switcher button groups (for three different scenes) were each absolutely-positioned at the same screen coordinate, with no logic hiding the ones that didn't belong to the currently-active scene — so all three rendered simultaneously, overlapping, at every moment in the video. In a normal full-stage screenshot this just looked like slightly-odd anti-aliasing on a button; only a 3–4× device-scale-factor screenshot cropped tightly to just that button revealed it was actually two glyphs blended on top of each other. **Lesson: zoom in on small interactive elements specifically — don't rely on full-frame screenshots to catch small-element overlap.**
- **A debug-hook check that looked "wrong" but wasn't a real bug.** Calling `window.__debug.setVariant('B')` directly changes internal state and re-renders the chart correctly, but does *not* trigger the click handler that updates a button's `.selected`/highlighted visual class (that logic lives on the real click listener, not on the state setter). A screenshot taken right after calling the hook showed the *correct* chart with a *stale-looking* button highlight — which is a limitation of the test harness, not a shippable bug. Confirmed by simulating an actual `page.click()` on the button and re-checking, which showed the highlight update correctly. When something looks inconsistent in a hook-driven screenshot, reproduce it with a real interaction before concluding it's a bug.

## Cleanup

Verification is scratch work, not a deliverable — remove the local `node_modules`/`package.json` install, kill any local HTTP server you started (`pkill -f "http.server <port>"`), and delete throwaway screenshots and `.cjs` scripts once a stage is confirmed. Keep only the actual prototype file and, if it's genuinely reusable across episodes, the verification script itself.
