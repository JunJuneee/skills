#!/usr/bin/env python3
"""Print the channel authorized by the local YouTube token."""

import json
import urllib.request

from common import access_token


def main() -> None:
    request = urllib.request.Request(
        "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true",
        headers={"Authorization": f"Bearer {access_token()}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        items = json.load(response).get("items", [])
    if not items:
        raise SystemExit("No YouTube channel is available for this Google account.")
    channel = items[0]
    print(f"Connected channel: {channel['snippet']['title']} ({channel['id']})")


if __name__ == "__main__":
    main()
