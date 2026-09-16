#!/usr/bin/env python3
"""Authorize a local YouTube uploader using desktop OAuth with PKCE."""

import argparse
import base64
import hashlib
import json
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from common import save_credentials


REDIRECT_URI = "http://127.0.0.1:8765/"
SCOPES = {
    "upload": ("https://www.googleapis.com/auth/youtube.upload",),
    "manage": (
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    ),
}


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def exchange_code(values: dict[str, str]) -> dict:
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(values).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secrets", type=Path, required=True)
    parser.add_argument("--mode", choices=SCOPES, default="manage")
    args = parser.parse_args()
    raw = json.loads(args.client_secrets.read_text(encoding="utf-8"))
    client = raw.get("installed") or raw.get("web") or {}
    client_id = client.get("client_id", "")
    client_secret = client.get("client_secret", "")
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise SystemExit("The OAuth JSON does not contain a valid desktop client ID.")

    verifier = secrets.token_urlsafe(72)
    state = secrets.token_urlsafe(24)
    received: dict[str, str] = {}
    complete = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid OAuth state. You can close this tab.")
                return
            received.update({key: value[0] for key, value in query.items() if value})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>YouTube authorization complete</h2><p>You can close this tab.</p>".encode())
            complete.set()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 8765), Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    parameters = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES[args.mode]),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge(verifier),
        "code_challenge_method": "S256",
    }
    print("Opening browser for YouTube authorization...")
    webbrowser.open("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(parameters))
    if not complete.wait(timeout=300):
        server.shutdown()
        raise SystemExit("Authorization timed out after 5 minutes.")
    server.shutdown()
    if "error" in received or "code" not in received:
        raise SystemExit(f"Authorization did not complete: {received.get('error', 'no code returned')}")
    request_values = {
        "client_id": client_id,
        "code": received["code"],
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    if client_secret:
        request_values["client_secret"] = client_secret
    tokens = exchange_code(request_values)
    if "refresh_token" not in tokens:
        raise SystemExit("Google did not issue a refresh token. Run authorization again.")
    save_credentials(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": tokens["refresh_token"],
            "token_uri": "https://oauth2.googleapis.com/token",
            "mode": args.mode,
        }
    )
    print("Authorization saved locally.")


if __name__ == "__main__":
    main()
