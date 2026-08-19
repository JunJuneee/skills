#!/usr/bin/env python3
"""Convert eight semantic scene start times into Remotion frame ranges."""

from __future__ import annotations

import argparse
import math


SCENE_NAMES = (
    "opening",
    "indices",
    "russell",
    "key_indicator",
    "macro",
    "movers",
    "takeaway",
    "outlook",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-duration", type=float, required=True)
    parser.add_argument("--starts", type=float, nargs=8, required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--disclaimer-seconds", type=float, default=2.0)
    args = parser.parse_args()

    if args.audio_duration <= 0:
        parser.error("--audio-duration must be positive")
    if args.fps <= 0:
        parser.error("--fps must be positive")
    if args.starts[0] != 0:
        parser.error("The opening scene must start at 0 seconds")
    if any(left >= right for left, right in zip(args.starts, args.starts[1:])):
        parser.error("Scene starts must be strictly increasing")
    if args.starts[-1] >= args.audio_duration:
        parser.error("The final scene must start before the audio ends")

    starts = [round(value * args.fps) for value in args.starts]
    audio_end = math.ceil(args.audio_duration * args.fps)
    disclaimer_frames = round(args.disclaimer_seconds * args.fps)

    print("const CUES = [")
    for index, (name, start) in enumerate(zip(SCENE_NAMES, starts)):
        end = starts[index + 1] if index + 1 < len(starts) else audio_end
        print(f"  {{from: {start}, duration: {end - start}}}, // {name}")
    print("] as const;")
    print()
    print(f"audioEndFrame: {audio_end}")
    print(f"disclaimerFrom: {audio_end}")
    print(f"disclaimerFrames: {disclaimer_frames}")
    print(f"compositionFrames: {audio_end + disclaimer_frames}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

