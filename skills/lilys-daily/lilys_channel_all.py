"""YouTube 채널의 전체 라이브 방송을 Lilys로 요약 요청하는 스크립트

사용법:
  python3 lilys_channel_all.py
"""

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

API_KEY = "AIzaSyB79UBMIqiAuB7860x9PfeBj9FwnayByQY"
BASE_URL = "https://www.googleapis.com/youtube/v3"

CHANNEL_ID = "UCywP4xzKn0o19sPVoL8P3gQ"
CHANNEL_NAME = "닥치고차트tv"
COLLECTION_ID = 147771
MAX_WORKERS = 5


def get_bearer_token():
    """Bearer 토큰을 환경변수 또는 token.txt에서 가져옵니다."""
    token = os.environ.get("BEARER_TOKEN")
    if token:
        return token
    token_path = os.path.join(os.path.dirname(__file__), "token.txt")
    if os.path.exists(token_path):
        with open(token_path, "r") as f:
            return f.read().strip()
    print(f"token.txt 파일을 생성해주세요: {token_path}")
    print("내용: Bearer eyJ...")
    sys.exit(1)


def fetch_all_live_videos(channel_id: str) -> list:
    """채널의 모든 완료된 라이브 방송 목록을 가져옵니다."""
    videos = []
    page_token = None
    page = 0

    while True:
        page += 1
        params = {
            "key": API_KEY,
            "channelId": channel_id,
            "part": "id,snippet",
            "eventType": "completed",
            "type": "video",
            "maxResults": 50,
            "order": "date",
        }
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(f"{BASE_URL}/search", params=params)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            vid = item["id"]["videoId"]
            videos.append({
                "video_id": vid,
                "title": item["snippet"]["title"],
                "url": f"https://www.youtube.com/watch?v={vid}",
                "published_at": item["snippet"]["publishedAt"],
            })

        total = data.get("pageInfo", {}).get("totalResults", 0)
        print(f"  페이지 {page}: {len(videos)}/{total}건 수집")

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return videos


def get_existing_source_ids(collection_id, bearer_token):
    """Lilys에서 해당 collection의 기존 sourceId 목록을 모두 가져옵니다."""
    existing = set()
    page = 0

    while True:
        resp = requests.get(
            "https://api.lilys.ai/backend/digest-sessions",
            headers={"Authorization": bearer_token},
            params={
                "provider": "google",
                "collectionId": collection_id,
                "page": page,
                "sortType": "newest",
            },
        )
        if not resp.ok:
            print(f"  Lilys 기존 목록 조회 실패 ({resp.status_code})")
            break

        sessions = resp.json().get("digestSessions", [])
        if not sessions:
            break

        for s in sessions:
            source_id = s.get("sessionData", {}).get(
                "data", {}).get("sourceId")
            if source_id:
                existing.add(source_id)

        page += 1

    return existing


def send_to_lilys(video, collection_id, channel_name, bearer_token):
    """Lilys API로 동영상 요약 요청을 보냅니다."""
    resp = requests.post(
        "https://api.lilys.ai/backend/lazy-digest-session",
        headers={
            "Authorization": bearer_token,
            "Content-Type": "application/json",
        },
        json={
            "url": video["url"],
            "title": f"{video['title']} - {channel_name}",
            "provider": "google",
            "collectionId": collection_id,
            "sourceType": "youtube_video",
            "sourceId": video["video_id"],
            "shouldStartImmediately": True,
        },
    )
    return resp


def process_video(video, collection_id, channel_name, bearer_token):
    """단일 동영상을 Lilys에 요청합니다."""
    try:
        resp = send_to_lilys(video, collection_id, channel_name, bearer_token)
        if resp.ok:
            return {"video_id": video["video_id"], "status": "ok"}
        return {
            "video_id": video["video_id"],
            "status": "fail",
            "reason": f"{resp.status_code}: {resp.text[:100]}",
        }
    except Exception as e:
        return {
            "video_id": video["video_id"],
            "status": "fail",
            "reason": str(e)[:100],
        }


def main():
    bearer_token = get_bearer_token()

    print(f"채널: {CHANNEL_NAME} ({CHANNEL_ID})")
    print(f"Collection ID: {COLLECTION_ID}")
    print()

    # 1) 라이브 방송 목록 수집
    print("=== 라이브 방송 목록 수집 ===")
    videos = fetch_all_live_videos(CHANNEL_ID)
    print(f"총 {len(videos)}개 라이브 방송 발견\n")

    if not videos:
        print("라이브 방송이 없습니다.")
        return

    # 2) 기존 등록 목록 조회
    print("=== 기존 등록 영상 확인 ===")
    existing = get_existing_source_ids(COLLECTION_ID, bearer_token)
    print(f"  기존 등록: {len(existing)}건")

    # 오래된 순서로 정렬
    videos.sort(key=lambda v: v["published_at"])

    # 중복 제거
    new_videos = [v for v in videos if v["video_id"] not in existing]
    skipped = len(videos) - len(new_videos)
    print(f"  신규 요청 대상: {len(new_videos)}건 (스킵: {skipped}건)\n")

    if not new_videos:
        print("모든 영상이 이미 등록되어 있습니다.")
        return

    # 3) Lilys 요청 (병렬)
    print(f"=== Lilys 요청 (병렬 {MAX_WORKERS}개) ===")
    results = {"ok": 0, "fail": 0}
    failures = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                process_video, video, COLLECTION_ID, CHANNEL_NAME, bearer_token
            ): video
            for video in new_videos
        }

        for i, future in enumerate(as_completed(futures), 1):
            video = futures[future]
            result = future.result()
            status = result["status"]
            results[status] += 1

            icon = "O" if status == "ok" else "X"
            detail = result.get("reason", "")
            print(
                f"  [{icon}] ({i}/{len(new_videos)}) {video['title'][:60]}  {detail}")

    # 4) 결과 요약
    print(f"\n=== 결과 요약 ===")
    print(f"  성공: {results['ok']}건")
    print(f"  스킵: {skipped}건 (이미 등록됨)")
    print(f"  실패: {results['fail']}건")


if __name__ == "__main__":
    main()
