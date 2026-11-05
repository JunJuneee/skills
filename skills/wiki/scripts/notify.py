"""notify (T5, D17 + panel D-7): one fixed-wording Slack line per absorb run.
Python 3.9, stdlib only.

The line carries counts and a reason code only, never page titles, source
text or warning strings. Four states:

  success  status ok      "위키: 반영 12 · 새 페이지 2 · 격리 1 · 전역 선호 +1/−0"
  zero     status empty   "위키: 반영 0 · 격리 1"
  failure  status failed  "위키: 실패 (claude_flags_missing)"
  held     status held    "위키: 한도 보류 · 반영 3 · 새 페이지 0 · 격리 0 · 전역 선호 +0/−0 · 실패 1"

Sending (panel D-7 B): chat.postMessage through urllib. The bot token comes
from `token_cmd`, an argv list run without a shell (for example
["doppler", "secrets", "get", "SLACK_BOT_TOKEN", "--plain", "--project", "<p>",
"--config", "<c>"]); it must start with xoxb-. The token never reaches a
log, the ledger or an exception message.

Configuration: WIKI_ROOT/notify.json when it exists (local, gitignored),
else the `notify` block of settings.json. Both use the same keys,
`slack_channel` (a channel ID) and `token_cmd`. Either one empty means
log-only: the line is kept in the .state ledger and nothing is sent. A send
failure never changes the absorb result; only its reason code is recorded.
"""

import collections
import json
import os
import re
import shutil
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import common  # noqa: E402

NOTIFY_FILE = "notify.json"
SLACK_URL = "https://slack.com/api/chat.postMessage"
TOKEN_TIMEOUT = 20
HTTP_TIMEOUT = 15

STATE_SUCCESS = "success"
STATE_ZERO = "zero"
STATE_FAILURE = "failure"
STATE_HELD = "held"

MODE_SLACK = "slack"
MODE_LOG_ONLY = "log_only"

_REASON_RE = re.compile(r"^[a-z0-9_:.-]{1,64}$")
_CHANNEL_RE = re.compile(r"^[CGD][A-Z0-9]{6,20}$")
_TOKEN_RE = re.compile(r"^xoxb-[A-Za-z0-9-]{10,250}$")


class NotifyError(common.WikiError):
    """A send failure. The message is a fixed phrase, never the token."""


# ---------------------------------------------------------------------------
# The line
# ---------------------------------------------------------------------------

def _count(value):
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def safe_reason(reason):
    """A reason code for the line, or `unknown` for anything free-form."""
    if isinstance(reason, str) and _REASON_RE.match(reason):
        return reason
    return "unknown"


def classify(report):
    status = (report or {}).get("status")
    if status == "ok":
        return STATE_SUCCESS
    if status == "empty":
        return STATE_ZERO
    if status == "held":
        return STATE_HELD
    return STATE_FAILURE


def format_line(report):
    """The fixed-wording line, built only from integers and a reason code."""
    report = report or {}
    state = classify(report)
    if state == STATE_FAILURE:
        return "위키: 실패 (%s)" % safe_reason(report.get("reason"))
    quarantined = _count(report.get("quarantined"))
    if state == STATE_ZERO:
        return "위키: 반영 0 · 격리 %d" % quarantined
    batches = report.get("batches") if isinstance(report.get("batches"), list) else []
    failed = len([b for b in batches if isinstance(b, dict) and not b.get("ok")])
    deferred = len([b for b in batches if isinstance(b, dict) and b.get("deferred")])
    parts = ["반영 %d" % _count(report.get("applied")),
             "새 페이지 %d" % _count(report.get("new_pages")),
             "격리 %d" % quarantined,
             "전역 선호 +%d/−%d" % (_count(report.get("rules_added")),
                                   _count(report.get("rules_removed")))]
    if failed:
        parts.append("실패 %d" % failed)
    if deferred:
        parts.append("보류 %d" % deferred)
    elif isinstance(report.get("deferred_files"), list) and report["deferred_files"]:
        parts.append("보류 파일 %d" % len(report["deferred_files"]))
    prefix = "위키: 한도 보류 · " if state == STATE_HELD else "위키: "
    return prefix + " · ".join(parts)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def notify_path(root):
    return os.path.join(root, NOTIFY_FILE)


def _validate(block, where):
    if not isinstance(block, dict):
        raise common.ConfigError("notify_config_invalid", "%s must be a JSON object" % where)
    channel = block.get("slack_channel", "")
    token_cmd = block.get("token_cmd", [])
    if not isinstance(channel, str):
        raise common.ConfigError("notify_config_invalid", "%s: slack_channel must be a string" % where)
    if not isinstance(token_cmd, list) or not all(isinstance(a, str) and a for a in token_cmd):
        raise common.ConfigError("notify_config_invalid",
                                 "%s: token_cmd must be an argv list of strings" % where)
    config = collections.OrderedDict()
    config["source"] = where
    config["slack_channel"] = channel.strip()
    config["token_cmd"] = list(token_cmd)
    return config


def load_config(root, settings=None):
    """The notify config, with `source` naming where it came from.
    `enabled` is False (log-only) when the channel or token_cmd is empty."""
    path = notify_path(root)
    if os.path.exists(path):
        config = _validate(common.load_json_file(path, "notify_config_invalid"), NOTIFY_FILE)
    else:
        if settings is None:
            settings = common.load_settings(root)
        config = _validate(settings.get("notify") or {}, "settings.json notify")
    config["enabled"] = bool(config["slack_channel"] and config["token_cmd"])
    return config


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

# Where a token_cmd program (doppler, op, ...) usually lives when the
# launchd PATH (claude's folder + system folders) does not hold it, e.g. when
# notify was configured after `schedule install`.
FALLBACK_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")


def resolve_program(name, environ):
    """Absolute path of argv[0]: as given when absolute, else the given
    environment's PATH, else ~/.local/bin and FALLBACK_DIRS. An absolute
    argv[0] in token_cmd avoids the lookup entirely."""
    if os.path.isabs(name):
        return name
    found = shutil.which(name, path=environ.get("PATH") or os.defpath)
    if found or os.sep in name:
        return found
    home = environ.get("HOME") or ""
    extra = ([os.path.join(home, ".local", "bin")] if home else []) + list(FALLBACK_DIRS)
    return shutil.which(name, path=os.pathsep.join(extra))


def fetch_token(token_cmd, environ, timeout=TOKEN_TIMEOUT, run=None):
    """Run token_cmd (argv, no shell) and return a validated xoxb- token."""
    run = run or subprocess.run
    argv = list(token_cmd)
    found = resolve_program(argv[0], environ)
    if not found:
        raise NotifyError("token_cmd_missing", "token_cmd program not found")
    argv[0] = found
    try:
        proc = run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.DEVNULL, env=dict(environ), timeout=timeout, shell=False)
    except subprocess.TimeoutExpired:
        raise NotifyError("token_cmd_timeout", "token_cmd timed out")
    except OSError:
        raise NotifyError("token_cmd_failed", "token_cmd could not run")
    if proc.returncode != 0:
        raise NotifyError("token_cmd_failed", "token_cmd exited %d" % proc.returncode)
    try:
        token = (proc.stdout or b"").decode("utf-8").strip()
    except UnicodeDecodeError:
        token = ""
    if not _TOKEN_RE.match(token):
        raise NotifyError("token_invalid", "token_cmd did not print an xoxb- bot token")
    return token


def urllib_transport(url, headers, body, timeout=HTTP_TIMEOUT):
    """POST body; returns (http_status, response bytes)."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError, ValueError):
        raise NotifyError("slack_network", "could not reach Slack")


def post_message(token, channel, text, transport=None):
    transport = transport or urllib_transport
    body = json.dumps({"channel": channel, "text": text, "mrkdwn": False,
                       "unfurl_links": False, "unfurl_media": False},
                      ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8",
               "Authorization": "Bearer " + token}
    status, payload = transport(SLACK_URL, headers, body)
    if status != 200:
        raise NotifyError("slack_http_%d" % _count(status), "Slack HTTP error")
    try:
        data = json.loads((payload or b"").decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise NotifyError("slack_response_invalid", "Slack response is not JSON")
    if not isinstance(data, dict):
        raise NotifyError("slack_response_invalid", "Slack response is not an object")
    if data.get("ok") is not True:
        error = data.get("error")
        code = "slack_%s" % error if isinstance(error, str) else "slack_error"
        raise NotifyError(safe_reason(code), "Slack refused the message")
    return True


def notify(root, report, environ=None, settings=None, transport=None, token_run=None):
    """Send (or log) the line for one absorb report. Never raises; returns
    {state, text, mode, sent, reason}. The caller records it in the ledger."""
    environ = os.environ if environ is None else environ
    result = collections.OrderedDict()
    result["state"] = classify(report)
    result["text"] = format_line(report)
    result["mode"] = MODE_LOG_ONLY
    result["sent"] = False
    result["reason"] = None
    try:
        config = load_config(root, settings)
    except common.WikiError as exc:
        result["reason"] = safe_reason(exc.reason)
        return result
    except Exception:
        result["reason"] = "notify_config_invalid"
        return result
    if not config["enabled"]:
        result["reason"] = "not_configured"
        return result
    result["mode"] = MODE_SLACK
    if not _CHANNEL_RE.match(config["slack_channel"]):
        result["reason"] = "channel_invalid"
        return result
    try:
        token = fetch_token(config["token_cmd"], environ, run=token_run)
        post_message(token, config["slack_channel"], result["text"], transport=transport)
        result["sent"] = True
    except common.WikiError as exc:
        result["reason"] = safe_reason(exc.reason)
    except Exception:  # never let a send failure change the absorb result
        result["reason"] = "notify_internal_error"
    return result
