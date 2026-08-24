# Instagram reel publishing

Publishes the social-safe Market Note reel through the Instagram Content Publishing API.
The video uploads straight from disk, so no public file hosting is required.

## One-time account and app setup

1. Switch the target Instagram account to **Professional** (Business or Creator). The
   Content Publishing API rejects personal accounts.
2. At [developers.facebook.com](https://developers.facebook.com/) create an app: **Other →
   Business**, then add the **Instagram** product and open **API setup with Instagram login**.
3. Connect the account in that panel. It returns an **Instagram User ID** and a
   **short-lived access token**, and it is where the `instagram_business_basic` and
   `instagram_business_content_publish` permissions get granted.
4. Copy the **App secret** from **App settings → Basic**.

App Review is not needed while publishing only to accounts connected to the app in
development mode. Review is required only to publish on behalf of other people's accounts.

Facebook Login is the alternative path. It routes through `graph.facebook.com`, needs the
Instagram account linked to a Facebook Page, and uses `instagram_basic`,
`instagram_content_publish`, and `pages_read_engagement`. Prefer Instagram Login unless a
Page is already part of the workflow.

## Store the credentials

Exchange the short-lived token for a 60-day token and record the account id:

```bash
python scripts/instagram_auth.py exchange \
  --access-token SHORT_LIVED_TOKEN --app-secret APP_SECRET --save-app-secret
python scripts/instagram_auth.py whoami
```

Both write to `~/.config/market-note/instagram.json` with owner-only permissions. Never
commit that file or paste a token into the repository. `IG_ACCESS_TOKEN` and `IG_USER_ID`
override the config file when set.

Long-lived tokens last 60 days and are refreshable only after 24 hours of age:

```bash
python scripts/instagram_auth.py refresh
```

Run the refresh well before the `expires_at` date that `whoami` prints. An expired token
requires repeating the dashboard exchange by hand.

## Publish a reel

Always dry-run first. It runs every local specification check and prints the exact caption
without calling the API:

```bash
python scripts/publish_reels.py \
  video/korea-market-close-2026-08-24-reels.mp4 \
  --caption-file scripts/instagram-caption.txt \
  --dry-run
```

Then publish:

```bash
python scripts/publish_reels.py \
  video/korea-market-close-2026-08-24-reels.mp4 \
  --caption-file scripts/instagram-caption.txt
```

Publish the `-reels.mp4` social-safe variant, not `-final.mp4`. The standard Shorts render
places text under the Instagram action rail and bottom overlay.

The script creates a resumable container, uploads the file, polls `status_code` until
`FINISHED`, publishes, and prints the permalink. Transcoding usually finishes within a
minute; `--poll-timeout` defaults to 600 seconds.

Useful options:

- `--cover-url` sets the Reels-tab cover, but needs a **public HTTPS JPEG URL**. Without
  hosting, use `--thumb-offset MILLISECONDS` to pick a frame from the video instead.
- `--no-share-to-feed` keeps the reel in the Reels tab only.
- `--hashtags-file` appends a tag block after a blank line.
- `--audio-name` names the reel audio. Instagram permits this only once per reel.

## Specification limits enforced by preflight

Values come from the IG User Media API reference. The preflight fails the run before any
API call when the render violates them.

| Property | Requirement |
| --- | --- |
| Container | MP4 or MOV, `moov` atom before `mdat` |
| Video codec | H264 or HEVC |
| Audio codec | AAC |
| Frame rate | 23–60 FPS |
| Width | 1920 px maximum |
| Aspect ratio | 0.01:1 to 10:1; 9:16 recommended |
| Duration | 3 seconds to 15 minutes |
| File size | 300 MB maximum |
| Caption | 2200 characters maximum |

A standard 1080x1920 Market Note reel clears all of these. When a render trips the `moov`
check, remux without re-encoding:

```bash
ffmpeg -i IN.mp4 -c copy -movflags +faststart OUT.mp4
```

## Rate limit

Instagram allows 100 API-published posts per rolling 24 hours per account. One daily
market-close reel is far inside that ceiling.

## Failure handling

- `Invalid OAuth access token` — the token expired or belongs to another app. Re-run
  `exchange`.
- Container status `ERROR` — Instagram rejected the media after upload. Re-check the
  preflight table; the status message names the reason.
- Container status `EXPIRED` — an unpublished container passed its 24-hour window. Re-run
  the publish from the start.
- Upload interrupted — the script retries three times with backoff. Adjust with
  `--upload-attempts`.
