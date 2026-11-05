import json
import os
import unittest

import _helpers
import common
from common import ConfigError


class ResolveRootTest(unittest.TestCase):
    def test_precedence_and_empty(self):
        tmp = os.path.realpath("/tmp")
        self.assertEqual(common.resolve_root("/tmp/x", {"WIKI_ROOT": "/tmp/y", "HOME": "/h"}),
                         os.path.join(tmp, "x"))
        self.assertEqual(common.resolve_root(None, {"WIKI_ROOT": "/tmp/y", "HOME": "/h"}),
                         os.path.join(tmp, "y"))
        self.assertEqual(common.resolve_root(None, {"WIKI_ROOT": "", "HOME": "/tmp"}),
                         os.path.join(tmp, "wiki"))
        self.assertEqual(common.resolve_root("", {"HOME": "/tmp"}), os.path.join(tmp, "wiki"))

    def test_realpath(self):
        root = common.resolve_root("/tmp/../tmp/./w", {})
        self.assertEqual(root, os.path.realpath("/tmp/w"))


class DomainsTest(_helpers.TempHomeCase):
    def write(self, data):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, "domains.json"), "w", encoding="utf-8") as handle:
            handle.write(data if isinstance(data, str) else json.dumps(data))

    def test_template_loads_with_placeholders(self):
        with open(os.path.join(_helpers.TEMPLATES_DIR, "domains.example.json"), encoding="utf-8") as h:
            data = json.load(h)
        domains = common.validate_domains(data)
        self.assertEqual(set(domains), set(common.DOMAINS_KEYS))
        placeholders = common.domains_placeholders(domains)
        self.assertTrue(any(p.startswith("owners:") for p in placeholders))
        self.assertTrue(any(p.startswith("work_terms:") for p in placeholders))

    def test_load_valid(self):
        self.write({"owners": {"Org": "work", "me": "personal"}, "work_terms": ["t"]})
        domains = common.load_domains(self.root)
        self.assertEqual(domains["owners"], {"Org": "work", "me": "personal"})
        self.assertEqual(domains["overrides"], {})
        self.assertEqual(domains["redact_allow"], [])
        self.assertEqual(common.domains_placeholders(domains), [])

    def test_errors(self):
        cases = [
            ({"owner": {}}, "domains_invalid"),
            ({"owners": {"Org": "company"}}, "domains_invalid"),
            ({"owners": {"Org": "work", "org": "personal"}}, "domains_invalid"),
            ({"owners": []}, "domains_invalid"),
            ({"work_terms": "x"}, "domains_invalid"),
            ({"work_terms": [1]}, "domains_invalid"),
            ({"overrides": {"mem:x": "both"}}, "domains_invalid"),
            ([], "domains_invalid"),
            ("{not json", "config_invalid_json"),
        ]
        for data, reason in cases:
            self.write(data)
            with self.assertRaises(ConfigError, msg=repr(data)) as ctx:
                common.load_domains(self.root)
            self.assertEqual(ctx.exception.reason, reason, repr(data))

    def test_missing(self):
        with self.assertRaises(ConfigError) as ctx:
            common.load_domains(self.root)
        self.assertEqual(ctx.exception.reason, "domains_missing")

    def test_underscore_keys_allowed(self):
        self.write({"_comment": "x", "owners": {}})
        self.assertEqual(common.load_domains(self.root)["owners"], {})


class SettingsTest(_helpers.TempHomeCase):
    def write(self, data):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, "settings.json"), "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def test_defaults_when_missing(self):
        settings = common.load_settings(self.root)
        self.assertEqual(settings["batch_max_sources"], 30)
        self.assertEqual(settings["notify"]["token_cmd"], [])
        self.assertEqual(settings["schedule"]["interval_seconds"], 1800)
        self.assertEqual(settings["schedule"]["min_hours_between_runs"], 20)

    def test_merge_and_unknown_keys(self):
        self.write({"model": "opus", "notify": {"slack_channel": "C000"}, "future": {"x": 1}})
        settings = common.load_settings(self.root)
        self.assertEqual(settings["model"], "opus")
        self.assertEqual(settings["notify"]["slack_channel"], "C000")
        self.assertEqual(settings["notify"]["token_cmd"], [])
        self.assertEqual(settings["future"], {"x": 1})
        self.assertNotIn("future", common.SETTINGS_DEFAULTS)

    def test_invalid(self):
        bad = [
            {"model": ""}, {"model": 3}, {"max_budget_usd": 0}, {"max_budget_usd": "2"},
            {"max_budget_usd": True}, {"batch_max_sources": 31}, {"batch_max_sources": 1.5},
            {"claude_path": "claude"}, {"notify": {"token_cmd": "doppler secrets get X"}},
            {"notify": []}, {"schedule": {"interval_seconds": 10}},
            {"schedule": {"label_user": 5}},
        ]
        for data in bad:
            self.write(data)
            with self.assertRaises(ConfigError, msg=repr(data)) as ctx:
                common.load_settings(self.root)
            self.assertEqual(ctx.exception.reason, "settings_invalid", repr(data))

    def test_token_cmd_argv(self):
        self.write({"notify": {"token_cmd": ["doppler", "secrets", "get", "NAME", "--plain"]}})
        self.assertEqual(common.load_settings(self.root)["notify"]["token_cmd"][0], "doppler")


if __name__ == "__main__":
    unittest.main()
