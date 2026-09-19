# Reference research & topic strategy

## Surveying a reference channel

For each reference channel, in order:

1. Navigate to `https://www.youtube.com/@<handle>/videos`.
2. Scroll to load 20–30+ videos: `for (i=0;i<8;i++){ window.scrollTo(0, document.body.scrollHeight); await sleep(800); }`.
3. Pull the whole list at once from `#contents` via `innerText` — it comes back as repeating `duration / title / channel / views / age` blocks. Parse it into a table (title | views | age | length) rather than clicking into videos one at a time.
4. Sort by views. Look at the top 5–10 and bottom 5–10 specifically — the *contrast* between what worked and what didn't on the same channel, same audience, same production quality is the useful signal, more than the top list alone.
5. From the top performers, extract **title formulas**. Write each as `[abstract pattern] — [the real title]`, e.g.:
   - `[Authority figure/company did X] — [surprising number]` — "앤드류 응의 AI 일자리 산수 — 40% 자동화되면 60%는 더 비싸진다"
   - `[Company] analyzed [large dataset] — [unexpected finding]` — "앤트로픽이 클로드 코드 40만 세션을 분석했더니"
6. Open 1–3 of the actual top videos and look at the *screen*, not just the title. Set `video.muted = true; video.play(); video.currentTime = <t>` at several points (skip the first ~10–20s if a mid-roll ad is likely; skip ads via `.ytp-skip-ad-button, .ytp-ad-skip-button-modern, button.ytp-ad-skip-button`, or just reload if a skip button won't click). Screenshot the video element itself (not the whole page) at each point. Note concretely:
   - Background: dark or light, what hex-ish tone
   - Where the source/context label sits (top-left is common in this genre) and what it says
   - Caption/subtitle style (box color, position, how many lines)
   - How much of the runtime is a talking head vs. captured documents/tweets/slides vs. stock B-roll vs. pure infographic
   - Roughly how long shots hold before cutting (this sets your own target average shot length in stage 4)

## When to delegate this to a fork

If a channel survey is going to take more than ~3 tool calls (scrolling, multiple video opens, multiple screenshots), spawn it as a fork or a fresh general-purpose agent instead of doing it inline. The scrolling/scrubbing/screenshot process generates a lot of tool-call noise that isn't itself useful later — only the distilled findings are. Ask the sub-agent explicitly for: the sorted title/view table, the extracted title formulas, and a written description of what it saw on screen at each timestamp (not just "looks good" — actual colors, layout, motion).

**Common failure mode:** a fork asked to "research channel X" with full conversation context sometimes just restates facts already established earlier in the conversation instead of actually calling browser tools — check the returned `tool_uses` count in the completion notification. Zero tool calls on a research task means it didn't do the research; resend the task with an explicit numbered tool-call sequence.

## "It feels flat" — finding a second style reference

A single reference channel's conventions can start to feel monotonous once you're several episodes of design work in (heavy on static number-cards or text cards). If the user says something like "add motion graphics" or "this feels boring," that's a signal to go find a *second* reference tradition with a different motion vocabulary, not to just intensify the first one. In practice: cinematic explainer channels (camera push/pull on a static graphic, kinetic word-by-word typography) and pure-data-visualization channels (animated bar races, count-up numbers, dot/icon-grid pictograms for "N out of 100") are two genuinely different toolkits worth having on hand, and combining 3–4 concrete techniques from real channels (not invented from scratch) into a side-by-side switchable comparison (see `design-and-motion.md`) is much more useful to a user than a single default treatment.

## Topic / niche strategy

Classify the reference channels' recent videos (the same table from the survey above) into topic buckets by subject matter, not by format. For each bucket, compute the median view count. This is more informative than eyeballing which single video did best, because one viral outlier can make an otherwise-weak bucket look strong.

Cross-reference across *multiple unrelated channels* if you have the data — a pattern that holds across several different niches is much more trustworthy than one that only shows up in a single channel's data. What actually held across three unrelated reference channels in one real project: pure AI-tool-demo/tutorial content and pure macro/investment commentary both underperformed their own channel's median, while "an authoritative primary source, analyzed for a concrete numeric reversal" outperformed. Treat that as a hypothesis to check against your own research, not a rule to apply blindly.

**Avoid head-on competition.** List every specific topic the reference channels have already covered in your chosen bucket (title + rough date is enough). A brand-new channel picking the exact topic a 200-video incumbent already covered as its own best-performing video is starting from behind, because viewers who already saw the incumbent's version compare against it. Prefer an adjacent topic in the same bucket that hasn't been done, or a genuinely new angle on a covered topic (different data source, different reversal).

Once a niche is chosen, write down 3–4 candidate episode titles using the extracted title formulas, and a one-line "why this, why now" — this becomes the seed for the script (stage 3).
