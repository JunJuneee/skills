"""note, query and status commands (synthetic wiki in a temp dir)."""

import json
import os
import stat
import subprocess
import unittest

import _helpers
import common
import prepare
import wiki

DOMAINS = {"owners": {"someorg": "work", "someuser": "personal"}, "work_terms": ["acmecorp"],
           "overrides": {}, "redact_allow": [], "obsidian_plugins_allow": []}


def page(title, domain, summary, body, aliases=None):
    fm = [("title", title), ("type", "project"), ("domain", domain), ("summary", summary)]
    if aliases:
        fm.append(("aliases", aliases))
    return common.render_page(dict(fm), body)


class NoteQueryCase(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        wiki.init_wiki(self.root, self.env)
        with open(os.path.join(self.root, "domains.json"), "w") as handle:
            json.dump(DOMAINS, handle)

    def add_page(self, rel, text):
        path = os.path.join(self.root, rel)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)


class NoteTest(NoteQueryCase):
    def test_note_goes_to_the_domain_inbox(self):
        proc = self.run_cli("--json", "note", "--domain", "personal", "다음", "주에", "레이더", "배포")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        rel = json.loads(proc.stdout.decode())["path"]
        self.assertTrue(rel.startswith("inbox/personal/"))
        path = os.path.join(self.root, rel)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("다음 주에 레이더 배포", text)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)
        # inbox/ is gitignored and prepare picks the note up for its domain.
        self.assertNotIn(b"inbox", self.git(self.root, "status", "--porcelain",
                                             "--untracked-files=all").stdout)
        items = prepare.discover_inbox(self.root)
        self.assertEqual([(item["domain"], item["kind"]) for item in items],
                         [("personal", "inbox")])

    def test_same_second_never_overwrites(self):
        first = wiki.write_note(self.root, "work", "하나")
        import datetime
        now = datetime.datetime.now()
        a = wiki.write_note(self.root, "work", "둘", now=now)
        b = wiki.write_note(self.root, "work", "셋", now=now)
        self.assertEqual(len({first, a, b}), 3)

    def test_empty_note_is_refused(self):
        proc = self.run_cli("--json", "note", "--domain", "work", "   ")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "note_empty")
        self.assertEqual(os.listdir(os.path.join(self.root, "inbox", "work")), [])


class QueryTest(NoteQueryCase):
    def setUp(self):
        NoteQueryCase.setUp(self)
        self.add_page("personal/projects/radar.md", page(
            "Radar App", "personal", "개인 레이더 도구",
            "\n## 현재 상태\n\n- 배포 준비 중 <!-- src: inbox:personal/a.md @2026-11-01 -->\n"
            "\n## 내 메모\n", aliases=["레이더"]))
        self.add_page("personal/topics/deploy.md", page(
            "배포 메모", "personal", "배포 절차", "\n## 현재 상태\n\n- radar 배포는 금요일\n"))
        self.add_page("work/projects/radar.md", page(
            "Work Radar", "work", "회사 레이더", "\n## 현재 상태\n\n- 회사 radar 배포\n"))

    def test_explicit_domain_only_reads_that_domain(self):
        results = wiki.query_pages(self.root, "personal", "RADAR 배포")
        self.assertEqual(sorted(item["path"] for item in results),
                         ["personal/projects/radar.md", "personal/topics/deploy.md"])
        self.assertTrue(results[0]["snippets"])
        self.assertFalse([s for item in results for s in item["snippets"] if "src:" in s])
        work = wiki.query_pages(self.root, "work", "radar")
        self.assertEqual([item["path"] for item in work], ["work/projects/radar.md"])

    def test_fullwidth_and_alias_match(self):
        results = wiki.query_pages(self.root, "personal", "ＲＡＤＡＲ")
        self.assertEqual(results[0]["path"], "personal/projects/radar.md")
        self.assertEqual(wiki.query_pages(self.root, "personal", "레이더")[0]["title"], "Radar App")

    def test_domain_from_cwd_remote(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q", repo], env=self.env, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                        "https://github.com/someuser/radar.git"], env=self.env, check=True)
        proc = self.run_cli("--json", "query", "radar", cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        data = json.loads(proc.stdout.decode())
        self.assertEqual(data["domain"], "personal")
        self.assertNotIn("work/", json.dumps(data))

    def test_domain_flag_cannot_cross_a_decided_cwd(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q", repo], env=self.env, check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                        "https://github.com/someuser/radar.git"], env=self.env, check=True)
        proc = self.run_cli("--json", "query", "--domain", "work", "radar", cwd=repo)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "domain_conflict")
        self.assertNotIn("work/", proc.stdout.decode())
        proc = self.run_cli("--json", "query", "--domain", "personal", "radar", cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())

    def test_undetermined_cwd_needs_a_domain(self):
        proc = self.run_cli("--json", "query", "radar", cwd=self.tmp)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "domain_unresolved")
        proc = self.run_cli("query", "--domain", "work", "radar", cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertIn("work/projects/radar.md", proc.stdout.decode())

    def test_empty_query(self):
        proc = self.run_cli("--json", "query", "--domain", "work", " ")
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "query_empty")


class StatusTest(NoteQueryCase):
    def test_status_has_counts_but_no_titles(self):
        self.add_page("work/projects/secret.md", page("Hidden Work Title", "work", "x", "\n"))
        wiki.write_note(self.root, "work", "# Hidden Inbox Title\n\n본문")
        proc = self.run_cli("--json", "status", env={"WIKI_LAUNCH_AGENTS_DIR":
                                                      os.path.join(self.tmp, "agents")})
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        data = json.loads(proc.stdout.decode())
        self.assertTrue(data["ok"])
        self.assertTrue(data["scheduled_due"])
        self.assertFalse(data["schedule"]["installed"])
        self.assertGreaterEqual(data["pending"]["work"], 1)
        self.assertNotIn("Hidden", proc.stdout.decode())
        proc = self.run_cli("status", env={"WIKI_LAUNCH_AGENTS_DIR":
                                           os.path.join(self.tmp, "agents")})
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertIn("자동 실행: 설치 안 됨", proc.stdout.decode())
        self.assertNotIn("Hidden", proc.stdout.decode())


if __name__ == "__main__":
    unittest.main()
