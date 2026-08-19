#!/usr/bin/env python3
"""Validate the basic delivery properties of a rendered Market Note MP4."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def probe(video: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--expected-width", type=int, default=1080)
    parser.add_argument("--expected-height", type=int, default=1920)
    parser.add_argument("--expected-duration", type=float)
    parser.add_argument("--duration-tolerance", type=float, default=0.15)
    parser.add_argument("--require-audio", action="store_true")
    args = parser.parse_args()

    video = args.video.expanduser().resolve()
    if not video.is_file():
        parser.error(f"Video file does not exist: {video}")

    data = probe(video)
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    errors = []

    if not video_stream:
        errors.append("missing video stream")
    else:
        if video_stream.get("codec_name") != "h264":
            errors.append(f"video codec is {video_stream.get('codec_name')}, expected h264")
        if video_stream.get("width") != args.expected_width:
            errors.append(f"width is {video_stream.get('width')}, expected {args.expected_width}")
        if video_stream.get("height") != args.expected_height:
            errors.append(f"height is {video_stream.get('height')}, expected {args.expected_height}")

    if args.require_audio and not audio_stream:
        errors.append("missing audio stream")
    if audio_stream and audio_stream.get("codec_name") != "aac":
        errors.append(f"audio codec is {audio_stream.get('codec_name')}, expected aac")

    duration = float(data.get("format", {}).get("duration", 0))
    if args.expected_duration is not None:
        delta = abs(duration - args.expected_duration)
        if delta > args.duration_tolerance:
            errors.append(
                f"duration is {duration:.3f}s, expected {args.expected_duration:.3f}s "
                f"±{args.duration_tolerance:.3f}s"
            )

    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    audio_summary = "none"
    if audio_stream:
        audio_summary = f"{audio_stream.get('codec_name')} {audio_stream.get('sample_rate')}Hz"
    print(
        f"PASS: h264 {args.expected_width}x{args.expected_height}, "
        f"audio={audio_summary}, duration={duration:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

