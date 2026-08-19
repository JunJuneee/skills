# Research and render QA

## Research

Use current primary sources for figures that can change. Prefer official statistical releases, central-bank calendars, company filings, and exchange or index-provider notices. Use a reputable market-close report to cross-check the narrative. Record publication date and direct URL for every fact group.

Separate fact from interpretation. Avoid language that implies guaranteed returns or personalized investment advice.

## Audio QA

- Confirm the supplied MP3 duration with `ffprobe`.
- Transcribe the actual file with Korean word or segment timestamps.
- Use sentence start times, including real pauses, rather than character-count estimates.
- Confirm the audio file copied into `public/` is the newest supplied file.

## Visual QA

Capture stills 0.3-1.0 seconds after each scene change. Check for clipped text, mismatched card order, unequal paired-card heights, guide misalignment, low mobile readability, and a silent blank ending.

## Delivery QA

- Video: H.264, 1080x1920, 30 fps.
- Audio: AAC present and audible.
- Duration: audio duration plus 2 seconds for the disclaimer, within normal frame rounding.
- No burned subtitles unless requested.
- Deliver the MP4 with an absolute local link and state the actual duration.

