# Daily automation

`scripts/run_daily.sh korea|us [YYYY-MM-DD]` produces and publishes one episode. Two
launchd jobs call it on weekdays: the US session at 07:00 KST and the Korean session at
16:00 KST. The US job with no date argument builds the previous Seoul day, which is the
session that closed overnight.

## Configuration

Write `~/.config/market-note/automation.env` with owner-only permissions. It holds a voice
id and paths, not secrets — the ElevenLabs key, the YouTube token, and the Instagram token
stay where their own tools already read them.

```sh
ARCHIVE_ROOT=/Users/jun/Desktop/github/ai_video
REMOTION_DIR="/Users/jun/Documents/ChatGPT/금융 쇼츠 제작/remotion-shorts"
ELEVENLABS_VOICE_ID=<the Kim voice id>
STAGING_REPO=JunJuneee/skills
YOUTUBE_PRIVACY=public
YOUTUBE_TAGS=마켓노트,증시마감
NOTIFY_CMD='/Users/jun/claude-agents/.venv/bin/python /Users/jun/claude-agents/lib/notify.py'
```

Only paths outside the skill belong here. `SKILL_DIR` is derived from the script's own
location, and the sibling skills it calls — `youtube-video-publisher` and
`instagram-reels-publisher` — resolve next to it, so neither needs configuring. Override
`SKILL_DIR`, `YOUTUBE_SCRIPTS`, or `INSTAGRAM_SCRIPTS` only to point somewhere unusual.

`ELEVENLABS_VOICE_ID` is required because the API key lacks `voices_read`, so the voice
cannot be looked up by name. `NOTIFY_CMD` is optional; it receives one argument.

The agent stages run headless Claude Code, `claude -p --permission-mode bypassPermissions`,
with the Remotion project and the skill added as working directories. Bypassing
permissions is what makes the run unattended: a scheduled job has nobody to answer a tool
prompt and would hang until launchd killed it. Override `AGENT_CMD` to change model or
flags, for example `AGENT_CMD="claude -p --permission-mode bypassPermissions --model opus"`.

## Stages

1. The agent researches the session, writes the scripts, and emits the episode JSON.
2. `synthesize_tts.mjs` renders the narration.
3. `analyze_tts.py` measures it.
4. The agent maps transcript segments to scenes and prints only the indices.
5. `build_cues.py` turns those into cue frames.
6. Remotion renders `MarketNoteVideo` with `--props` pointing at the episode.
7. **The gate.** `verify_video.py` plus a publish dry run must both pass, and the cover
   frame is extracted. Nothing below this line runs otherwise.
8. YouTube upload, through the `youtube-video-publisher` skill.
9. Instagram: stage the file in a GitHub release, publish, delete the release.

Stages 1 to 3 skip when their output already exists, so a rerun after a failure resumes
rather than re-synthesising narration and spending ElevenLabs credit again.

An `ERR` trap deletes the staging release and sends the failure notice, so a crash between
stages 9 and 10 cannot leave the video served from a public URL.

## Installing the jobs

```bash
cp assets/launchd/com.jun.marketnote.*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jun.marketnote.us.plist
launchctl load ~/Library/LaunchAgents/com.jun.marketnote.korea.plist
```

Check one without waiting for the schedule:

```bash
launchctl start com.jun.marketnote.korea
tail -f /Users/jun/Desktop/github/ai_video/korea/$(date +%F)/qa/run.log
```

Run the script by hand first, on a past date, and confirm the episode looks right before
loading the jobs. `YOUTUBE_PRIVACY=unlisted` makes that rehearsal safe.

## The YouTube token will expire

Google issues 7-day refresh tokens to OAuth clients whose consent screen is still in
**Testing**. Automation dies silently a week after each manual re-authorisation. Set the
consent screen to **In production** in Google Cloud Console; unattended publishing is not
dependable until that is done.

The Instagram token lasts 60 days. Refresh it well before `expires_at`:

```bash
python ../instagram-reels-publisher/scripts/instagram_auth.py refresh
```
