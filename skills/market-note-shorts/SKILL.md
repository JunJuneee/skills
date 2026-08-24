---
name: market-note-shorts
description: Create and revise Korean vertical financial market-closing shorts in the Market Note card style. Use when Codex must research or ingest market facts, write display and pronunciation-oriented ElevenLabs TTS scripts, align a continuous MP3 to scene changes, generate timing data or SRT, update or copy the bundled Remotion template, render 1080x1920 H.264/AAC Shorts or Instagram Reels safe-area video, export matching covers or Vrew-ready scene PNGs, or diagnose narration-to-visual timing and ordering problems.
---

# Market Note Shorts

Build a verified Korean financial short from facts to a voice-synchronized vertical video. Treat the supplied TTS as the timing authority.

## Load only what is needed

- Read [references/script-style.md](references/script-style.md) before writing or revising narration.
- Read [references/visual-spec.md](references/visual-spec.md) before changing cards, typography, scene order, or the disclaimer.
- Read [references/research-and-qa.md](references/research-and-qa.md) when facts must be researched or a rendered video must be accepted.
- Use the **instagram-reels-publisher** skill when a finished reel must be published to Instagram.
- Use [assets/remotion-template](assets/remotion-template) when no working Remotion project exists. Otherwise modify the user's existing project in place.

## Workflow

### 1. Establish the content package

Collect the market date, closing values, percentage moves, macro drivers, notable stocks, next-session schedule, and direct source URLs. Verify time-sensitive facts with current primary sources. Do not invent missing values.

Produce two separate texts:

1. A display script using conventional notation such as `S&P 500`, `0.2%`, and `$88.52`.
2. A TTS script following `references/script-style.md`.

Keep visual order and narration order identical. If a card contains more information than the narration can support, either simplify the card or add useful narration.

### 2. Obtain one continuous TTS file

Prefer one full MP3 rather than sentence clips. Do not overlap or concatenate independent voice clips unless the user explicitly requests it.

If the user will synthesize the voice, deliver the final TTS script and wait for the MP3. Do not render a final synchronized video from estimated speech timing.

### 3. Analyze actual audio timing

Run:

```bash
python scripts/analyze_tts.py AUDIO.mp3 --output timing.json
```

If `faster_whisper` is installed in a nonstandard directory, add `--python-path PATH`. The first model download may require network access.

Use the returned segment start times to locate semantic boundaries. Never reuse timestamps from an older voice file.

### 3a. Build the episode file

Episodes are data, not new components. Write one JSON file per episode against
`assets/remotion-template/src/marketNote/types.ts` and render the shared `MarketNoteVideo`
and `MarketNoteCard` compositions with `--props=<episode>.json`. Do not add a dated
`.tsx` per day; that is what made the pipeline unautomatable.

Rows come in four shapes — `pair` (close plus change), `stat` (a labelled figure that
wraps), `single` (name and one value), and `numbered` (an ordered checklist). Any run
wrapped in asterisks takes the accent colour, so `"최대 *150조원*"` keeps 최대 in ink.

Derive the cue frames from the measured audio rather than by eye:

```bash
python scripts/build_cues.py timing.json --scene-segments 0 1 3 5 9 13 15 17 \
  --episode src/marketNote/data/YYYY-MM-DD-{market}.json
```

Each number is the timing.json segment index that opens a scene, so the count must be the
opening plus one per entry in `scenes`. Cuts land at the midpoint of the pause between
sentences, and the disclaimer starts at the measured file length.

### 4. Map narration to eight scenes

Use this fixed semantic order:

1. Opening market summary
2. Three major indices, narrated as one grouped sentence
3. Russell 2000 emphasis and why its divergence matters
4. Single lead-in to the key indicator
5. Macro card: retail sales, oil, and rate pressure
6. Stock movers in the exact same order as narration
7. One-sentence takeaway
8. Next-week schedule and interpretation

After the audio ends, show a static disclaimer for 2 seconds with no narration.

Compute frames with:

```bash
python scripts/build_timeline.py --audio-duration SECONDS --starts S0 S1 S2 S3 S4 S5 S6 S7
```

At 30 fps, each scene ends when the next scene begins. Set the final narrated scene to the audio end, then append 60 disclaimer frames.

### 5. Implement the Remotion composition

Copy the new MP3 into `public/` and update the audio source. Update all of the following together:

- Scene `from` and `durationInFrames` values
- Composition duration
- Progress-bar end frame
- Disclaimer start frame

Keep captions off the rendered video unless the user asks for burned-in captions. Generate SRT separately when requested.

For a separate SRT, first prepare a UTF-8 text file containing one reviewed display caption per Whisper segment. Keep each caption on one physical line and write `\\n` where a visual line break is needed. Then run:

```bash
python scripts/build_srt.py timing.json captions.txt --output captions.srt
```

Do not use the pronunciation-oriented TTS spelling as the visible caption text.

Render with stable concurrency:

```bash
npx remotion render src/index.ts DailyMarketCloseCalm out/market-note-final.mp4 --concurrency=1 --log=error
```

### 5a. Render a social-safe companion when Instagram or YouTube delivery is requested

Keep the standard Shorts composition unchanged. Create a separate social-safe composition with the identical audio, scene timings, narration order, and disclaimer duration.

Apply [references/visual-spec.md](references/visual-spec.md)'s Reels and Shorts safe layout to every scene, including the first frame and disclaimer. Reserve the right action rail as well as the top and bottom overlays. Do not simply reuse the standard Shorts MP4 or crop it. Render and retain both files when the user needs both platforms.

Export the Reels artifacts as:

```text
video/{market}-market-close-YYYY-MM-DD-reels.mp4
assets/thumbnail-{market}-market-close-YYYY-MM-DD-reels.png
qa/reels/
```

Create the thumbnail from the social-safe opening frame, not from the standard Shorts opening frame.

### 6. Validate before delivery

Run:

```bash
python scripts/verify_video.py out/market-note-final.mp4 --expected-width 1080 --expected-height 1920 --require-audio
```

Inspect stills shortly after every scene boundary, plus the first disclaimer frame. Confirm:

- The correct card appears when its sentence begins.
- Russell 2000 is visually dominant during its explanation.
- Stock order matches narration.
- Left and right card edges align to the progress bar.
- The disclaimer is fully visible from its first frame and holds for 2 seconds.
- The MP4 contains H.264 video and AAC audio at 1080x1920.

For a social-safe companion, inspect the opening, a dense macro or movers scene, and the disclaimer. Confirm that all essential elements stay inside the top, bottom, and right-action-rail safe area and that no platform-style UI is rendered into the video.

### 7. Archive the deliverables

After validation, archive every dated Market Note deliverable under:

```text
/Users/jun/Desktop/github/ai_video/{korea|america}/YYYY-MM-DD/
```

Use `korea` for Korean-market closes and `america` for U.S.-market closes. Use the market session date, not the render date, in ISO `YYYY-MM-DD` format.

Create only the needed subfolders:

- `video/`: final MP4 and explicitly retained video variants
- `assets/`: scene PNGs, contact sheets, and export bundles
- `audio/`: final TTS and other retained narration files
- `subtitles/`: SRT files
- `scripts/`: display and TTS scripts
- `qa/`: timing JSON and render-review stills

Use `qa/reels/` for Reels-specific review stills. Keep the matching Reels cover in `assets/`.

Place the final video at `video/{market}-market-close-YYYY-MM-DD-final.mp4`, where `{market}` is `korea` or `us`. Keep project source files in the working Remotion project so the composition remains rerenderable. Move generated output files into the archive after QA, but copy any audio or data files that the working composition still imports.

### 8. Publish the reel to Instagram

Only when the user asks for Instagram delivery. Use the **instagram-reels-publisher**
skill, which owns the scripts, the Meta app setup, and the specification table.

Publish the social-safe `-reels.mp4` variant, never `-final.mp4`: the standard Shorts
layout puts text under Instagram's action rail. Write the caption to
`scripts/{market}-market-close-YYYY-MM-DD-instagram-caption.txt` in the episode archive so
it is retained with the other deliverables.

## Non-negotiable rules

- Treat audio as the source of timing truth.
- Re-analyze every replacement MP3.
- Keep display notation separate from pronunciation notation.
- Do not apply a global CSS scale to enlarge the layout; change font sizes and card dimensions directly.
- Do not add a separate dark or off-brand disclaimer screen.
- Do not finish on an empty silent tail. Use the final 2 seconds for the static disclaimer.
- When Instagram Reels or YouTube Shorts is requested, preserve the standard render and create a separate social-safe render and cover.
- Report the actual rendered duration to the user.
- Deliver links from the dated `ai_video` archive path, not from the temporary Remotion output directory.
