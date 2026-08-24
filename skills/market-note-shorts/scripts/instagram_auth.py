#!/usr/bin/env python3
"""Manage Instagram Graph API credentials for Market Note reel publishing.

Subcommands:
  whoami    Verify the stored token and show the connected professional account.
  exchange  Trade a short-lived token from the Meta app dashboard for a 60-day token.
  refresh   Extend an unexpired long-lived token for another 60 days.

Credentials resolve in this order: --access-token, IG_ACCESS_TOKEN, the config file.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".config" / "market-note" / "instagram.json"
GRAPH_HOSTS = {"instagram": "graph.instagram.com", "facebook": "graph.facebook.com"}
API_VERSION = "v23.0"


class ApiError(Exception):
    def __init__(self, status: int, path: str, body: str) -> None:
        super().__init__(f"Instagram API error {status} on GET /{path}: {body}")
        self.status = status
        try:
            self.code = json.loads(body).get("error", {}).get("code")
        except json.JSONDecodeError:
            self.code = None


def api_get(host: str, path: str, params: dict) -> dict:
    url = f"https://{host}/{API_VERSION}/{path.lstrip('/')}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise ApiError(error.code, path, error.read().decode("utf-8", "replace")) from error


def load_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"Config file is not valid JSON: {path} ({error})") from error


def save_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def resolve_token(args, config: dict) -> str:
    token = args.access_token or os.environ.get("IG_ACCESS_TOKEN") or config.get("access_token")
    if not token:
        raise SystemExit(
            "No access token. Pass --access-token, set IG_ACCESS_TOKEN, "
            "or run 'instagram_auth.py exchange' first."
        )
    return token


def store_token(config_path: Path, config: dict, token: str, expires_in: int | None) -> None:
    config["access_token"] = token
    if expires_in:
        expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        config["expires_at"] = expiry.isoformat()
        print(f"Token stored. Expires {expiry.date()} ({expires_in // 86400} days).")
    else:
        config.pop("expires_at", None)
        print("Token stored. No expiry reported.")
    save_config(config_path, config)
    print(f"Config: {config_path}")


def cmd_whoami(args, config_path: Path, config: dict) -> int:
    token = resolve_token(args, config)
    host = GRAPH_HOSTS[args.login_type]
    fields = "user_id,username,account_type" if args.login_type == "instagram" else "id,username"
    profile = api_get(host, "me", {"fields": fields, "access_token": token})
    user_id = profile.get("user_id") or profile.get("id")
    print(f"username     : {profile.get('username')}")
    print(f"ig_user_id   : {user_id}")
    if profile.get("account_type"):
        print(f"account_type : {profile['account_type']}")
    if config.get("expires_at"):
        print(f"token_expires: {config['expires_at']}")
    if user_id and config.get("ig_user_id") != user_id:
        config["ig_user_id"] = user_id
        save_config(config_path, config)
        print(f"Saved ig_user_id to {config_path}")
    return 0


def cmd_exchange(args, config_path: Path, config: dict) -> int:
    short_token = args.access_token or os.environ.get("IG_ACCESS_TOKEN")
    if not short_token:
        raise SystemExit("Pass the short-lived token via --access-token or IG_ACCESS_TOKEN.")
    app_secret = args.app_secret or os.environ.get("IG_APP_SECRET") or config.get("app_secret")
    if not app_secret:
        raise SystemExit("Pass the app secret via --app-secret or IG_APP_SECRET.")

    if args.login_type == "instagram":
        try:
            payload = api_get(
                GRAPH_HOSTS["instagram"],
                "access_token",
                {
                    "grant_type": "ig_exchange_token",
                    "client_secret": app_secret,
                    "access_token": short_token,
                },
            )
        except ApiError as error:
            # The App Dashboard now hands out 60-day tokens directly, and those cannot be
            # exchanged again. Keep the token we were given rather than failing the setup.
            if error.code != 452:
                raise
            print("Token is already long-lived; storing it as-is.")
            config["login_type"] = args.login_type
            if args.save_app_secret:
                config["app_secret"] = app_secret
            store_token(config_path, config, short_token, None)
            return 0
    else:
        if not args.app_id:
            raise SystemExit("Facebook login exchange also needs --app-id.")
        payload = api_get(
            GRAPH_HOSTS["facebook"],
            "oauth/access_token",
            {
                "grant_type": "fb_exchange_token",
                "client_id": args.app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            },
        )

    config["login_type"] = args.login_type
    if args.save_app_secret:
        config["app_secret"] = app_secret
    store_token(config_path, config, payload["access_token"], payload.get("expires_in"))
    return 0


def cmd_refresh(args, config_path: Path, config: dict) -> int:
    token = resolve_token(args, config)
    if args.login_type != "instagram":
        raise SystemExit(
            "refresh only applies to Instagram Login tokens. Long-lived Facebook Page "
            "tokens do not expire on a 60-day clock; re-run exchange if the token broke."
        )
    payload = api_get(
        GRAPH_HOSTS["instagram"],
        "refresh_access_token",
        {"grant_type": "ig_refresh_token", "access_token": token},
    )
    store_token(config_path, config, payload["access_token"], payload.get("expires_in"))
    return 0


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    common.add_argument("--login-type", choices=sorted(GRAPH_HOSTS), default="instagram")
    common.add_argument("--access-token")
    common.add_argument("--app-secret")
    common.add_argument("--app-id")
    common.add_argument(
        "--save-app-secret",
        action="store_true",
        help="Persist the app secret in the config file so refresh runs unattended.",
    )

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("whoami", parents=[common], help="Verify the token and show the account")
    subparsers.add_parser("exchange", parents=[common], help="Short-lived token to 60-day token")
    subparsers.add_parser("refresh", parents=[common], help="Extend a long-lived token")
    args = parser.parse_args()

    config_path = args.config.expanduser()
    config = load_config(config_path)
    if args.login_type == "instagram" and config.get("login_type") == "facebook":
        args.login_type = "facebook"

    handlers = {"whoami": cmd_whoami, "exchange": cmd_exchange, "refresh": cmd_refresh}
    try:
        return handlers[args.command](args, config_path, config)
    except ApiError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    raise SystemExit(main())
