#!/usr/bin/env python3
"""Shared OAuth helpers for the YouTube Video Publisher skill."""

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path


STATE_DIR = Path.home() / ".codex" / "youtube-video-publisher"
TOKEN_PATH = STATE_DIR / "oauth.json"


def save_credentials(credentials: dict) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(credentials, indent=2) + "\n", encoding="utf-8")
    os.chmod(TOKEN_PATH, 0o600)


def load_credentials() -> dict:
    if not TOKEN_PATH.is_file():
        raise SystemExit("No YouTube OAuth token found. Run scripts/authorize.py first.")
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))


def post_form(url: str, values: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def access_token() -> str:
    credentials = load_credentials()
    values = {
        "client_id": credentials["client_id"],
        "refresh_token": credentials["refresh_token"],
        "grant_type": "refresh_token",
    }
    if credentials.get("client_secret"):
        values["client_secret"] = credentials["client_secret"]
    return post_form(credentials["token_uri"], values)["access_token"]
