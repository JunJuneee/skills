#!/usr/bin/env python3
"""Derive Remotion cue frames from measured narration timing.

Takes the timing.json produced by analyze_tts.py plus the segment index that opens each
scene, and places every cut at the midpoint of the silence between the two sentences it
separates. That is the same placement the hand-tuned episodes used, without the guesswork.

Writes the `cues`, `disclaimerFrom` and `disclaimerFrames` fields of an episode file. With
--episode the values are merged into that file in place; otherwise they print as JSON.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def load_timing(timing: Path) -> tuple[list[dict], float | None]:
    data = json.loads(timing.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        segments, duration = data.get("segments"), data.get("duration")
    else:
        segments, duration = data, None
    if not segments:
        raise SystemExit(f"No segments found in {timing}")
    return segments, float(duration) if duration else None


def boundary_frame(previous_end: float, next_start: float, fps: int) -> int:
    """Cut halfway through the pause, so neither sentence is clipped."""
    if next_start < previous_end:
        next_start = previous_end
    return round((previous_end + next_start) / 2 * fps)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("timing", type=Path, help="timing.json from analyze_tts.py")
    parser.add_argument(
        "--scene-segments",
        type=int,
        nargs="+",
        required=True,
        help="Segment index that starts each scene, beginning with 0 for the opening",
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--disclaimer-seconds", type=float, default=2.0)
    parser.add_argument(
        "--episode", type=Path, help="Episode JSON to update in place instead of printing"
    )
    args = parser.parse_args()

    segments, audio_duration = load_timing(args.timing.expanduser())
    starts = args.scene_segments
    if starts[0] != 0:
        parser.error("The first scene must start at segment 0")
    if any(left >= right for left, right in zip(starts, starts[1:])):
        parser.error("--scene-segments must be strictly increasing")
    if starts[-1] >= len(segments):
        parser.error(f"Segment {starts[-1]} is out of range; timing has {len(segments)}")

    boundaries = [0]
    for index in starts[1:]:
        boundaries.append(
            boundary_frame(
                float(segments[index - 1]["end"]), float(segments[index]["start"]), args.fps
            )
        )

    # Prefer the measured file length: the MP3 usually carries a little silence after the
    # last transcribed word, and cutting to the disclaimer early clips the narration tail.
    end_seconds = max(audio_duration or 0.0, float(segments[-1]["end"]))
    narration_end = math.ceil(end_seconds * args.fps)
    if narration_end <= boundaries[-1]:
        raise SystemExit("Narration ends before the last scene starts; check --scene-segments")

    cues = [
        {"from": start, "duration": end - start}
        for start, end in zip(boundaries, boundaries[1:] + [narration_end])
    ]
    result = {
        "cues": cues,
        "disclaimerFrom": narration_end,
        "disclaimerFrames": round(args.disclaimer_seconds * args.fps),
    }

    if args.episode:
        episode_path = args.episode.expanduser()
        episode = json.loads(episode_path.read_text(encoding="utf-8"))
        expected = len(episode.get("scenes", [])) + 1
        if len(cues) != expected:
            raise SystemExit(
                f"{episode_path.name} has {expected - 1} scenes plus an opening, "
                f"so it needs {expected} cues, but {len(cues)} were derived"
            )
        episode.update(result)
        episode_path.write_text(
            json.dumps(episode, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        total = result["disclaimerFrom"] + result["disclaimerFrames"]
        print(f"Updated {episode_path} with {len(cues)} cues, {total} frames total")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
