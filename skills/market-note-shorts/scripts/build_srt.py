#!/usr/bin/env python3
"""Create an SRT file from Whisper timing JSON and reviewed display captions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def srt_time(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pair Whisper segments with one reviewed display caption per line."
    )
    parser.add_argument("timing_json", type=Path)
    parser.add_argument("captions_txt", type=Path)
    parser.add_argument("--output", "-o", type=Path, default=Path("captions.srt"))
    args = parser.parse_args()

    payload = json.loads(args.timing_json.read_text(encoding="utf-8"))
    segments = payload.get("segments", [])
    captions = [
        line.strip().replace(r"\n", "\n")
        for line in args.captions_txt.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if not segments:
        raise SystemExit("No segments found in timing JSON.")
    if len(captions) != len(segments):
        raise SystemExit(
            f"Caption count ({len(captions)}) must match segment count ({len(segments)})."
        )

    blocks: list[str] = []
    for index, (segment, caption) in enumerate(zip(segments, captions), start=1):
        blocks.append(
            f"{index}\n{srt_time(float(segment['start']))} --> "
            f"{srt_time(float(segment['end']))}\n{caption}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"Wrote {len(blocks)} captions to {args.output}")


if __name__ == "__main__":
    main()
