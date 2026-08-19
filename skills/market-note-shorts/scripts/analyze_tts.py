#!/usr/bin/env python3
"""Transcribe a TTS MP3 and emit segment/word timestamps as JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_duration(audio: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="ko")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument(
        "--python-path",
        type=Path,
        help="Optional directory containing a nonstandard faster_whisper install.",
    )
    args = parser.parse_args()

    audio = args.audio.expanduser().resolve()
    if not audio.is_file():
        parser.error(f"Audio file does not exist: {audio}")

    if args.python_path:
        sys.path.insert(0, str(args.python_path.expanduser().resolve()))

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "faster_whisper is not installed. Install faster-whisper or pass "
            "--python-path pointing to an existing installation."
        ) from exc

    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute_type,
    )
    raw_segments, info = model.transcribe(
        str(audio),
        language=args.language,
        word_timestamps=True,
        vad_filter=True,
    )

    segments = []
    for index, segment in enumerate(raw_segments):
        words = []
        for word in segment.words or []:
            words.append(
                {
                    "start": round(float(word.start), 3),
                    "end": round(float(word.end), 3),
                    "text": word.word.strip(),
                    "probability": round(float(word.probability), 4),
                }
            )
        segments.append(
            {
                "index": index,
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": segment.text.strip(),
                "words": words,
            }
        )

    payload = {
        "audio": str(audio),
        "duration": round(get_duration(audio), 6),
        "detected_language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "segments": segments,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"Wrote {len(segments)} segments to {output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

