"""YouTube 채널의 전체 동영상을 Lilys로 요약 요청하는 스크립트 (순차 처리, 오래된 순)

사용법:
  python3 lilys_channel_all_seq.py
"""

import os
import sys
import time

import requests

API_KEY = "AIzaSyB79UBMIqiAuB7860x9PfeBj9FwnayByQY"
BASE_URL = "https://www.googleapis.com/youtube/v3"

CHANNEL_ID = "UC94-KOOG6y4FW6SKHgIPQOg"
CHANNEL_NAME = "J TV"
COLLECTION_ID = 151255


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


def get_uploads_playlist_id(channel_id: str):
    """채널의 업로드 재생목록 ID를 가져옵니다."""
    resp = requests.get(f"{BASE_URL}/channels", params={
        "key": API_KEY,
        "id": channel_id,
        "part": "contentDetails",
    })
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def fetch_all_videos(channel_id: str) -> list:
    """채널의 모든 동영상 목록을 가져옵니다."""
    playlist_id = get_uploads_playlist_id(channel_id)
    if not playlist_id:
        print("  업로드 재생목록을 찾을 수 없습니다.")
        return []

    videos = []
    page_token = None
    page = 0

    while True:
        page += 1
        params = {
            "key": API_KEY,
            "playlistId": playlist_id,
            "part": "snippet",
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(f"{BASE_URL}/playlistItems", params=params)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            snippet = item["snippet"]
            vid = snippet["resourceId"]["videoId"]
            videos.append({
                "video_id": vid,
                "title": snippet["title"],
                "url": f"https://www.youtube.com/watch?v={vid}",
                "published_at": snippet["publishedAt"],
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


def main():
    bearer_token = get_bearer_token()

    print(f"채널: {CHANNEL_NAME} ({CHANNEL_ID})")
    print(f"Collection ID: {COLLECTION_ID}")
    print()

    # 1) 전체 동영상 목록 수집
    print("=== 전체 동영상 목록 수집 ===")
    videos = fetch_all_videos(CHANNEL_ID)
    print(f"총 {len(videos)}개 동영상 발견\n")

    if not videos:
        print("동영상이 없습니다.")
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

    # 3) Lilys 요청 (순차 처리 - 오래된 순)
    print("=== Lilys 요청 (순차 처리, 오래된 순) ===")
    ok_count = 0
    fail_count = 0

    for i, video in enumerate(new_videos, 1):
        try:
            resp = send_to_lilys(video, COLLECTION_ID,
                                 CHANNEL_NAME, bearer_token)
            if resp.ok:
                ok_count += 1
                print(f"  [O] ({i}/{len(new_videos)}) {video['title'][:60]}")
            else:
                fail_count += 1
                print(
                    f"  [X] ({i}/{len(new_videos)}) {video['title'][:60]}  {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            fail_count += 1
            print(
                f"  [X] ({i}/{len(new_videos)}) {video['title'][:60]}  {str(e)[:100]}")

        # API 부하 방지를 위한 짧은 대기
        if i < len(new_videos):
            time.sleep(1)

    # 4) 결과 요약
    print(f"\n=== 결과 요약 ===")
    print(f"  성공: {ok_count}건")
    print(f"  스킵: {skipped}건 (이미 등록됨)")
    print(f"  실패: {fail_count}건")


if __name__ == "__main__":
    main()
