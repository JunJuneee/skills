#!/usr/bin/env python3
"""Render one keyword into the fixed 400px Naver CTA template."""

from argparse import ArgumentParser
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets" / "cta-base-400.png"
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
GREEN = "#00a72a"
MAX_KEYWORD = "스파이더맨 4 개봉·관람 순서"
MAX_TEXT_WIDTH = 264


def choose_font(draw: ImageDraw.ImageDraw, keyword: str) -> ImageFont.FreeTypeFont:
    if len(keyword) > len(MAX_KEYWORD):
        raise ValueError(f"키워드는 공백 포함 최대 {len(MAX_KEYWORD)}자입니다: {MAX_KEYWORD}")
    for size in range(29, 18, -1):
        candidate = ImageFont.truetype(FONT, size, index=14)
        left, _, right, _ = draw.textbbox((0, 0), keyword, font=candidate)
        if right - left <= MAX_TEXT_WIDTH:
            return candidate
    raise ValueError("검색창에 안전하게 들어가지 않는 키워드입니다.")


def render(keyword: str, output: Path) -> None:
    image = Image.open(BASE).convert("RGB")
    draw = ImageDraw.Draw(image)
    selected = choose_font(draw, keyword)
    left, top, right, bottom = draw.textbbox((0, 0), keyword, font=selected)
    x = 39 + (277 - (right - left)) / 2 - left
    y = 217 - (bottom - top) / 2 - top
    draw.text((x, y), keyword, font=selected, fill=GREEN)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("keyword")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.keyword, args.output)
