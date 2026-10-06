#!/usr/bin/env python3
"""YouTube URL → 정리된 자막 텍스트 + 메타데이터 + 저장할 노트 경로.

usage:
  python3 fetch_transcript.py URL [--notes-dir ~/notes/youtube] [--bucket 60]
                                  [--cookies-from-browser chrome]

stdout에 JSON 한 개를 출력한다. 요약은 하지 않는다(요약은 에이전트 몫).

exit codes:
  0 성공
  2 입력 오류(URL 아님, yt-dlp 미설치)
  3 yt-dlp 실패(네트워크·봇 차단·비공개 영상)
  4 쓸 수 있는 자막 없음
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

YT_URL = re.compile(r"^https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", re.I)
TS = re.compile(r"^(\d+):(\d+):(\d+)\.\d+ -->")
TAG = re.compile(r"<[^>]+>")
FALLBACK_LANGS = ["ko", "en"]


def fail(code, msg, **extra):
    print(json.dumps({"ok": False, "error": msg, **extra}, ensure_ascii=False))
    sys.exit(code)


def run_ytdlp(args, cookies, attempts=1):
    cmd = ["yt-dlp", "--no-playlist", "--no-warnings"]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    for i in range(attempts):
        proc = subprocess.run(cmd + args, capture_output=True, text=True)
        if proc.returncode == 0:
            break
        if i + 1 < attempts:
            time.sleep(3)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip().splitlines()
        first = next((l for l in err if l.startswith("ERROR")), err[-1] if err else "")
        hint = None
        if "Sign in to confirm" in first or "bot" in first.lower():
            hint = "봇 차단 — --cookies-from-browser chrome 으로 재시도"
        fail(3, first[:300], hint=hint)
    return proc.stdout


def pick_track(meta):
    """(kind, lang) — 사람이 올린 자막 > 원어 자동자막 > 번역 자동자막."""
    manual = meta.get("subtitles") or {}
    auto = meta.get("automatic_captions") or {}
    lang = (meta.get("language") or "").split("-")[0]
    order = ([lang] if lang else []) + [l for l in FALLBACK_LANGS if l != lang]

    for l in order:
        for key in manual:
            if key == l or key.startswith(l + "-"):
                return "manual", key
    for l in order:
        # 자동자막의 "<lang>-orig"가 원음 인식본이고 "<lang>"은 번역일 수 있다
        for key in (f"{l}-orig", l):
            if key in auto:
                return "auto", key
    return None, None


def clean_vtt(path, bucket):
    start, seen, groups = 0, set(), {}
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        m = TS.match(line)
        if m:
            h, mi, s = map(int, m.groups())
            start = h * 3600 + mi * 60 + s
            continue
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in line:
            continue
        # ">>"는 화자 전환 표시 — 요약에 노이즈라 지운다
        text = html.unescape(TAG.sub("", line)).replace(">>", "").strip()
        # 자동자막은 같은 줄이 롤링되며 2~3번 반복된다
        if text and text not in seen:
            seen.add(text)
            groups.setdefault(start // bucket * bucket, []).append(text)
    out = []
    for t in sorted(groups):
        h, rest = divmod(t, 3600)
        stamp = f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60:02d}:{rest % 60:02d}"
        out.append(f"[{stamp}] " + " ".join(groups[t]))
    return "\n".join(out) + "\n"


def slugify(title, limit=50):
    s = re.sub(r"[\"'‘’“”]", "", title)
    s = re.sub(r"[\\/:*?<>|#,\[\]\n\r\t]", " ", s)
    s = re.sub(r"\s+", "-", s.strip())
    if len(s) > limit:
        cut = s[:limit]
        # 단어 중간에서 끊기지 않게 마지막 "-"까지 자른다
        s = cut[: cut.rfind("-")] if cut.rfind("-") > limit // 2 else cut
    return s.rstrip("-.") or "untitled"


def find_existing(notes_dir, video_id):
    if not notes_dir.is_dir():
        return None
    needle = f"video_id: {video_id}"
    for p in sorted(notes_dir.glob("*.md")):
        try:
            head = p.read_text(encoding="utf-8")[:2000]
        except OSError:
            continue
        if needle in head:
            return str(p)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--notes-dir", default="~/notes/youtube")
    ap.add_argument("--bucket", type=int, default=60, help="타임스탬프 단락 간격(초)")
    ap.add_argument("--cookies-from-browser", default=None)
    a = ap.parse_args()

    if not YT_URL.match(a.url):
        fail(2, "YouTube URL이 아니다")
    if not shutil.which("yt-dlp"):
        fail(2, "yt-dlp가 없다 — brew install yt-dlp")

    meta = json.loads(run_ytdlp(["-J", a.url], a.cookies_from_browser))
    vid = meta["id"]
    kind, track = pick_track(meta)
    if not track:
        fail(4, "쓸 수 있는 자막이 없다(사람 자막·자동자막 모두 없음)", video_id=vid,
             title=meta.get("title"))

    work = Path(tempfile.gettempdir()) / "yt-summary" / vid
    work.mkdir(parents=True, exist_ok=True)
    flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
    run_ytdlp(["--skip-download", flag, "--sub-langs", track, "--sub-format", "vtt",
               "-o", str(work / "%(id)s"), a.url], a.cookies_from_browser,
              attempts=2)  # 자막 URL이 간헐적으로 404를 낸다(실측)
    vtt = work / f"{vid}.{track}.vtt"
    if not vtt.exists():
        fail(4, f"자막 파일이 생성되지 않았다({track})", video_id=vid)

    transcript = clean_vtt(vtt, a.bucket)
    tpath = work / "transcript.txt"
    tpath.write_text(transcript, encoding="utf-8")

    notes_dir = Path(os.path.expanduser(a.notes_dir))
    up = meta.get("upload_date") or date.today().strftime("%Y%m%d")
    up_iso = f"{up[:4]}-{up[4:6]}-{up[6:8]}"
    note = notes_dir / f"{up_iso}_{slugify(meta.get('title', vid))}.md"
    if note.exists() and vid not in note.read_text(encoding="utf-8")[:2000]:
        note = note.with_name(f"{note.stem}_{vid}.md")

    print(json.dumps({
        "ok": True,
        "video_id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "title": meta.get("title"),
        "channel": meta.get("channel") or meta.get("uploader"),
        "upload_date": up_iso,
        "duration": meta.get("duration_string"),
        "language": meta.get("language"),
        "caption_kind": kind,
        "caption_track": track,
        "transcript_path": str(tpath),
        "transcript_chars": len(transcript),
        "note_path": str(note),
        "existing_note": find_existing(notes_dir, vid),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
