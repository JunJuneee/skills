#!/usr/bin/env python3
"""Publish a rendered Market Note reel to Instagram via the Content Publishing API.

The video is uploaded straight from disk through the resumable upload endpoint, so
no public hosting is needed. A cover image still requires a public URL; without one
the cover is taken from the frame at --thumb-offset.

Run with --dry-run first: it performs every local spec check and prints the caption
without touching the API.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".config" / "market-note" / "instagram.json"
GRAPH_HOSTS = {"instagram": "graph.instagram.com", "facebook": "graph.facebook.com"}
RUPLOAD_HOST = "rupload.facebook.com"
API_VERSION = "v23.0"

# Instagram reels specifications, as published in the IG User Media API reference.
MAX_FILE_BYTES = 300 * 1024 * 1024
MIN_DURATION_SECONDS = 3.0
MAX_DURATION_SECONDS = 900.0
MIN_FPS = 23.0
MAX_FPS = 60.0
MAX_HORIZONTAL_PIXELS = 1920
MIN_ASPECT_RATIO = 0.01
MAX_ASPECT_RATIO = 10.0
ALLOWED_VIDEO_CODECS = {"h264", "hevc"}
ALLOWED_AUDIO_CODECS = {"aac"}
MAX_CAPTION_CHARS = 2200


def probe(video: Path) -> dict:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise SystemExit("ffprobe not found. Install ffmpeg to run the reel preflight.") from error
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"ffprobe failed on {video}: {error.stderr.strip()}") from error
    return json.loads(result.stdout)


def parse_frame_rate(value: str | None) -> float | None:
    if not value:
        return None
    if "/" in value:
        numerator, _, denominator = value.partition("/")
        try:
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            return float(numerator) / denominator_value
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None


def moov_before_mdat(video: Path) -> bool | None:
    """Return True when the moov atom precedes mdat, None when the layout is unreadable."""
    try:
        with video.open("rb") as handle:
            offset = 0
            file_size = video.stat().st_size
            while offset < file_size:
                handle.seek(offset)
                header = handle.read(8)
                if len(header) < 8:
                    return None
                size = int.from_bytes(header[:4], "big")
                name = header[4:8].decode("ascii", "replace")
                if size == 1:
                    extended = handle.read(8)
                    if len(extended) < 8:
                        return None
                    size = int.from_bytes(extended, "big")
                elif size == 0:
                    size = file_size - offset
                if name == "moov":
                    return True
                if name == "mdat":
                    return False
                if size < 8:
                    return None
                offset += size
    except OSError:
        return None
    return None


def preflight(video: Path) -> list[str]:
    problems: list[str] = []
    size_bytes = video.stat().st_size
    if size_bytes > MAX_FILE_BYTES:
        problems.append(
            f"file is {size_bytes / 1024 / 1024:.1f}MB, over the {MAX_FILE_BYTES // 1024 // 1024}MB reels limit"
        )
    if video.suffix.lower() not in {".mp4", ".mov"}:
        problems.append(f"container is {video.suffix or 'unknown'}, expected .mp4 or .mov")

    data = probe(video)
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not video_stream:
        problems.append("no video stream found")
    else:
        codec = video_stream.get("codec_name")
        if codec not in ALLOWED_VIDEO_CODECS:
            problems.append(f"video codec is {codec}, expected one of {sorted(ALLOWED_VIDEO_CODECS)}")
        width = video_stream.get("width") or 0
        height = video_stream.get("height") or 0
        if width > MAX_HORIZONTAL_PIXELS:
            problems.append(f"width is {width}px, over the {MAX_HORIZONTAL_PIXELS}px limit")
        if height:
            ratio = width / height
            if not MIN_ASPECT_RATIO <= ratio <= MAX_ASPECT_RATIO:
                problems.append(f"aspect ratio {ratio:.3f} is outside {MIN_ASPECT_RATIO}:1..{MAX_ASPECT_RATIO}:1")
        fps = parse_frame_rate(video_stream.get("avg_frame_rate")) or parse_frame_rate(
            video_stream.get("r_frame_rate")
        )
        if fps is None:
            problems.append("frame rate could not be read")
        elif not MIN_FPS - 0.5 <= fps <= MAX_FPS + 0.5:
            problems.append(f"frame rate is {fps:.2f}fps, expected {MIN_FPS:.0f}-{MAX_FPS:.0f}fps")

    if not audio_stream:
        problems.append("no audio stream found; a Market Note reel must carry its narration")
    elif audio_stream.get("codec_name") not in ALLOWED_AUDIO_CODECS:
        problems.append(f"audio codec is {audio_stream.get('codec_name')}, expected aac")

    duration = data.get("format", {}).get("duration")
    try:
        duration_seconds = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_seconds = None
    if duration_seconds is None:
        problems.append("duration could not be read")
    elif duration_seconds < MIN_DURATION_SECONDS:
        problems.append(f"duration is {duration_seconds:.2f}s, under the {MIN_DURATION_SECONDS:.0f}s minimum")
    elif duration_seconds > MAX_DURATION_SECONDS:
        problems.append(f"duration is {duration_seconds:.1f}s, over the 15 minute maximum")

    faststart = moov_before_mdat(video)
    if faststart is False:
        problems.append(
            "moov atom sits after mdat; remux with "
            "'ffmpeg -i IN.mp4 -c copy -movflags +faststart OUT.mp4'"
        )

    if not problems:
        resolution = f"{video_stream.get('width')}x{video_stream.get('height')}" if video_stream else "?"
        print(
            f"Preflight OK: {resolution}, {duration_seconds:.1f}s, "
            f"{size_bytes / 1024 / 1024:.1f}MB, moov-first={faststart}"
        )
    return problems


def load_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"Config file is not valid JSON: {path} ({error})") from error


def api_request(host: str, path: str, params: dict, method: str = "GET") -> dict:
    encoded = urllib.parse.urlencode(params).encode("utf-8")
    if method == "GET":
        url = f"https://{host}/{API_VERSION}/{path.lstrip('/')}?{encoded.decode('utf-8')}"
        request = urllib.request.Request(url, method="GET")
    else:
        url = f"https://{host}/{API_VERSION}/{path.lstrip('/')}"
        request = urllib.request.Request(url, data=encoded, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise SystemExit(f"Instagram API error {error.code} on {method} /{path}: {detail}") from error


def upload_video(container_id: str, video: Path, token: str, attempts: int) -> None:
    url = f"https://{RUPLOAD_HOST}/ig-api-upload/{API_VERSION}/{container_id}"
    size_bytes = video.stat().st_size
    payload = video.read_bytes()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"OAuth {token}",
                "offset": "0",
                "file_size": str(size_bytes),
                "Content-Type": "application/octet-stream",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                body = json.loads(response.read().decode("utf-8"))
            if body.get("success") is False:
                raise RuntimeError(f"upload rejected: {body}")
            print(f"Uploaded {size_bytes / 1024 / 1024:.1f}MB to container {container_id}")
            return
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, TimeoutError) as error:
            detail = error.read().decode("utf-8", "replace") if isinstance(error, urllib.error.HTTPError) else str(error)
            last_error = error
            print(f"Upload attempt {attempt}/{attempts} failed: {detail}", file=sys.stderr)
            if attempt < attempts:
                time.sleep(5 * attempt)
    raise SystemExit(f"Video upload failed after {attempts} attempts: {last_error}")


def wait_until_finished(host: str, container_id: str, token: str, interval: int, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while True:
        payload = api_request(
            host, container_id, {"fields": "status_code,status", "access_token": token}
        )
        code = payload.get("status_code")
        if code == "FINISHED":
            print("Container status: FINISHED")
            return
        if code in {"ERROR", "EXPIRED"}:
            raise SystemExit(f"Container {container_id} ended in {code}: {payload.get('status')}")
        if time.monotonic() >= deadline:
            raise SystemExit(
                f"Container {container_id} still {code} after {timeout}s. "
                "Instagram is still transcoding; re-check later before republishing."
            )
        print(f"Container status: {code}; waiting {interval}s")
        time.sleep(interval)


def build_caption(args) -> str:
    parts: list[str] = []
    if args.caption_file:
        parts.append(args.caption_file.expanduser().read_text(encoding="utf-8").strip())
    if args.caption:
        parts.append(args.caption.strip())
    if args.hashtags_file:
        parts.append(args.hashtags_file.expanduser().read_text(encoding="utf-8").strip())
    caption = "\n\n".join(part for part in parts if part)
    if len(caption) > MAX_CAPTION_CHARS:
        raise SystemExit(
            f"Caption is {len(caption)} characters, over the {MAX_CAPTION_CHARS} character limit."
        )
    return caption


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("video", type=Path, help="Rendered reels MP4, normally the -reels.mp4 variant")
    parser.add_argument("--caption", help="Caption text passed inline")
    parser.add_argument("--caption-file", type=Path, help="File holding the caption body")
    parser.add_argument("--hashtags-file", type=Path, help="File appended to the caption after a blank line")
    parser.add_argument(
        "--video-url",
        help="Public HTTPS URL Instagram fetches the video from. Required for Instagram "
        "Login, which does not accept resumable uploads. The local file is still used "
        "for the preflight checks.",
    )
    parser.add_argument("--cover-url", help="Public HTTPS URL of a JPEG cover; overrides --thumb-offset")
    parser.add_argument("--thumb-offset", type=int, default=0, help="Cover frame position in milliseconds")
    parser.add_argument("--audio-name", help="Names the reel audio; Instagram allows this only once")
    parser.add_argument(
        "--no-share-to-feed",
        action="store_true",
        help="Keep the reel out of the main feed, showing it only in the Reels tab",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--login-type", choices=sorted(GRAPH_HOSTS))
    parser.add_argument("--access-token")
    parser.add_argument("--ig-user-id")
    parser.add_argument("--poll-interval", type=int, default=10)
    parser.add_argument("--poll-timeout", type=int, default=600)
    parser.add_argument("--upload-attempts", type=int, default=3)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the local checks and print the request plan without calling the API",
    )
    args = parser.parse_args()

    video = args.video.expanduser().resolve()
    if not video.is_file():
        parser.error(f"Video file does not exist: {video}")

    if not args.skip_preflight:
        problems = preflight(video)
        if problems:
            print(f"{video} fails the Instagram reels specification:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1

    caption = build_caption(args)
    config = load_config(args.config.expanduser())
    login_type = args.login_type or config.get("login_type") or "instagram"
    host = GRAPH_HOSTS[login_type]
    token = args.access_token or os.environ.get("IG_ACCESS_TOKEN") or config.get("access_token")
    ig_user_id = args.ig_user_id or os.environ.get("IG_USER_ID") or config.get("ig_user_id")

    container_params = {
        "media_type": "REELS",
        "share_to_feed": "false" if args.no_share_to_feed else "true",
    }
    if args.video_url:
        # Instagram Login rejects upload_type=resumable, so the file must be fetched
        # from a public HTTPS URL. See references/instagram-publishing.md.
        container_params["video_url"] = args.video_url
    else:
        container_params["upload_type"] = "resumable"
    if caption:
        container_params["caption"] = caption
    if args.cover_url:
        container_params["cover_url"] = args.cover_url
    elif args.thumb_offset:
        container_params["thumb_offset"] = str(args.thumb_offset)
    if args.audio_name:
        container_params["audio_name"] = args.audio_name

    if args.dry_run:
        print("\n--- dry run ---")
        print(f"endpoint     : https://{host}/{API_VERSION}/{ig_user_id or '<IG_USER_ID>'}/media")
        print(f"video        : {video} ({video.stat().st_size / 1024 / 1024:.1f}MB)")
        print(f"source       : {args.video_url or 'resumable upload from disk'}")
        print(f"login_type   : {login_type}")
        print(f"token        : {'present' if token else 'MISSING'}")
        print(f"ig_user_id   : {ig_user_id or 'MISSING'}")
        print(f"share_to_feed: {container_params['share_to_feed']}")
        print(f"cover        : {args.cover_url or f'frame at {args.thumb_offset}ms'}")
        print(f"caption ({len(caption)} chars):\n{caption or '(empty)'}")
        return 0

    if not token:
        raise SystemExit("No access token. Run instagram_auth.py exchange or set IG_ACCESS_TOKEN.")
    if not ig_user_id:
        raise SystemExit("No Instagram user id. Run instagram_auth.py whoami or set IG_USER_ID.")

    container_params["access_token"] = token
    container = api_request(host, f"{ig_user_id}/media", container_params, method="POST")
    container_id = container.get("id")
    if not container_id:
        raise SystemExit(f"Container creation returned no id: {container}")
    print(f"Created container {container_id}")

    if not args.video_url:
        upload_video(container_id, video, token, args.upload_attempts)
    wait_until_finished(host, container_id, token, args.poll_interval, args.poll_timeout)

    published = api_request(
        host,
        f"{ig_user_id}/media_publish",
        {"creation_id": container_id, "access_token": token},
        method="POST",
    )
    media_id = published.get("id")
    print(f"Published media {media_id}")

    permalink = api_request(host, str(media_id), {"fields": "permalink", "access_token": token})
    if permalink.get("permalink"):
        print(f"Permalink: {permalink['permalink']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
