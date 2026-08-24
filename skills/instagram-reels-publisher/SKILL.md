---
name: instagram-reels-publisher
description: Publish a vertical MP4 to Instagram as a Reel through the Instagram Graph API, including Meta app setup, tester-role troubleshooting, long-lived token storage and refresh, specification preflight, temporary public hosting, and caption handling. Use when the user asks to post or schedule an Instagram reel, connect or test the Instagram API, fix an Instagram token or permission error, or automate Instagram video delivery.
---

# Instagram Reels Publisher

Publishes a finished vertical video to an Instagram professional account and returns the
permalink. Two scripts do the work:

- `scripts/instagram_auth.py` — verify, store, and refresh credentials.
- `scripts/publish_reels.py` — preflight the file, create the container, publish, print the
  permalink.

Credentials live in `~/.config/instagram-reels/credentials.json` with owner-only
permissions, falling back to the older `~/.config/market-note/instagram.json` when that is
the only file present. Never write a token into a repository, a handoff note, or a message.

## Two facts that decide everything

**Instagram Login cannot upload from disk.** `upload_type=resumable` is rejected on
`graph.instagram.com` at every version from v22.0 to v25.0 with `The parameter video_url is
required`. Resumable upload is a Facebook Login feature. The file must therefore sit at a
public HTTPS URL, which Instagram fetches once, at container creation. Nothing reads that
URL afterwards, so delete the staged copy as soon as the permalink prints.

**The App Dashboard hands out 60-day tokens directly.** Passing one to `ig_exchange_token`
fails with code 452 `Session key invalid`. `instagram_auth.py exchange` detects that and
stores the token unchanged, so run it either way.

## Publish

Always dry-run first. It runs every specification check and prints the exact caption
without calling the API:

```bash
python scripts/publish_reels.py VIDEO.mp4 --caption-file CAPTION.txt --dry-run
```

Then stage the file, publish, and clean up. A GitHub release on a public repository works
with no extra infrastructure:

```bash
gh release create ig-media-YYYY-MM-DD --repo OWNER/REPO \
  --title "Instagram media staging" --notes "Temporary." VIDEO.mp4

python scripts/publish_reels.py VIDEO.mp4 --caption-file CAPTION.txt \
  --video-url "https://github.com/OWNER/REPO/releases/download/ig-media-YYYY-MM-DD/VIDEO.mp4"

gh release delete ig-media-YYYY-MM-DD --repo OWNER/REPO --yes --cleanup-tag
```

Staging publishes the video to a second public location. Confirm with the user before
staging anything that is not already public, and delete the release even when the publish
fails.

Options worth knowing:

- `--no-share-to-feed` keeps the reel out of the profile grid, Reels tab only.
- `--cover-url` sets the Reels-tab cover but needs a public HTTPS **JPEG**; without one use
  `--thumb-offset MILLISECONDS` to pick a frame.
- `--hashtags-file` appends a tag block after a blank line.
- `--audio-name` names the reel audio. Instagram allows this once per reel.

## Specification, enforced before any API call

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

A failing preflight exits 1 and names every violation. For a `moov` failure, remux without
re-encoding: `ffmpeg -i IN.mp4 -c copy -movflags +faststart OUT.mp4`.

Instagram allows 100 API-published posts per rolling 24 hours per account.

## Setup and error recovery

Read [references/setup.md](references/setup.md) for the Meta app walkthrough. The errors
that actually block a first setup, in the order they appear:

- **"개발자 역할 권한 부족" on Add account** — the Instagram account has no role on the app.
- **`"name" does not resolve to a valid user ID`** — the role popup was left on
  Administrator/Developer/Tester, which accept Facebook users only. Select **Instagram
  tester first**, then the username field appears.
- **Role stuck on Pending** — the invite must be accepted from the Instagram side at
  [instagram.com/accounts/manage_access](https://www.instagram.com/accounts/manage_access/)
  → **Tester invites**, signed in as that account. A pending role stays inactive.
- **`Invalid OAuth access token`** — expired or issued to a different app. Generate a new
  token and rerun `exchange`.
- **Container status `ERROR`** — the media was rejected after fetching; the status message
  names the reason. **`EXPIRED`** — an unpublished container passed its 24-hour window.

Tokens last 60 days and are refreshable only after 24 hours of age. Run
`python scripts/instagram_auth.py refresh` well before the `expires_at` that `whoami`
prints; an expired token forces the dashboard steps again by hand.

## Account requirements

The target account must be **professional** (Business or Creator) — the Content Publishing
API rejects personal accounts. App Review is not needed while publishing only to accounts
connected to the app in development mode; it is required only to publish on behalf of other
people's accounts.
