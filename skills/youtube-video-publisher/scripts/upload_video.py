#!/usr/bin/env python3
"""Upload a local video to the authorized YouTube channel."""

import argparse
import json
import mimetypes
import urllib.parse
import urllib.request
from pathlib import Path

from common import access_token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description-file", type=Path, required=True)
    parser.add_argument("--privacy", choices=("private", "unlisted", "public"), default="private")
    parser.add_argument("--tags", default="")
    parser.add_argument("--category", default="25")
    args = parser.parse_args()
    if not args.video.is_file() or not args.description_file.is_file():
        raise SystemExit("Video or description file was not found.")

    media_type = mimetypes.guess_type(args.video.name)[0] or "video/mp4"
    size = args.video.stat().st_size
    metadata = {
        "snippet": {
            "title": args.title,
            "description": args.description_file.read_text(encoding="utf-8"),
            "categoryId": args.category,
        },
        "status": {"privacyStatus": args.privacy, "selfDeclaredMadeForKids": False},
    }
    tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    if tags:
        metadata["snippet"]["tags"] = tags
    session_url = "https://www.googleapis.com/upload/youtube/v3/videos?" + urllib.parse.urlencode(
        {"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "false"}
    )
    start = urllib.request.Request(
        session_url,
        data=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token()}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": media_type,
        },
        method="POST",
    )
    with urllib.request.urlopen(start, timeout=60) as response:
        upload_url = response.headers["Location"]
    if not upload_url:
        raise SystemExit("YouTube did not return a resumable upload URL.")
    with args.video.open("rb") as source:
        upload = urllib.request.Request(
            upload_url,
            data=source.read(),
            headers={"Content-Type": media_type, "Content-Length": str(size)},
            method="PUT",
        )
        with urllib.request.urlopen(upload, timeout=900) as response:
            video = json.load(response)
    print(f"Uploaded: https://www.youtube.com/watch?v={video['id']}")
    print(f"Privacy: {args.privacy}")


if __name__ == "__main__":
    main()
