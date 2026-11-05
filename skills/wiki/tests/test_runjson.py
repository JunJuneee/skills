import copy
import datetime
import json
import os
import stat
import unittest

import _helpers
import common

SHA = "a" * 40


def sample_run():
    run = common.new_run("2026-11-06T0215", SHA, "/w/.absorb-wt")
    run["batches"].append(common.make_batch(1, [
        common.make_source("mem:proj/feedback_x.md", "personal", "new", "2026-11-04",
                           "staging/1/mem/feedback_x.md"),
        common.make_source("prompt:personal/2026-11-04", "personal", "changed", "2026-11-04",
                           "staging/1/prompts/2026-11-04.md", "staging/1/prompts/2026-11-04.md.diff"),
        common.make_source("handoff:old.md", "personal", "deleted", "2026-10-01", None),
    ]))
    run["batches"].append(common.make_batch(2, [
        common.make_source("inbox:work/n.md", "work", "new", "2026-11-05", "staging/2/inbox/n.md"),
    ]))
    run["quarantined"] = 1
    return run


class RunJsonTest(_helpers.TempHomeCase):
    def test_contract_keys(self):
        run = sample_run()
        for key in common.RUN_TOP_KEYS:
            self.assertIn(key, run)
        self.assertEqual(run["schema_version"], 1)
        self.assertTrue(run["deviations"])
        self.assertEqual(list(run["batches"][0].keys()), ["batch_id", "sources", "allowed_globs"])
        self.assertEqual(list(run["batches"][0]["sources"][0].keys()), list(common.SOURCE_KEYS))
        self.assertEqual(run["batches"][0]["allowed_globs"], ["personal/**"])
        self.assertEqual(run["batches"][1]["allowed_globs"], ["work/**"])
        self.assertEqual(common.validate_run(run), [])

    def test_allowed_globs_exclude_root_files(self):
        globs = common.allowed_globs_for("personal")
        for path in ("index.md", "log.md", "now.md", "about-me.md", "settings.json",
                     "domains.json", "SCHEMA.md", "work/projects/x.md", ".state/run.json"):
            self.assertFalse(common.path_allowed(path, globs), path)
        for path in ("personal/projects/x.md", "personal/_drafts/now.md", "personal/a/b/c.md"):
            self.assertTrue(common.path_allowed(path, globs), path)
        with self.assertRaises(ValueError):
            common.allowed_globs_for("both")

    def test_make_batch_guards(self):
        work = common.make_source("mem:a", "work", "new", "2026-01-01", "staging/1/a")
        personal = common.make_source("mem:b", "personal", "new", "2026-01-01", "staging/1/b")
        with self.assertRaises(ValueError):
            common.make_batch(1, [work, personal])
        with self.assertRaises(ValueError):
            common.make_batch(1, [])
        with self.assertRaises(ValueError):
            common.make_batch(1, [work] * 31)
        self.assertEqual(len(common.make_batch(1, [work] * 30)["sources"]), 30)

    def test_validate_errors(self):
        def broken(mutate):
            run = copy.deepcopy(sample_run())
            mutate(run)
            return common.validate_run(run)

        self.assertIn("missing base_sha", broken(lambda r: r.pop("base_sha")))
        self.assertTrue(broken(lambda r: r.update(base_sha="HEAD")))
        self.assertTrue(broken(lambda r: r.update(run_id="today")))
        self.assertTrue(broken(lambda r: r.update(quarantined=-1)))
        self.assertTrue(broken(lambda r: r.update(unresolved=True)))
        self.assertTrue(broken(lambda r: r["batches"][0].update(allowed_globs=["personal/**", "index.md"])))
        self.assertTrue(broken(lambda r: r["batches"][0].update(allowed_globs=["**"])))
        self.assertTrue(broken(lambda r: r["batches"][1].update(batch_id=1)))
        self.assertTrue(broken(lambda r: r["batches"][0]["sources"][0].update(op="edit")))
        self.assertTrue(broken(lambda r: r["batches"][0]["sources"][0].update(date="2026/11/04")))
        self.assertTrue(broken(lambda r: r["batches"][0]["sources"][0].update(id="has space:x")))
        self.assertTrue(broken(lambda r: r["batches"][0]["sources"][0].update(domain="work")))
        self.assertTrue(broken(lambda r: r["batches"][0]["sources"][0].update(redacted_path=None)))
        for path in ("../x", "/abs/staging/1/x", "staging/../x", "snapshots/x", "staging",
                     "staging//x", "staging\\1\\x"):
            self.assertTrue(broken(lambda r, p=path: r["batches"][0]["sources"][0].update(
                redacted_path=p)), path)
        self.assertTrue(broken(lambda r: r["batches"][0]["sources"].extend(
            [copy.deepcopy(r["batches"][0]["sources"][0]) for _ in range(30)])))
        self.assertTrue(broken(lambda r: r["batches"][0].update(sources=[])))
        self.assertEqual(common.validate_run([]), ["run.json must be an object"])

    def test_write_read_round_trip(self):
        run = sample_run()
        common.write_run(self.root, run)
        path = common.run_json_path(self.root)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(common.state_dir(self.root)).st_mode), 0o700)
        self.assertEqual(json.loads(json.dumps(common.read_run(self.root))),
                         json.loads(json.dumps(run)))
        bad = sample_run()
        bad["base_sha"] = "x"
        with self.assertRaises(common.WikiError) as ctx:
            common.write_run(self.root, bad)
        self.assertEqual(ctx.exception.reason, "run_json_invalid")

    def test_run_id(self):
        self.assertEqual(common.make_run_id(datetime.datetime(2026, 11, 6, 2, 15)), "2026-11-06T0215")


class GlobMatchTest(unittest.TestCase):
    def test_segments(self):
        m = common.glob_match
        self.assertTrue(m("personal/a.md", "personal/**"))
        self.assertTrue(m("personal/x/y/z.md", "personal/**"))
        self.assertFalse(m("personal", "personal/**"))
        self.assertFalse(m("personal-x/a.md", "personal/**"))
        self.assertFalse(m("Personal/a.md", "personal/**"))
        self.assertFalse(m("personal/../work/a.md", "personal/**"))
        self.assertFalse(m("./personal/a.md", "personal/**"))
        self.assertFalse(m("/personal/a.md", "personal/**"))
        self.assertFalse(m("personal//a.md", "personal/**"))
        self.assertFalse(m("", "personal/**"))
        self.assertTrue(m("personal/projects/한글 페이지.md", "personal/**"))
        self.assertTrue(m("work/notes/a.md", "work/*/a.md"))
        self.assertFalse(m("work/notes/deep/a.md", "work/*/a.md"))
        self.assertTrue(m("work/notes/deep/a.md", "work/**/a.md"))
        self.assertTrue(m("work/a.md", "work/**/a.md"))
        self.assertTrue(m("index.md", "index.md"))
        self.assertFalse(m("index.mdx", "index.md"))
        self.assertTrue(m("work/a1.md", "work/a?.md"))
        self.assertFalse(m("work/a.b", "work/a[.]b"))


if __name__ == "__main__":
    unittest.main()
