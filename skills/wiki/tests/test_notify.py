"""notify (T5, D17 + panel D-7): fixed wording, four states, token handling.

No network: the HTTP transport and token_cmd are fakes. Token-looking
strings are assembled at runtime (GitHub push protection)."""

import json
import os
import subprocess
import sys
import unittest

import _helpers
import common
import notify
import wiki

BOT_PREFIX = "xox" + "b-"
FAKE_TOKEN = BOT_PREFIX + "1234567890" + "-" + "abcdefABCDEF"
CHANNEL = "C" + "0ABCDEF12"


def report(status, **extra):
    data = {"ok": status != "failed", "status": status, "reason": None, "applied": 0,
            "new_pages": 0, "quarantined": 0, "unresolved": 0, "rules_added": 0,
            "rules_removed": 0, "batches": [], "warnings": ["secret title in a warning"]}
    data.update(extra)
    return data


class FakeTransport(object):
    def __init__(self, status=200, payload=None, error=None):
        self.calls = []
        self.status = status
        self.payload = json.dumps(payload if payload is not None else {"ok": True}).encode()
        self.error = error

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, json.loads(body.decode("utf-8"))))
        if self.error:
            raise self.error
        return self.status, self.payload


class FormatTest(unittest.TestCase):
    def test_success_line(self):
        line = notify.format_line(report("ok", applied=12, new_pages=2, quarantined=1,
                                         rules_added=1))
        self.assertEqual(line, "위키: 반영 12 · 새 페이지 2 · 격리 1 · 전역 선호 +1/−0")
        self.assertEqual(notify.classify(report("ok")), notify.STATE_SUCCESS)

    def test_zero_line(self):
        self.assertEqual(notify.format_line(report("empty", quarantined=3)), "위키: 반영 0 · 격리 3")
        self.assertEqual(notify.classify(report("empty")), notify.STATE_ZERO)

    def test_failure_line_uses_reason_code_only(self):
        self.assertEqual(notify.format_line(report("failed", reason="claude_flags_missing")),
                         "위키: 실패 (claude_flags_missing)")
        self.assertEqual(notify.format_line(report("failed", reason="/some path: free text")),
                         "위키: 실패 (unknown)")
        self.assertEqual(notify.format_line(report(None)), "위키: 실패 (unknown)")
        self.assertEqual(notify.classify({}), notify.STATE_FAILURE)

    def test_held_line_counts_failed_and_deferred_batches(self):
        batches = [{"ok": True, "deferred": False}, {"ok": False, "deferred": False},
                   {"ok": True, "deferred": True}]
        line = notify.format_line(report("held", applied=3, reason="budget_exceeded",
                                         batches=batches))
        self.assertEqual(line, "위키: 한도 보류 · 반영 3 · 새 페이지 0 · 격리 0 · "
                               "전역 선호 +0/−0 · 실패 1 · 보류 1")
        self.assertEqual(notify.classify(report("held")), notify.STATE_HELD)

    def test_counts_are_integers_only(self):
        line = notify.format_line(report("ok", applied="12; drop", new_pages=True,
                                         quarantined=-4, rules_added=2.9))
        self.assertEqual(line, "위키: 반영 0 · 새 페이지 0 · 격리 0 · 전역 선호 +2/−0")
        self.assertNotIn("secret", line)


class ConfigTest(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        os.makedirs(self.root)

    def test_defaults_are_log_only(self):
        config = notify.load_config(self.root)
        self.assertFalse(config["enabled"])
        self.assertEqual(config["source"], "settings.json notify")

    def test_settings_block(self):
        with open(os.path.join(self.root, "settings.json"), "w") as handle:
            json.dump({"notify": {"slack_channel": CHANNEL, "token_cmd": ["tok"]}}, handle)
        config = notify.load_config(self.root)
        self.assertTrue(config["enabled"])
        self.assertEqual(config["token_cmd"], ["tok"])

    def test_notify_json_takes_precedence(self):
        with open(os.path.join(self.root, "settings.json"), "w") as handle:
            json.dump({"notify": {"slack_channel": CHANNEL, "token_cmd": ["tok"]}}, handle)
        with open(os.path.join(self.root, "notify.json"), "w") as handle:
            json.dump({"slack_channel": "", "token_cmd": []}, handle)
        config = notify.load_config(self.root)
        self.assertEqual(config["source"], "notify.json")
        self.assertFalse(config["enabled"])

    def test_token_cmd_must_be_argv_list(self):
        with open(os.path.join(self.root, "notify.json"), "w") as handle:
            json.dump({"slack_channel": CHANNEL, "token_cmd": "doppler secrets get X"}, handle)
        with self.assertRaises(common.WikiError) as ctx:
            notify.load_config(self.root)
        self.assertEqual(ctx.exception.reason, "notify_config_invalid")
        result = notify.notify(self.root, report("ok"), self.env, transport=FakeTransport())
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "notify_config_invalid")


class SendTest(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        os.makedirs(self.root)
        self.token_cmd = [sys.executable, "-c", "print(%r)" % FAKE_TOKEN]

    def configure(self, channel=CHANNEL, token_cmd=None):
        with open(os.path.join(self.root, "notify.json"), "w") as handle:
            json.dump({"slack_channel": channel,
                       "token_cmd": token_cmd if token_cmd is not None else self.token_cmd},
                      handle)

    def test_log_only_without_config(self):
        transport = FakeTransport()
        result = notify.notify(self.root, report("ok", applied=1), self.env, transport=transport)
        self.assertEqual(result["mode"], notify.MODE_LOG_ONLY)
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "not_configured")
        self.assertEqual(result["text"], "위키: 반영 1 · 새 페이지 0 · 격리 0 · 전역 선호 +0/−0")
        self.assertEqual(transport.calls, [])

    def test_sends_one_line(self):
        self.configure()
        transport = FakeTransport()
        result = notify.notify(self.root, report("ok", applied=2), self.env, transport=transport)
        self.assertTrue(result["sent"], result)
        self.assertIsNone(result["reason"])
        self.assertEqual(len(transport.calls), 1)
        url, headers, body = transport.calls[0]
        self.assertEqual(url, "https://slack.com/api/chat.postMessage")
        self.assertEqual(headers["Authorization"], "Bearer " + FAKE_TOKEN)
        self.assertEqual(body["channel"], CHANNEL)
        self.assertEqual(body["text"], result["text"])
        self.assertFalse(body["mrkdwn"])
        self.assertFalse(body["unfurl_links"])
        self.assertNotIn(FAKE_TOKEN, json.dumps(result))

    def test_token_cmd_runs_without_shell(self):
        self.configure(token_cmd=["tok-cmd", "--plain"])
        seen = {}

        def fake_run(argv, **kwargs):
            seen["argv"], seen["kwargs"] = argv, kwargs
            return subprocess.CompletedProcess(argv, 0, (FAKE_TOKEN + "\n").encode(), b"")

        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        program = os.path.join(bindir, "tok-cmd")
        with open(program, "w") as handle:
            handle.write("#!/bin/sh\nexit 1\n")
        os.chmod(program, 0o755)
        env = dict(self.env, PATH=bindir)
        result = notify.notify(self.root, report("empty"), env, transport=FakeTransport(),
                               token_run=fake_run)
        self.assertTrue(result["sent"], result)
        self.assertEqual(seen["argv"], [program, "--plain"])
        self.assertIs(seen["kwargs"]["shell"], False)
        self.assertIs(seen["kwargs"]["stdin"], subprocess.DEVNULL)

    def test_rejects_non_bot_token(self):
        user_token = "xox" + "p-" + "1234567890-abcdefABCDEF"
        self.configure(token_cmd=[sys.executable, "-c", "print(%r)" % user_token])
        transport = FakeTransport()
        result = notify.notify(self.root, report("ok"), self.env, transport=transport)
        self.assertEqual(result["reason"], "token_invalid")
        self.assertEqual(transport.calls, [])
        self.assertNotIn(user_token, json.dumps(result))

    def test_token_cmd_failures(self):
        self.configure(token_cmd=[sys.executable, "-c", "import sys; sys.exit(3)"])
        result = notify.notify(self.root, report("ok"), self.env, transport=FakeTransport())
        self.assertEqual(result["reason"], "token_cmd_failed")
        self.configure(token_cmd=["no-such-token-program-xyz"])
        result = notify.notify(self.root, report("ok"), self.env, transport=FakeTransport())
        self.assertEqual(result["reason"], "token_cmd_missing")

    def test_channel_must_be_an_id(self):
        self.configure(channel="#general")
        transport = FakeTransport()
        result = notify.notify(self.root, report("ok"), self.env, transport=transport)
        self.assertEqual(result["reason"], "channel_invalid")
        self.assertEqual(transport.calls, [])

    def test_slack_errors_become_reason_codes(self):
        self.configure()
        cases = [
            (FakeTransport(payload={"ok": False, "error": "channel_not_found"}),
             "slack_channel_not_found"),
            (FakeTransport(payload={"ok": False, "error": "weird error text!"}), "unknown"),
            (FakeTransport(status=500), "slack_http_500"),
            (FakeTransport(error=notify.NotifyError("slack_network", "x")), "slack_network"),
            (FakeTransport(error=RuntimeError("boom " + FAKE_TOKEN)), "notify_internal_error"),
        ]
        for transport, reason in cases:
            result = notify.notify(self.root, report("ok"), self.env, transport=transport)
            self.assertFalse(result["sent"])
            self.assertEqual(result["reason"], reason)
            self.assertNotIn(FAKE_TOKEN, json.dumps(result))


class WikiGitignoreTest(_helpers.TempHomeCase):
    def test_notify_json_is_ignored_in_the_wiki(self):
        wiki.init_wiki(self.root, self.env)
        proc = self.git(self.root, "check-ignore", "-q", "notify.json")
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
