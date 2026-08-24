# Instagram reel publishing

Publishes the social-safe Market Note reel through the Instagram Content Publishing API.

Instagram Login **rejects `upload_type=resumable`** — every API version answers a container
request with `The parameter video_url is required`. Resumable upload from disk works only
on the Facebook Login path. So the reel must sit at a **public HTTPS URL** while Instagram
fetches it, which it does once, at container creation. After the reel is published the URL
is no longer used and the file can be removed.

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

The Instagram account also needs the **Instagram tester** role on the app before any token
can be generated, or `계정 추가` fails with "insufficient developer role":

1. App Dashboard → **App roles → Roles** → **Add people**.
2. Pick the role **Instagram tester first** — the plain Administrator/Developer/Tester
   fields accept Facebook users only and reject an Instagram handle with
   `does not resolve to a valid user ID`.
3. Enter the Instagram username, add, and the row shows **Pending**.
4. Accept from the Instagram side at
   [instagram.com/accounts/manage_access](https://www.instagram.com/accounts/manage_access/)
   → **Tester invites** tab, signed in as that account. Pending roles stay inactive.

## Store the credentials

```bash
python scripts/instagram_auth.py exchange \
  --access-token TOKEN --app-secret APP_SECRET --save-app-secret
python scripts/instagram_auth.py whoami
```

The dashboard now issues a 60-day token directly. Exchanging one again fails with code 452
(`Session key invalid`), so `exchange` detects that and stores the token unchanged.

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

Then stage the file somewhere public and publish. A GitHub release on a public repository
works without extra infrastructure:

```bash
gh release create ig-media-YYYY-MM-DD --repo OWNER/REPO \
  --title "Instagram media staging YYYY-MM-DD" --notes "Temporary." VIDEO.mp4

python scripts/publish_reels.py video/korea-market-close-YYYY-MM-DD-reels.mp4 \
  --caption-file scripts/korea-market-close-YYYY-MM-DD-instagram-caption.txt \
  --video-url "https://github.com/OWNER/REPO/releases/download/ig-media-YYYY-MM-DD/VIDEO.mp4"

gh release delete ig-media-YYYY-MM-DD --repo OWNER/REPO --yes --cleanup-tag
```

Delete the staging release once the permalink prints. Instagram has already fetched the
file by then, and leaving it published serves the video from a second public location.

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
