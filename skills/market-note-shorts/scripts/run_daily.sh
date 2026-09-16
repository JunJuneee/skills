#!/usr/bin/env bash
# Produce and publish one Market Note episode end to end.
#
#   run_daily.sh korea|us [YYYY-MM-DD]
#
# Stages: write the episode, synthesise narration, measure it, derive cues, render,
# verify, then publish to YouTube and Instagram. The render is verified before anything
# is published, so a broken episode fails loudly instead of going out.
#
# Configuration comes from ~/.config/market-note/automation.env; see
# references/automation.md.

set -Eeuo pipefail

MARKET="${1:-}"
if [[ "$MARKET" != "korea" && "$MARKET" != "us" ]]; then
  echo "usage: $0 korea|us [YYYY-MM-DD]" >&2
  exit 2
fi

# 이 스크립트는 스킬 안에 있으므로 스킬 경로는 설정이 아니라 자기 위치에서 구한다.
SKILL_DIR="${SKILL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SKILLS_ROOT="$(cd "$SKILL_DIR/.." && pwd)"

CONFIG="${MARKET_NOTE_ENV:-$HOME/.config/market-note/automation.env}"
# shellcheck source=/dev/null
[[ -f "$CONFIG" ]] && source "$CONFIG"

: "${ARCHIVE_ROOT:?set ARCHIVE_ROOT in $CONFIG}"
: "${REMOTION_DIR:?set REMOTION_DIR in $CONFIG}"
: "${ELEVENLABS_VOICE_ID:?set ELEVENLABS_VOICE_ID in $CONFIG}"
: "${STAGING_REPO:?set STAGING_REPO in $CONFIG}"
# Headless Claude Code. bypassPermissions is what makes it unattended: a scheduled run
# has nobody to answer a tool prompt, and the job would hang until launchd killed it.
AGENT_CMD="${AGENT_CMD:-claude -p --permission-mode bypassPermissions}"
PRIVACY="${YOUTUBE_PRIVACY:-public}"
INSTAGRAM_SCRIPTS="${INSTAGRAM_SCRIPTS:-$SKILLS_ROOT/instagram-reels-publisher/scripts}"
YOUTUBE_SCRIPTS="${YOUTUBE_SCRIPTS:-$SKILLS_ROOT/youtube-video-publisher/scripts}"

DATE="${2:-$(TZ=Asia/Seoul date +%F)}"
# The US session that closes overnight belongs to the previous Seoul day.
if [[ "$MARKET" == "us" && -z "${2:-}" ]]; then
  DATE="$(TZ=Asia/Seoul date -v-1d +%F 2>/dev/null || date -d 'yesterday' +%F)"
fi

REGION_DIR="$([[ "$MARKET" == "korea" ]] && echo korea || echo america)"
EPISODE="$ARCHIVE_ROOT/$REGION_DIR/$DATE"
SLUG="$MARKET-market-close-$DATE"
DATA_JSON="$REMOTION_DIR/src/marketNote/data/$DATE-$MARKET.json"
VIDEO="$EPISODE/video/$SLUG-reels.mp4"
STAGING_TAG="ig-media-$MARKET-$DATE"

mkdir -p "$EPISODE"/{scripts,audio,video,assets,qa}
LOG="$EPISODE/qa/run.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $SLUG  started $(date -u +%FT%TZ) ==="

notify() {
  [[ -n "${NOTIFY_CMD:-}" ]] && "$SHELL" -c "$NOTIFY_CMD" "$1" || true
}

cleanup_staging() {
  gh release delete "$STAGING_TAG" --repo "$STAGING_REPO" --yes --cleanup-tag >/dev/null 2>&1 || true
}

on_error() {
  local line=$1
  echo "FAILED at line $line. Nothing further was published."
  cleanup_staging
  notify "Market Note $SLUG failed at line $line. See $LOG"
}
trap 'on_error $LINENO' ERR

run_agent() {
  # $1 = prompt. The agent runs inside the archive so relative paths resolve, and needs
  # the Remotion project and the skill on top of that to write the episode file.
  ( cd "$EPISODE" && $AGENT_CMD --add-dir "$REMOTION_DIR" --add-dir "$SKILL_DIR" "$1" )
}

# 1. Research, copy, and the episode data file.
if [[ ! -f "$DATA_JSON" ]]; then
  echo "--- 1/9 writing episode"
  run_agent "Use the jun-skills:market-note-shorts skill to build the $MARKET market close episode for $DATE.
Produce, with no placeholder values:
  scripts/$SLUG-facts.md, -display.txt, -tts.txt
  scripts/$SLUG-title.txt          one line, the YouTube title
  scripts/$SLUG-youtube-description.txt
  scripts/$SLUG-instagram-caption.txt
  $DATA_JSON                        the episode, matching src/marketNote/types.ts,
                                    with audio set to \"$SLUG-tts.mp3\" and cues omitted
Verify every figure against a primary source. Stop rather than invent a number."
else
  echo "--- 1/9 episode data already present, skipping"
fi

for required in "$DATA_JSON" "$EPISODE/scripts/$SLUG-tts.txt" \
                "$EPISODE/scripts/$SLUG-title.txt" \
                "$EPISODE/scripts/$SLUG-youtube-description.txt" \
                "$EPISODE/scripts/$SLUG-instagram-caption.txt"; do
  [[ -s "$required" ]] || { echo "missing or empty: $required"; exit 1; }
done

# 2. Narration.
AUDIO="$EPISODE/audio/$SLUG-tts.mp3"
if [[ ! -s "$AUDIO" ]]; then
  echo "--- 2/9 synthesising narration"
  node "$SKILL_DIR/scripts/synthesize_tts.mjs" \
    --text "$EPISODE/scripts/$SLUG-tts.txt" --out "$AUDIO" --voice "$ELEVENLABS_VOICE_ID"
fi
cp -f "$AUDIO" "$REMOTION_DIR/public/$SLUG-tts.mp3"

# 3. Measured timing.
TIMING="$EPISODE/qa/timing.json"
if [[ ! -s "$TIMING" ]]; then
  echo "--- 3/9 analysing timing"
  uv run --with faster-whisper python "$SKILL_DIR/scripts/analyze_tts.py" "$AUDIO" --output "$TIMING"
fi

# 4. Which transcript segment opens each scene.
echo "--- 4/9 mapping segments to scenes"
SEGMENTS="$(run_agent "Read $TIMING and $DATA_JSON. The episode has an opening plus one cue
per entry in scenes. Print only the timing.json segment index that starts each, space
separated, ascending, starting at 0. No prose, no trailing text.")"
SEGMENTS="$(tr -cd '0-9 ' <<<"$SEGMENTS" | xargs)"
[[ -n "$SEGMENTS" ]] || { echo "segment mapping returned nothing"; exit 1; }
echo "segments: $SEGMENTS"

# 5. Cue frames.
echo "--- 5/9 deriving cues"
# shellcheck disable=SC2086
python3 "$SKILL_DIR/scripts/build_cues.py" "$TIMING" --scene-segments $SEGMENTS --episode "$DATA_JSON"

# 6. Render.
echo "--- 6/9 rendering"
( cd "$REMOTION_DIR" && npx remotion render src/index.ts MarketNoteVideo "$VIDEO" \
    --props="$DATA_JSON" --concurrency=1 --log=error )

# 7. Gate. Nothing below this line runs on a bad render.
echo "--- 7/9 verifying"
python3 "$SKILL_DIR/scripts/verify_video.py" "$VIDEO" \
  --expected-width 1080 --expected-height 1920 --require-audio
python3 "$INSTAGRAM_SCRIPTS/publish_reels.py" "$VIDEO" \
  --caption-file "$EPISODE/scripts/$SLUG-instagram-caption.txt" --dry-run
ffmpeg -y -v error -i "$VIDEO" -vframes 1 "$EPISODE/assets/thumbnail-$SLUG-reels.png"

# 8. YouTube.
echo "--- 8/9 publishing to YouTube"
python3 "$YOUTUBE_SCRIPTS/upload_video.py" "$VIDEO" \
  --title "$(head -n1 "$EPISODE/scripts/$SLUG-title.txt")" \
  --description-file "$EPISODE/scripts/$SLUG-youtube-description.txt" \
  --privacy "$PRIVACY" --tags "${YOUTUBE_TAGS:-마켓노트,증시마감}"

# 9. Instagram. Instagram Login fetches the file over HTTPS, so stage it, then remove it.
echo "--- 9/9 publishing to Instagram"
gh release create "$STAGING_TAG" --repo "$STAGING_REPO" \
  --title "Instagram media staging $SLUG" --notes "Temporary." "$VIDEO" >/dev/null
python3 "$INSTAGRAM_SCRIPTS/publish_reels.py" "$VIDEO" \
  --caption-file "$EPISODE/scripts/$SLUG-instagram-caption.txt" \
  --video-url "https://github.com/$STAGING_REPO/releases/download/$STAGING_TAG/$(basename "$VIDEO")"
cleanup_staging

echo "=== $SLUG done $(date -u +%FT%TZ) ==="
notify "Market Note $SLUG published to YouTube and Instagram."
