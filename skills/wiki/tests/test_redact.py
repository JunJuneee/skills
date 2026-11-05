"""Redaction (D15, contract 4). Secret-looking fixtures are assembled at
runtime so the public repo never holds a literal token."""

import unittest

import _helpers  # noqa: F401
import redact


def j(*parts):
    return "".join(parts)


# A 32-char mixed alnum token with entropy well above 4.0.
RANDOM_TOKEN = j("Zx9Qw3Er", "7Ty1Ui5O", "p2As8Df4", "Gh6Jk0Lm")
# Made-up shapes of real data: an encoded project folder (alpha-only slug
# with entropy >= 4.0) and a worktree folder with a short hash suffix.
ENCODED_FOLDER = "-opt-Fake-Desktop-Widget-Orbit-Planner-Example"
HASHED_SEGMENT = "demo-tools-lucky-fox-4c2e9a1b7d3f"


class RedactTest(unittest.TestCase):
    def check(self, text, kind, allow=()):
        result = redact.redact(text, allow)
        self.assertIn("[REDACTED:%s]" % kind, result.text, result)
        self.assertEqual(result.counts.get(kind), 1, result)
        return result

    def test_prefixed_tokens(self):
        cases = [
            ("github", j("gh", "p_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8")),
            ("github", j("github", "_pat_", "11ABCDEFG0123456789_abcdefghijk")),
            ("slack", j("xo", "xb-", "1234567890-0987654321-AbCdEfGhIjKl")),
            ("anthropic", j("sk-", "ant-", "api03-AbCdEfGhIjKlMnOpQrStUv")),
            ("openai", j("sk-", "proj-", "AbCdEfGhIjKlMnOpQrStUvWx")),
            ("aws", j("AK", "IA", "ABCDEFGHIJKLMNOP")),
            ("google", j("AI", "za", "SyAbCdEfGhIjKlMnOpQrStUvWxYz0123456")),
            ("gitlab", j("gl", "pat-", "AbCdEfGhIjKlMnOpQrSt")),
            ("jwt", j("ey", "JhbGciOiJIUzI1NiJ9", ".", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", ".",
                      "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV")),
        ]
        for kind, token in cases:
            result = self.check("before %s after" % token, kind)
            self.assertNotIn(token, result.text)
            self.assertTrue(result.text.startswith("before ") and result.text.endswith(" after"))

    def test_deterministic(self):
        one = redact.redact("key %s" % j("gh", "p_", "A" * 10, "b" * 20)).text
        two = redact.redact("key %s" % j("gh", "p_", "C" * 10, "d" * 20)).text
        self.assertEqual(one, two)
        self.assertEqual(one, "key [REDACTED:github]")

    def test_private_key_block(self):
        block = j("-----BEGIN ", "RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA ",
                  "PRIVATE KEY-----")
        result = self.check("x\n%s\ny" % block, "private_key")
        self.assertEqual(result.text, "x\n[REDACTED:private_key]\ny")

    def test_url_credentials(self):
        result = self.check(j("clone https://bob:", "s3cr3tPass", "@git.example.com/a/b"),
                            "url_cred")
        self.assertIn("https://[REDACTED:url_cred]@git.example.com/a/b", result.text)

    def test_bearer_and_assignment(self):
        self.check(j("Authorization: Bearer ", "abc.DEF_123-xyz~987"), "bearer")
        result = self.check(j("export API_", "TOKEN=", "Qw3rty12"), "assign")
        self.assertIn("API_TOKEN=[REDACTED:assign]", result.text)
        result = self.check(j('password: "', "hunter22", '"'), "assign")
        self.assertIn('password: "[REDACTED:assign]"', result.text)

    def test_assignment_placeholders_are_kept(self):
        for text in ("token=$SLACK_BOT_TOKEN", "api_key: <your-key>", "password=******",
                     "secret: ${SECRET}", "token: abc"):
            result = redact.redact(text)
            self.assertEqual(result.text, text)
            self.assertEqual(result.counts, {})

    def test_high_entropy(self):
        result = self.check("val %s end" % RANDOM_TOKEN, "entropy")
        self.assertEqual(result.text, "val [REDACTED:entropy] end")

    def test_hex(self):
        token = j("9f86d081884c7d65", "9a2feaa0c55ad015", "a3bf4f1b2b0b822c")
        self.check("digest %s" % token, "hex")
        low = "ab" * 16  # 32 hex chars, entropy 1.0
        self.assertEqual(redact.redact(low).counts, {})

    def test_exceptions(self):
        texts = [
            j("commit 0123456789abcdef", "0123456789abcdef01234567"),
            "id 123e4567-e89b-12d3-a456-426614174000",
            "/opt/projects/%s/skills/wiki/scripts" % HASHED_SEGMENT,
            "skills/wiki/scripts/prepare.py and ~/notes/videos/some-long-file-name.md",
            "<!-- src: mem:%s/feedback_x.md @2026-11-01 -->" % ENCODED_FOLDER,
            "~/.claude/projects/%s/memory/a.md" % ENCODED_FOLDER,
            "sample-tool-workflow-review-loops-final",
        ]
        for text in texts:
            result = redact.redact(text)
            self.assertEqual(result.text, text, result)

    def test_exception_fixtures_are_meaningful(self):
        # Without the path/slug exceptions these would be redacted.
        self.assertGreaterEqual(redact.shannon_entropy(ENCODED_FOLDER), redact.ENTROPY_THRESHOLD)
        self.assertGreaterEqual(redact.shannon_entropy(HASHED_SEGMENT), redact.ENTROPY_THRESHOLD)
        self.assertEqual(redact.redact(HASHED_SEGMENT).counts, {"entropy": 1})

    def test_path_with_secret_segment(self):
        result = redact.redact("/tmp/a/%s/b" % RANDOM_TOKEN)
        self.assertEqual(result.counts, {"entropy": 1})

    def test_mixed_alnum_slug_is_redacted(self):
        token = j("a1b2C3d4", "-E5f6G7h8", "-i9J0k1L2", "m3N4")
        self.assertEqual(redact.redact(token).counts, {"entropy": 1})

    def test_random_mixed_case_slug_is_redacted(self):
        # Three random mixed-case alpha parts are not an encoded folder name.
        parts = (j("AbCd", "EfGh"), j("IjKl", "MnOp"), j("QrSt", "UvWx"))
        for sep in ("-", "/", "_"):
            token = sep.join(parts)
            self.assertEqual(redact.scan("x %s y" % token), {"entropy": 1}, token)
        for text in ("Sources/AppFeature/UserProfileSettingsPanel.swift",
                     "~/.claude/projects/-opt-x-Desktop-WidgetOrbitServerMonorepo-api/a",
                     "<!-- src: mem:-opt-x-Desktop-WidgetOrbitServerMonorepo-api/b.md @2026-11-01 -->",
                     "packages/HTTPServerConfigLoader/index",
                     "see [[iOSAppDelegate-main-file-example]]"):
            self.assertEqual(redact.scan(text), {}, text)

    def test_allow_list(self):
        token = j("gh", "p_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8")
        result = redact.redact("a %s b %s" % (token, RANDOM_TOKEN), allow=[token, RANDOM_TOKEN])
        self.assertEqual(result.text, "a %s b %s" % (token, RANDOM_TOKEN))
        self.assertEqual(result.counts, {})

    def test_email_and_internal_host_warn_only(self):
        text = "mail dev@example.com host build.corp and 10.0.0.12"
        result = redact.redact(text)
        self.assertEqual(result.text, text)
        self.assertEqual(result.warnings, {"email": 1, "internal_host": 2})

    def test_scan_and_idempotence(self):
        text = "x %s" % RANDOM_TOKEN
        once = redact.redact(text).text
        self.assertEqual(redact.scan(once), {})
        self.assertEqual(redact.redact(once).text, once)
        self.assertEqual(redact.scan(text), {"entropy": 1})

    def test_korean_text_untouched(self):
        text = "한글 문장은 그대로 둔다. 결정은 내가 하고 결과만 보고한다."
        self.assertEqual(redact.redact(text).text, text)


if __name__ == "__main__":
    unittest.main()
