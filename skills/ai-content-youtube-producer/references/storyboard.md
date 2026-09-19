# Storyboard / cut sheet

## The four cut types

| Type | Meaning | Typical duration |
|---|---|---|
| **I** infographic | A number, chart, or diagram is the point of the shot | 4–8s, more for multi-stage builds |
| **T** typography | A short phrase/quote alone, no chart | 3–5s |
| **C** capture | Screenshot of the real source (doc/page/tweet/report cover), with a visible URL/date | 5–7s — needs dwell time to actually read |
| **S** stock footage | Illustrative B-roll, or a hand-drawn line-icon substitute (see `design-and-motion.md`) | 4–6s |

Track the running I/T/C/S percentage split as you build the cut sheet. A report-explainer will naturally skew heavy on I (~50–60%) because the numbers *are* the content; that's fine and expected, don't force it toward some "ideal" generic split — but do sanity-check against your stage-1 research (what split did the actual reference channel use?).

## The "same type three-in-a-row" rule — and its real exception

Three consecutive cuts of the same *rendered look* (e.g. three plain text cards on a blank background, one after another) reads as monotonous and was a real piece of user feedback on an early draft ("너무 줄글만 있는 게 아닌가"). But the rule is about *visual sameness*, not the type label: three consecutive **I** cuts that are three different *stages of the same graphic building up* (a bar chart's three bars appearing one at a time, each getting its own beat) are not the same failure — they're a single coherent reveal, and forcing a different cut type in between would break the reveal for no benefit. When counting toward the "no three in a row" rule, collapse sequential stages of one composition into a single logical cut first, then check the *remaining* sequence for real repetition.

Two concrete fixes that came out of catching this rule violated in practice:
- Don't let a screen's big text repeat the same full sentence as the caption/subtitle bar below it — split so the on-screen text is 2–4 keywords and the caption carries the full narration sentence. (This alone often turns three "identical-looking" text cards into three visually distinct ones just by shortening what's on screen and letting a different visual motif — a stamp, a diagram, an icon — carry the rest.)
- Add a small "pinned" element (a shrunk-down version of the previous beat's key number, docked to a corner) that persists across a run of otherwise-plain cuts, so the screen is never *fully* blank-background-plus-text for more than one beat in a row.

## Deriving cut timing without drift

Hand-picking absolute start/end seconds per cut, one at a time, reliably drifts: small rounding or "close enough" choices per cut accumulate, and by the end of a multi-minute section the cut sheet's total no longer matches the script's actual measured section length (in one real case, off by over two minutes across ~40 cuts). The reliable method:

1. From the script (stage 3), get each section's real `(start, end)` in seconds — these come from the cumulative character-count timing, not from guesses.
2. Within a section, assign each cut a *relative weight* (a rough number of seconds it "feels like" it needs) rather than an absolute timestamp.
3. Rescale: `actual_duration = weight * (section_real_duration / sum_of_weights_in_section)`. Every section's cuts then sum exactly to that section's real duration by construction, and you never have to manually reconcile a running total.

This also makes it trivial to insert or delete a cut later — just add/remove a weighted row and rescale; nothing else needs to change.

## Asset list

Pull out two lists as you build the cut sheet, since they're the actual pre-production shopping list:
- **Captures needed**: timecode, what to screenshot, and — for anything that might change or disappear (a page that could be redesigned, a tweet that could be deleted) — a note to grab it *now* rather than right before rendering.
- **Stock/icon keywords needed**: short, specific, and biased toward close-ups/details that don't reveal a specific country or brand unintentionally (a wide shot with foreign-language signage or a recognizable storefront in a Korean-context video reads as visibly wrong to viewers). If real stock photography isn't available in your production environment (e.g. an Artifact's CSP blocks external image hosts), plan for hand-drawn line-icon SVGs instead — see `design-and-motion.md`.
