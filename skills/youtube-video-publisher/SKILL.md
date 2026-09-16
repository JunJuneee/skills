---
name: youtube-video-publisher
description: Authorize a YouTube channel, upload local video files, and manage published video privacy and metadata through the YouTube Data API. Use when Codex needs to upload an MP4 or other local video to YouTube, publish or unpublish a Shorts/video, verify the authorized channel, or troubleshoot YouTube OAuth and API permission errors.
---

# YouTube Video Publisher

Use the bundled scripts for deterministic OAuth, upload, and publish operations. Keep all OAuth state in `~/.codex/youtube-video-publisher/`; never place tokens, client secrets, or downloaded `client_secret.json` files in a repository or chat response.

## Authorization setup

1. In the **same Google Cloud project** that owns the desktop OAuth client, enable **YouTube Data API v3**.
2. In Google Auth Platform, add only the scopes required:
   - `youtube.upload` for creating a video.
   - `youtube.force-ssl` as well for changing privacy, title, description, thumbnails, or other video metadata.
3. If the OAuth app is in Testing, add the YouTube channel owner as a test user.
4. Ask the user for explicit approval before opening a browser login flow. Use their local downloaded OAuth JSON without displaying its contents:

```bash
python3 scripts/authorize.py --client-secrets /absolute/path/client_secret.json --mode manage
```

`--mode upload` requests only upload permission. Re-run authorization with `--mode manage` after adding management scope or changing accounts.

## Verify the target channel

Before any live write, verify which channel the token controls:

```bash
python3 scripts/check_channel.py
```

If the channel is wrong, re-run `authorize.py` and approve using the correct Google account or Brand Channel.

## Upload videos

Use a private upload by default. Obtain explicit user approval before `--privacy public` or `--privacy unlisted` because it changes external visibility.

```bash
python3 scripts/upload_video.py /absolute/path/video.mp4 \
  --title "Exact title" \
  --description-file /absolute/path/description.txt \
  --tags "tag-one,tag-two" \
  --privacy private
```

For a Shorts candidate, verify the source is vertical with `ffprobe`; YouTube, not the API, determines final Shorts classification. Do not promise the classification before processing completes.

## Publish or change visibility

Changing privacy requires the `manage` token and explicit user approval. Use the returned video ID:

```bash
python3 scripts/set_privacy.py VIDEO_ID --privacy public
```

## Guardrails and recovery

- Never use an API key or service account for channel uploads; use desktop OAuth.
- Do not delete, overwrite, or publicly publish content without clear user authorization.
- `accessNotConfigured` means YouTube Data API v3 is disabled in the OAuth client's project, not necessarily the currently selected console project.
- `insufficientPermissions` for a metadata update means the token lacks `youtube.force-ssl`; add the scope and re-authorize.
- `videoNotFound` after re-authorizing usually means a different channel/account was selected; run `check_channel.py` before retrying.
- Projects subject to YouTube's verification policy can force API uploads private. Report that outcome and ask before any manual/public follow-up.

## Scripts

- `scripts/authorize.py` — browser OAuth and refresh-token storage.
- `scripts/check_channel.py` — read-only confirmation of the authorized channel.
- `scripts/upload_video.py` — resumable video upload with metadata.
- `scripts/set_privacy.py` — private, unlisted, or public status update.
