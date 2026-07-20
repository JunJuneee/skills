"""YouTube 채널의 동영상 목록을 가져오는 스크립트"""

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

API_KEY = "AIzaSyB79UBMIqiAuB7860x9PfeBj9FwnayByQY"  # YouTube Data API v3 키를 입력하세요
BASE_URL = "https://www.googleapis.com/youtube/v3"


def get_channel_id(handle: str) -> Optional[str]:
    """채널 핸들(@username)로 채널 ID를 조회합니다."""
    resp = requests.get(f"{BASE_URL}/channels", params={
        "key": API_KEY,
        "forHandle": handle,
        "part": "id",
    })
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return items[0]["id"] if items else None


def get_uploads_playlist_id(channel_id: str) -> Optional[str]:
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


def get_videos(playlist_id: str, since: datetime, max_results: int = 100):
    """재생목록에서 since 이후에 게시된 동영상만 가져옵니다."""
    videos = []
    page_token = None

    while True:
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

        stop = False
        for item in data.get("items", []):
            snippet = item["snippet"]
            published = datetime.fromisoformat(
                snippet["publishedAt"].replace("Z", "+00:00"))
            if published < since:
                stop = True
                break
            videos.append({
                "title": snippet["title"],
                "video_id": snippet["resourceId"]["videoId"],
                "url": f"https://www.youtube.com/watch?v={snippet['resourceId']['videoId']}",
                "published_at": snippet["publishedAt"],
                "description": snippet["description"][:100],
            })

        page_token = data.get("nextPageToken")
        if stop or not page_token or len(videos) >= max_results:
            break

    # video ID로 duration 조회
    if videos:
        for i in range(0, len(videos), 50):
            batch = videos[i:i+50]
            ids = ",".join(v["video_id"] for v in batch)
            resp = requests.get(f"{BASE_URL}/videos", params={
                "key": API_KEY,
                "id": ids,
                "part": "contentDetails",
            })
            resp.raise_for_status()
            durations = {item["id"]: item["contentDetails"]["duration"]
                         for item in resp.json().get("items", [])
                         if "duration" in item.get("contentDetails", {})}
            for v in batch:
                v["duration"] = parse_duration(
                    durations.get(v["video_id"], "PT0S"))

    return videos


def parse_duration(iso_duration: str) -> str:
    """ISO 8601 duration (PT1H2M3S) -> '1:02:03' 형식으로 변환"""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not m:
        return "0:00"
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def duration_to_seconds(duration_str: str) -> int:
    """'1:02:03' 또는 '2:03' 형식의 duration을 초 단위로 변환"""
    parts = duration_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def get_existing_source_ids(collection_id, bearer_token):
    """Lilys API에서 해당 collection의 기존 sourceId 목록을 가져옵니다."""
    resp = requests.get(
        "https://api.lilys.ai/backend/digest-sessions",
        headers={"Authorization": bearer_token},
        params={
            "provider": "google",
            "collectionId": collection_id,
            "page": 0,
            "sortType": "newest",
        },
    )
    if not resp.ok:
        print(f"   Lilys 기존 목록 조회 실패 ({resp.status_code})")
        return set()
    sessions = resp.json().get("digestSessions", [])
    return {
        s["sessionData"]["data"]["sourceId"]
        for s in sessions
        if s.get("sessionData", {}).get("data", {}).get("sourceId")
    }


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
    channels = [
        {"channel_id": "UChlv4GSd7OQl3js-jkLOnFA",
            "name": "삼프로TV", "collection_id": 145430},
        {"channel_id": "UCIUni4ScRp4mqPXsxy62L5w",
            "name": "언더스탠딩", "collection_id": 145430},
        {"channel_id": "UCxfko2YOD6DODYRGzeOPhIQ",
            "name": "머니인사이드", "collection_id": 145430},
        {"channel_id": "UCA_hgsFzmynpv1zkvA5A7jA",
         "name": "지식인사이드", "collection_id": 145430},
        {"channel_id": "UCiYbaVEODktcsh09454Grow",
            "name": "손에잡히는경제", "collection_id": 145430},
        {"channel_id": "UCpqD9_OJNtF6suPpi6mOQCQ",
         "name": "월가아재의 과학적 투자", "collection_id": 145430},
        {"channel_id": "UCelFN6fJ6OY6v8pbc_SLiXA",
            "name": "티타임즈TV", "collection_id": 145431},
        {"channel_id": "UCRl4mTjvAUCoSZcb83HQ_sg",
         "name": "아웃스탠딩", "collection_id": 145431},
        {"channel_id": "UCWgXoKQ4rl7SY9UHuAwxvzQ",
         "name": "BZCF | 비즈까페", "collection_id": 145431},
        {"channel_id": "UCwAnu01qlnVg1Ai2AbtTMaA",
            "name": "Jeff Su", "collection_id": 145432},
        {"channel_id": "UCO0vOSFeZC-GLJOYtCZwyvQ",
            "name": "Eugene Kadzin", "collection_id": 145432},
        {"channel_id": "UCui4jxDaMb53Gdh-AZUTPAg",
            "name": "Liam Ottley", "collection_id": 145432},
        {"channel_id": "UCIg2taLnC9X6LRP1k3kukOA",
            "name": "Jack Roberts", "collection_id": 145432},
        {"channel_id": "UCxVxcTULO9cFU6SB9qVaisQ",
            "name": "Stephen G. Pope", "collection_id": 145432},
        {"channel_id": "UCnzxPyNnn8jk4bHFk3JUBhA",
            "name": "Jono Catliff", "collection_id": 145432},
        {"channel_id": "UCbo-KbSjJDG6JWQ_MTZ_rNA",
            "name": "Nick Saraev", "collection_id": 145432},
        {"channel_id": "UCdd-Xj9HNn-rIURJGnnCBJg",
            "name": "헤이제임스", "collection_id": 145432},
        {"channel_id": "UCbHmDkgh2oHWcN7e28QnIFw",
            "name": "임커밋", "collection_id": 145432},
        {"channel_id": "UCLKPca3kwwd-B59HNr-_lvA",
         "name": "AI Engineer", "collection_id": 145432},
        {"channel_id": "UCrDwWp7EBBv4NwvScIpBDOA",
         "name": "Anthropic", "collection_id": 145432},
        {"channel_id": "UC6t1O76G0jYXOAoYCm153dA",
         "name": "Lenny’s podcast", "collection_id": 145432},
        {"channel_id": "UCRYY7IEbkHLH_ScJCu9eWDQ",
         "name": "How I AI", "collection_id": 145432},
        {"channel_id": "UCz-BiVywYdO6iXhjXkw_Kgw",
         "name": "노정석", "collection_id": 145432},
        {"channel_id": "UCdwVtI_TclbVf7QRC_hvc_Q",
         "name": "sudoremove", "collection_id": 145432},
        {"channel_id": "UC94-KOOG6y4FW6SKHgIPQOg",
            "name": "J TV", "collection_id": 151255},
        {"channel_id": "UC7uFGmwzzXok18RdOh9FDfQ",
         "name": "알고란", "collection_id": 154987}
    ]

    # 1순위: 환경변수, 2순위: token.txt 파일
    bearer_token = os.environ.get("BEARER_TOKEN")
    if not bearer_token:
        token_path = os.path.join(os.path.dirname(__file__), "token.txt")
        if os.path.exists(token_path):
            with open(token_path, "r") as f:
                bearer_token = f.read().strip()
            print(f"token.txt에서 토큰을 읽었습니다.")
        else:
            print(f"token.txt 파일을 생성해주세요: {token_path}")
            print("내용: Bearer eyJ...")
            return

    since = datetime.now(timezone.utc) - timedelta(days=2)

    # collection_id별로 기존 sourceId를 한 번만 조회
    existing_by_collection = {}
    unique_collection_ids = {ch["collection_id"] for ch in channels}
    for cid in unique_collection_ids:
        existing_by_collection[cid] = get_existing_source_ids(
            cid, bearer_token)
        print(f"컬렉션 {cid}: 기존 {len(existing_by_collection[cid])}건 로드")

    for ch in channels:
        print(f"\n{'=' * 60}")
        print(f"채널: {ch['name']} ({ch['channel_id']})")
        print(f"{'=' * 60}")

        playlist_id = get_uploads_playlist_id(ch["channel_id"])
        if not playlist_id:
            print("업로드 재생목록을 찾을 수 없습니다.\n")
            continue

        videos = get_videos(playlist_id, since=since)
        # 오래된 순서로 정렬
        videos.sort(key=lambda v: v["published_at"])
        print(f"최근 1일 이내 동영상: {len(videos)}개\n")

        for i, video in enumerate(videos, 1):
            print(f"{i}. {video['title']}")
            print(f"   URL: {video['url']}  ({video['duration']})")

            if duration_to_seconds(video["duration"]) >= 3 * 3600:
                print(f"   -> 스킵 (3시간 이상 영상)")
                print()
                continue

            if duration_to_seconds(video["duration"]) <= 5 * 60:
                print(f"   -> 스킵 (5분 미만 이상 영상)")
                print()
                continue

            if video["video_id"] in existing_by_collection.get(ch["collection_id"], set()):
                print(f"   -> 스킵 (이미 등록된 영상)")
                print()
                continue

            resp = send_to_lilys(
                video, ch["collection_id"], ch["name"], bearer_token)
            if resp.ok:
                print(f"   -> Lilys 요청 성공 ({resp.status_code})")
            else:
                print(
                    f"   -> Lilys 요청 실패 ({resp.status_code}: {resp.text[:100]})")
            print()


if __name__ == "__main__":
    main()
