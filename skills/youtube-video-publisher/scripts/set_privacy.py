#!/usr/bin/env python3
"""Change the privacy status of an existing YouTube video."""

import argparse
import json
import urllib.request

from common import access_token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id")
    parser.add_argument("--privacy", choices=("private", "unlisted", "public"), required=True)
    args = parser.parse_args()
    body = {
        "id": args.video_id,
        "status": {"privacyStatus": args.privacy, "selfDeclaredMadeForKids": False},
    }
    request = urllib.request.Request(
        "https://www.googleapis.com/youtube/v3/videos?part=status",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json; charset=UTF-8"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        video = json.load(response)
    print(f"Privacy updated: {video['status']['privacyStatus']}")


if __name__ == "__main__":
    main()
