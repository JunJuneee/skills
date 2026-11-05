"""prepare (T2): discovery, contract-2 resolution, redaction, snapshots,
withdrawal, inbox consumption, staging and run.json. Synthetic fixtures in
temp dirs only; owners and work terms are made up."""

import datetime
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import time
import unittest
from unittest import mock

import _helpers
import common
import prepare
import wiki

NOW = datetime.datetime(2026, 11, 6, 12, 0)
WORK_ORG = "WorkOrg"
ME = "MeUser"
TERM = "AcmeCorp"


def noon(date_text):
    """Epoch milliseconds at local noon (TZ cannot move the date)."""
    moment = datetime.datetime.strptime(date_text, "%Y-%m-%d").replace(hour=12)
    return int(time.mktime(moment.timetuple()) * 1000)


def j(*parts):
    return "".join(parts)


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class PrepareCase(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        patcher = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                               "GIT_CONFIG_NOSYSTEM": "1",
                                               "GIT_TERMINAL_PROMPT": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)
        wiki.init_wiki(self.root, environ=self.env)
        self.write_domains()
        self.src = os.path.join(self.tmp, "src")
        self.projects = os.path.join(self.src, "projects")
        self.history = os.path.join(self.src, "history.jsonl")
        self.handoff = os.path.join(self.src, "handoff")
        self.design = os.path.join(self.src, "design")
        for path in (self.projects, self.handoff, self.design):
            os.makedirs(path)
        self.traycer_db = None
        self.epics_db = None
        self.repos = os.path.join(self.tmp, "repos")
        os.makedirs(self.repos)

    # -- fixtures ---------------------------------------------------------

    def write_domains(self, **changes):
        data = {"owners": {WORK_ORG: "work", ME: "personal"}, "work_terms": [TERM],
                "overrides": {}, "redact_allow": [], "obsidian_plugins_allow": []}
        data.update(changes)
        with open(os.path.join(self.root, "domains.json"), "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def paths(self):
        return prepare.SourcePaths(self.projects, self.history, self.handoff, self.design,
                                   self.traycer_db, self.epics_db)

    def make_repo(self, name, *urls):
        path = os.path.join(self.repos, name)
        os.makedirs(path)
        self.git(path, "init", "-q")
        for index, url in enumerate(urls):
            self.git(path, "remote", "add", "r%d" % index, url)
        return path

    def project_folder(self, cwd):
        return prepare.fs_encode(cwd)

    def add_memory(self, folder, name, body, modified="2026-11-04T03:00:00.000Z", jsonl_cwd=None):
        memdir = os.path.join(self.projects, folder, "memory")
        os.makedirs(memdir, exist_ok=True)
        lines = ["---", "name: %s" % name.replace(".md", ""), "description: test memory",
                 "metadata:", "  node_type: memory", "  type: feedback"]
        if modified:
            lines.append("  modified: %s" % modified)
        lines += ["---", "", body, ""]
        with open(os.path.join(memdir, name), "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        if jsonl_cwd:
            with open(os.path.join(self.projects, folder, "s1.jsonl"), "w") as handle:
                handle.write(json.dumps({"type": "custom-title", "sessionId": "x"}) + "\n")
                handle.write(json.dumps({"type": "user", "cwd": jsonl_cwd}) + "\n")
        return os.path.join(memdir, name)

    def add_doc(self, base, rel, fm_lines, body="본문"):
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = "\n".join(["---"] + fm_lines + ["---", "", body, ""]) if fm_lines else body
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def write_history(self, rows):
        with open(self.history, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def add_inbox(self, domain, name, text):
        path = os.path.join(self.root, "inbox", domain, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def run_prepare(self, now=NOW, **kwargs):
        kwargs.setdefault("fs_root", self.tmp)
        return prepare.prepare(self.root, environ=self.env, paths=self.paths(), now=now,
                               **kwargs)

    def run_json(self):
        with open(common.run_json_path(self.root), encoding="utf-8") as handle:
            return json.load(handle)

    def all_sources(self):
        return [source for batch in self.run_json()["batches"] for source in batch["sources"]]

    def source(self, source_id, op=None):
        found = [s for s in self.all_sources() if s["id"] == source_id
                 and (op is None or s["op"] == op)]
        self.assertEqual(len(found), 1, (source_id, op, self.all_sources()))
        return found[0]

    def staged(self, source):
        with open(os.path.join(self.root, ".state", source["redacted_path"]),
                  encoding="utf-8") as handle:
            return handle.read()

    def commit_all(self):
        for batch in self.run_json()["batches"]:
            prepare.commit_batch(self.root, batch["batch_id"])
        prepare.finalize_run(self.root)

    def sources_json(self):
        return prepare.load_sources(self.root)["sources"]


class MemoryResolutionTest(PrepareCase):
    def test_jsonl_cwd_and_remote(self):
        repo = self.make_repo("work-app", "git@github.com:%s/app.git" % WORK_ORG)
        folder = "-x-gone-work-app"
        self.add_memory(folder, "feedback_a.md", "선호 A", jsonl_cwd=repo)
        memdir = os.path.join(self.projects, folder, "memory")
        with open(os.path.join(memdir, "MEMORY.md"), "w") as handle:
            handle.write("index")
        result = self.run_prepare()
        source = self.source("mem:%s/feedback_a.md" % folder)
        self.assertEqual(source["domain"], "work")
        self.assertEqual(source["op"], "new")
        self.assertEqual(source["date"], prepare.parse_iso_date("2026-11-04T03:00:00.000Z"))
        self.assertIsNone(source["diff_path"])
        self.assertEqual(len(self.all_sources()), 1)  # MEMORY.md excluded
        self.assertEqual(result["by_domain"], {"work": 1, "personal": 0})
        self.assertIn("선호 A", self.staged(source))
        self.assertEqual(common.validate_run(self.run_json()), [])

    def test_filesystem_candidate(self):
        repo = self.make_repo("my.side-proj", "https://github.com/%s/side.git" % ME)
        folder = self.project_folder(repo)
        self.add_memory(folder, "project_b.md", "개인 프로젝트", modified=None)
        self.run_prepare()
        source = self.source("mem:%s/project_b.md" % folder)
        self.assertEqual(source["domain"], "personal")
        self.assertEqual(source["date"], datetime.date.today().strftime("%Y-%m-%d"))

    def test_filesystem_candidate_from_slash(self):
        repo = self.make_repo("slash-root", "https://github.com/%s/x.git" % ME)
        folder = self.project_folder(repo)
        self.add_memory(folder, "p.md", "x")
        self.run_prepare(fs_root="/")
        self.assertEqual(self.source("mem:%s/p.md" % folder)["domain"], "personal")

    def test_any_work_remote_wins(self):
        repo = self.make_repo("fork", "https://github.com/%s/x.git" % ME,
                              "git@github.com:%s/x.git" % WORK_ORG)
        self.add_memory(self.project_folder(repo), "a.md", "x")
        self.run_prepare()
        self.assertEqual(self.all_sources()[0]["domain"], "work")

    def test_unresolved_and_work_terms_fallback(self):
        self.add_memory("-x-vanished-path", "a.md", "그냥 메모")
        self.add_memory("-x-%s-repo" % TERM.lower(), "b.md", "그냥 메모")
        result = self.run_prepare()
        self.assertEqual([s["id"] for s in self.all_sources()], ["mem:-x-%s-repo/b.md" % TERM.lower()])
        self.assertEqual(self.all_sources()[0]["domain"], "work")
        self.assertEqual(result["unresolved"], 1)
        self.assertEqual(self.run_json()["unresolved"], 1)

    def test_personal_with_work_term_is_quarantined(self):
        repo = self.make_repo("side", "https://github.com/%s/side.git" % ME)
        folder = self.project_folder(repo)
        # NFKC + casefold: full-width and lower case still hit the term.
        self.add_memory(folder, "a.md", "회사 일: ａｃｍｅcorp 배포")
        self.add_memory(folder, "b.md", "개인 일")
        result = self.run_prepare()
        self.assertEqual([s["id"] for s in self.all_sources()], ["mem:%s/b.md" % folder])
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(self.run_json()["quarantined"], 1)

    def test_override_wins(self):
        repo = self.make_repo("side", "https://github.com/%s/side.git" % ME)
        folder = self.project_folder(repo)
        self.add_memory(folder, "a.md", "x")
        self.write_domains(overrides={"mem:%s/a.md" % folder: "work"})
        self.run_prepare()
        self.assertEqual(self.all_sources()[0]["domain"], "work")


class DocsTest(PrepareCase):
    def test_handoff_rules(self):
        self.add_doc(self.handoff, "2026-11-01-a.md",
                     ["date: 2026-11-01", "branch: feat/x",
                      "pr_url: https://github.com/%s/app/pull/3" % WORK_ORG, "topic: 배포"])
        self.add_doc(self.handoff, "2026-11-02-b.md",
                     ["date: 2026-11-02", "topic: 정리", "tags: [%s, infra]" % TERM.lower()])
        self.add_doc(self.handoff, "2026-11-03-c.md", ["date: 2026-11-03", "topic: 아무거나"])
        self.add_doc(self.handoff, "2026-11-03-d.md",
                     ["date: 2026-11-03", "branch: %s:feature" % ME, "topic: 개인"])
        with open(os.path.join(self.handoff, "x.patch"), "w") as handle:
            handle.write("diff")
        result = self.run_prepare()
        self.assertEqual(self.source("handoff:2026-11-01-a.md")["domain"], "work")
        self.assertEqual(self.source("handoff:2026-11-01-a.md")["date"], "2026-11-01")
        self.assertEqual(self.source("handoff:2026-11-02-b.md")["domain"], "work")
        self.assertEqual(self.source("handoff:2026-11-03-d.md")["domain"], "personal")
        ids = [s["id"] for s in self.all_sources()]
        self.assertNotIn("handoff:2026-11-03-c.md", ids)
        self.assertEqual(result["unresolved"], 1)

    def test_design_recursive_and_dates(self):
        self.add_doc(self.design, "%s-app/20261027-103000-plan.md" % TERM.lower(), None,
                     "# 계획\n본문")
        self.add_doc(self.design, "notes 2.md", None, "x")
        self.run_prepare()
        source = self.source("design:%s-app/20261027-103000-plan.md" % TERM.lower())
        self.assertEqual(source["domain"], "work")
        self.assertEqual(source["date"], "2026-10-27")


class PromptTest(PrepareCase):
    def test_history_digest(self):
        work = self.make_repo("work", "git@github.com:%s/w.git" % WORK_ORG)
        mine = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        marker = j("PASTED", "-SECRET-", "MARKER")
        self.write_history([
            {"display": "작업 프롬프트 하나", "pastedContents": {"1": {"content": marker}},
             "timestamp": noon("2026-11-05"), "project": work, "sessionId": "s"},
            {"display": "/clear", "pastedContents": {}, "timestamp": noon("2026-11-05"),
             "project": work, "sessionId": "s"},
            {"display": "개인 프롬프트", "pastedContents": {}, "timestamp": noon("2026-11-05") + 60000,
             "project": mine, "sessionId": "s"},
            {"display": "%s 얘기 개인 레포에서" % TERM, "pastedContents": {},
             "timestamp": noon("2026-11-05"), "project": mine, "sessionId": "s"},
            {"display": "홈 폴더 프롬프트", "pastedContents": {}, "timestamp": noon("2026-11-05"),
             "project": self.home, "sessionId": "s"},
            {"display": "오래된 프롬프트", "pastedContents": {}, "timestamp": noon("2026-09-01"),
             "project": work, "sessionId": "s"},
        ])
        result = self.run_prepare()
        work_src = self.source("prompts:work/2026-11-05")
        personal_src = self.source("prompts:personal/2026-11-05")
        work_text = self.staged(work_src)
        personal_text = self.staged(personal_src)
        self.assertIn("작업 프롬프트 하나", work_text)
        self.assertNotIn(marker, work_text)
        self.assertNotIn("/clear", work_text)
        self.assertIn("개인 프롬프트", personal_text)
        self.assertNotIn(TERM, personal_text)
        self.assertNotIn("오래된", work_text + personal_text)
        self.assertEqual(len(self.all_sources()), 2)
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(result["unresolved"], 1)
        for batch in self.run_json()["batches"]:
            self.assertEqual(len(set(s["domain"] for s in batch["sources"])), 1)

    def test_prompts_are_never_withdrawn(self):
        mine = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        self.write_history([{"display": "개인", "timestamp": noon("2026-11-05"), "project": mine}])
        self.run_prepare()
        self.commit_all()
        os.unlink(self.history)
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])

    def test_digest_change_gives_diff(self):
        mine = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        rows = [{"display": "첫 프롬프트", "timestamp": noon("2026-11-05"), "project": mine}]
        self.write_history(rows)
        self.run_prepare()
        self.commit_all()
        rows.append({"display": "둘째 프롬프트", "timestamp": noon("2026-11-05") + 1000,
                     "project": mine})
        self.write_history(rows)
        self.run_prepare()
        source = self.source("prompts:personal/2026-11-05", "changed")
        with open(os.path.join(self.root, ".state", source["diff_path"]), encoding="utf-8") as h:
            diff = h.read()
        self.assertIn("+둘째 프롬프트", diff)

    def make_traycer(self, schema_ok=True, workspace=None):
        self.traycer_db = os.path.join(self.src, "chat-search.db")
        conn = sqlite3.connect(self.traycer_db)
        conn.execute("CREATE TABLE search_chat (chat_key TEXT PRIMARY KEY, epic_id TEXT NOT NULL,"
                     " lifecycle_state TEXT NOT NULL, title TEXT)")
        if schema_ok:
            conn.execute("CREATE TABLE search_doc (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                         " chat_key TEXT, message_id TEXT, tier TEXT, inter_agent INTEGER,"
                         " created_at INTEGER, text TEXT)")
        else:
            conn.execute("CREATE TABLE search_doc (id INTEGER PRIMARY KEY, body TEXT)")
        conn.execute("INSERT INTO search_chat VALUES ('c1', 'e1', 'active', 't')")
        conn.execute("INSERT INTO search_chat VALUES ('c2', 'e1', 'deleted', 't')")
        if schema_ok:
            rows = [("c1", "m1", "user", 0, noon("2026-11-04"), "트레이서 사용자 프롬프트"),
                    ("c1", "m2", "assistant", 0, noon("2026-11-04"), "어시스턴트 답"),
                    ("c1", "m3", "user", 1, noon("2026-11-04"), "에이전트 간 메시지"),
                    ("c2", "m4", "user", 0, noon("2026-11-04"), "지운 채팅")]
            conn.executemany("INSERT INTO search_doc (chat_key, message_id, tier, inter_agent,"
                             " created_at, text) VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
        conn.close()
        self.epics_db = os.path.join(self.src, "epic-homes.db")
        conn = sqlite3.connect(self.epics_db)
        conn.execute("CREATE TABLE local_epic (epic_id TEXT PRIMARY KEY, home TEXT,"
                     " creation_payload TEXT)")
        payload = {"workspaces": [{"workspacePath": workspace}] if workspace else [],
                   "repoIdentifiers": []}
        conn.execute("INSERT INTO local_epic VALUES ('e1', 'h', ?)", (json.dumps(payload),))
        conn.commit()
        conn.close()

    def test_traycer_db(self):
        mine = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        self.make_traycer(workspace=mine)
        os.chmod(self.traycer_db, 0o444)
        self.run_prepare()
        text = self.staged(self.source("prompts:personal/2026-11-04"))
        self.assertIn("트레이서 사용자 프롬프트", text)
        for absent in ("어시스턴트 답", "에이전트 간 메시지", "지운 채팅"):
            self.assertNotIn(absent, text)

    def test_traycer_without_single_workspace_is_unresolved(self):
        self.make_traycer(workspace=None)
        result = self.run_prepare()
        self.assertEqual(self.all_sources(), [])
        self.assertEqual(result["unresolved"], 1)

    def test_traycer_schema_mismatch(self):
        self.make_traycer(schema_ok=False)
        result = self.run_prepare()
        self.assertIn("traycer_db_schema", result["warnings"])
        self.assertEqual(self.all_sources(), [])


class RedactionStagingTest(PrepareCase):
    def test_secrets_redacted_in_staging_and_snapshots(self):
        repo = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        token = j("gh", "p_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8")
        self.add_memory(self.project_folder(repo), "a.md", "토큰 %s 끝" % token)
        result = self.run_prepare()
        source = self.all_sources()[0]
        self.assertNotIn(token, self.staged(source))
        self.assertIn("[REDACTED:github]", self.staged(source))
        self.assertEqual(result["redactions"], {"github": 1})
        self.commit_all()
        snaps = os.path.join(self.root, ".state", "snapshots")
        for name in os.listdir(snaps):
            with open(os.path.join(snaps, name), encoding="utf-8") as handle:
                self.assertNotIn(token, handle.read())
        with open(prepare.prepare_json_path(self.root), encoding="utf-8") as handle:
            self.assertNotIn(token, handle.read())

    def test_permissions_and_layout(self):
        repo = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        self.add_memory(self.project_folder(repo), "a.md", "x")
        self.run_prepare()
        staging = common.staging_dir(self.root)
        self.assertEqual(mode(staging), 0o700)
        self.assertEqual(mode(os.path.join(staging, "1")), 0o700)
        self.assertEqual(mode(os.path.join(self.root, ".state", self.all_sources()[0]["redacted_path"])),
                         0o600)
        self.assertEqual(mode(common.run_json_path(self.root)), 0o600)
        # Nothing in staging/<batch> carries origin paths or hashes.
        for name in os.listdir(os.path.join(staging, "1")):
            self.assertFalse(name.endswith(".json"))

    def test_seal_check_and_clear(self):
        repo = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        self.add_memory(self.project_folder(repo), "a.md", "x")
        self.run_prepare()
        self.assertEqual(prepare.check_batch_staging(self.root, 1), [])
        prepare.seal_batch(self.root, 1)
        base = prepare.batch_dir(self.root, 1)
        self.assertEqual(mode(base), 0o555)
        for name in os.listdir(base):
            self.assertEqual(mode(os.path.join(base, name)), 0o444)
        os.chmod(base, 0o700)
        with open(os.path.join(base, "planted.md"), "w") as handle:
            handle.write("x")
        self.assertEqual(prepare.check_batch_staging(self.root, 1), ["extra:planted.md"])
        os.chmod(base, 0o555)
        self.run_prepare()  # clears sealed staging from the previous run
        self.assertFalse(os.path.exists(os.path.join(base, "planted.md")))

    def test_batches_split_by_domain_and_size(self):
        mine = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        work = self.make_repo("work", "git@github.com:%s/w.git" % WORK_ORG)
        for index in range(35):
            self.add_memory(self.project_folder(mine), "p%02d.md" % index, "개인 %d" % index)
        self.add_memory(self.project_folder(work), "w.md", "업무")
        self.run_prepare()
        run = self.run_json()
        sizes = [(batch["allowed_globs"], len(batch["sources"])) for batch in run["batches"]]
        self.assertEqual(sizes, [(["work/**"], 1), (["personal/**"], 30), (["personal/**"], 5)])
        self.assertEqual(common.validate_run(run), [])
        self.assertTrue(run["deviations"])
        self.assertEqual(len(run["base_sha"]), 40)

    def test_lock_is_taken(self):
        with common.wiki_lock(self.root):
            with self.assertRaises(common.LockBusy):
                self.run_prepare()
        with common.wiki_lock(self.root):
            self.run_prepare(locked=True)

    def test_id_encoding(self):
        repo = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        self.add_memory(self.project_folder(repo), "a b>c.md", "x")
        self.run_prepare()
        source_id = self.all_sources()[0]["id"]
        self.assertTrue(source_id.endswith("/a%20b%3Ec.md"), source_id)
        self.assertTrue(common.is_valid_source_id(source_id))


class LifecycleTest(PrepareCase):
    def setUp(self):
        PrepareCase.setUp(self)
        self.mine = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        self.folder = self.project_folder(self.mine)
        self.mem = self.add_memory(self.folder, "a.md", "첫 버전")
        self.sid = "mem:%s/a.md" % self.folder

    def test_commit_then_no_change(self):
        self.run_prepare()
        self.commit_all()
        entry = self.sources_json()[self.sid]
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["domain"], "personal")
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])

    def test_failed_batch_is_offered_again(self):
        self.run_prepare()
        self.run_prepare()  # no commit_batch: state did not move
        self.assertEqual(self.source(self.sid)["op"], "new")
        self.assertNotIn(self.sid, self.sources_json())

    def test_changed_and_deleted(self):
        self.run_prepare()
        self.commit_all()
        self.add_memory(self.folder, "a.md", "둘째 버전")
        self.run_prepare()
        source = self.source(self.sid, "changed")
        with open(os.path.join(self.root, ".state", source["diff_path"]), encoding="utf-8") as h:
            diff = h.read()
        self.assertIn("-첫 버전", diff)
        self.assertIn("+둘째 버전", diff)
        self.commit_all()
        os.unlink(self.mem)
        self.run_prepare()
        deleted = self.source(self.sid, "deleted")
        self.assertEqual(deleted["domain"], "personal")
        self.assertIsNone(deleted["redacted_path"])
        self.commit_all()
        self.assertEqual(self.sources_json()[self.sid]["status"], "deleted")
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])

    def test_domain_flip_withdraws_old_domain(self):
        self.run_prepare()
        self.commit_all()
        self.write_domains(overrides={self.sid: "work"})
        self.run_prepare()
        self.assertEqual(self.source(self.sid, "deleted")["domain"], "personal")
        self.assertEqual(self.source(self.sid, "new")["domain"], "work")
        # Only the work batch merges: the personal withdrawal stays pending.
        run = self.run_json()
        work_batch = [b for b in run["batches"] if b["allowed_globs"] == ["work/**"]][0]
        prepare.commit_batch(self.root, work_batch["batch_id"])
        prepare.finalize_run(self.root)
        entry = self.sources_json()[self.sid]
        self.assertEqual((entry["domain"], entry["withdraw"]), ("work", ["personal"]))
        self.run_prepare()
        self.assertEqual([(s["op"], s["domain"]) for s in self.all_sources()],
                         [("deleted", "personal")])
        self.commit_all()
        self.assertNotIn("withdraw", self.sources_json()[self.sid])
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])

    def test_sticky_domain_when_repo_vanishes(self):
        self.run_prepare()
        self.commit_all()
        shutil.rmtree(self.mine)
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])
        self.add_memory(self.folder, "a.md", "바뀜")
        self.run_prepare()
        self.assertEqual(self.source(self.sid)["domain"], "personal")

    def test_quarantine_withdraws_active(self):
        self.run_prepare()
        self.commit_all()
        self.add_memory(self.folder, "a.md", "이제 %s 내용" % TERM)
        result = self.run_prepare()
        self.assertEqual(self.source(self.sid, "deleted")["domain"], "personal")
        self.assertEqual(result["quarantined"], 1)

    def test_mass_deletion_is_held(self):
        for index in range(12):
            self.add_memory(self.folder, "m%02d.md" % index, "x %d" % index)
        self.run_prepare()
        self.commit_all()
        shutil.rmtree(os.path.join(self.projects, self.folder, "memory"))
        os.makedirs(os.path.join(self.projects, self.folder, "memory"))
        result = self.run_prepare()
        self.assertEqual(self.all_sources(), [])
        self.assertEqual(result["held_deletions"], {"mem": 13})
        self.assertIn("mass_deletion_held:mem", result["warnings"])

    def test_missing_source_root_is_not_deletion(self):
        self.run_prepare()
        self.commit_all()
        shutil.rmtree(self.projects)
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])


class InboxTest(PrepareCase):
    def test_consumed_not_withdrawn(self):
        path = self.add_inbox("work", "note1.md", "# 메모\n작업 메모")
        self.run_prepare()
        source = self.source("inbox:work/note1.md")
        self.assertEqual(source["domain"], "work")
        self.commit_all()
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".state", "inbox-done", "work",
                                                    "note1.md")))
        self.assertEqual(self.sources_json()["inbox:work/note1.md"]["status"], "consumed")
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])

    def test_changed_after_prepare_is_not_moved(self):
        path = self.add_inbox("personal", "n.md", "개인 메모")
        self.run_prepare()
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n추가")
        self.commit_all()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.sources_json()["inbox:personal/n.md"]["status"], "active")
        self.run_prepare()
        self.assertEqual(self.source("inbox:personal/n.md")["op"], "changed")

    def test_personal_inbox_with_work_term(self):
        self.add_inbox("personal", "n.md", "%s 회의" % TERM)
        result = self.run_prepare()
        self.assertEqual(self.all_sources(), [])
        self.assertEqual(result["quarantined"], 1)


class ManualAndContextTest(PrepareCase):
    def test_manual_edit_committed_and_emitted(self):
        page = os.path.join(self.root, "personal", "projects", "side.md")
        with open(page, "w", encoding="utf-8") as handle:
            handle.write("---\ntitle: 사이드\ntype: project\ndomain: personal\n---\n\n"
                         "## 현재 상태\n\n사람이 고친 상태\n")
        before = self.git(self.root, "rev-parse", "HEAD").stdout.decode().strip()
        self.run_prepare()
        run = self.run_json()
        self.assertNotEqual(run["base_sha"], before)
        status = self.git(self.root, "status", "--porcelain").stdout.decode()
        self.assertNotIn("personal/", status)
        source = self.source("manual:personal/projects/side.md")
        self.assertEqual((source["op"], source["domain"]), ("new", "personal"))
        with open(os.path.join(self.root, ".state", source["diff_path"]), encoding="utf-8") as h:
            self.assertIn("+사람이 고친 상태", h.read())
        # Not absorbed yet: offered again next run.
        self.run_prepare()
        self.source("manual:personal/projects/side.md")
        self.commit_all()
        # Kept as closed so pages may keep citing it (verify knows the id).
        self.assertEqual(self.sources_json()["manual:personal/projects/side.md"]["status"],
                         "closed")
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])

    def test_manual_edit_survives_failed_prepare(self):
        page = os.path.join(self.root, "personal", "projects", "side.md")
        with open(page, "w", encoding="utf-8") as handle:
            handle.write("---\ntitle: 사이드\ntype: project\ndomain: personal\n---\n\n본문\n")
        settings_path = os.path.join(self.root, "settings.json")
        with open(settings_path, encoding="utf-8") as handle:
            good = handle.read()
        bad = json.loads(good)
        bad["prompt_days"] = 0
        with open(settings_path, "w", encoding="utf-8") as handle:
            json.dump(bad, handle)
        with self.assertRaises(common.ConfigError):
            self.run_prepare()
        self.assertNotIn("personal/", self.git(self.root, "status", "--porcelain").stdout.decode())
        with open(settings_path, "w", encoding="utf-8") as handle:
            handle.write(good)
        self.run_prepare()
        self.assertEqual(self.source("manual:personal/projects/side.md")["op"], "new")

    def test_deleted_page_is_committed(self):
        page = os.path.join(self.root, "work", "notes", "old.md")
        with open(page, "w", encoding="utf-8") as handle:
            handle.write("---\ntitle: 옛 메모\ntype: note\ndomain: work\n---\n\n본문\n")
        self.git(self.root, "add", "--", "work/notes/old.md")
        self.git(self.root, "-c", "user.name=t", "-c", "user.email=t@example.com",
                 "commit", "-q", "-m", "seed")
        os.unlink(page)
        self.run_prepare()
        self.assertNotIn("work/", self.git(self.root, "status", "--porcelain").stdout.decode())
        self.assertEqual(self.all_sources(), [])
        tree = self.git(self.root, "ls-tree", "-r", "--name-only", "HEAD").stdout.decode()
        self.assertNotIn("work/notes/old.md", tree)

    def test_my_notes_context_per_domain(self):
        now_md = os.path.join(self.root, "now.md")
        with open(now_md, encoding="utf-8") as handle:
            text = handle.read()
        text = text.replace("### work\n", "### work\n\n업무 메모는 여기\n")
        text = text.replace("### personal\n", "### personal\n\n개인 메모는 여기\n")
        with open(now_md, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.add_inbox("personal", "n.md", "개인")
        self.run_prepare()
        status = self.git(self.root, "status", "--porcelain").stdout.decode()
        self.assertNotIn("now.md", status)  # committed before base_sha
        batches = prepare.load_prepare(self.root)["batches"]
        bid = [key for key, rec in batches.items() if rec["domain"] == "personal"][0]
        record = batches[bid]
        self.assertEqual(record["context"], ["staging/%s/context/now.md" % bid])
        with open(os.path.join(self.root, ".state", "staging", bid, "context", "now.md"),
                  encoding="utf-8") as handle:
            context = handle.read()
        self.assertIn("개인 메모는 여기", context)
        self.assertNotIn("업무 메모", context)
        ids = dict((source["id"], source["domain"]) for source in self.all_sources())
        self.assertEqual(ids, {"inbox:personal/n.md": "personal",
                               "notes:personal/now.md": "personal",
                               "notes:work/now.md": "work"})
        staged = self.staged(self.source("notes:personal/now.md"))
        self.assertIn("개인 메모는 여기", staged)
        self.assertNotIn("업무 메모", staged)

    def test_notes_only_edit_reaches_a_batch(self):
        now_md = os.path.join(self.root, "now.md")
        with open(now_md, encoding="utf-8") as handle:
            text = handle.read()
        with open(now_md, "w", encoding="utf-8") as handle:
            handle.write(text.replace("### personal\n", "### personal\n\n초안이 틀림\n"))
        self.run_prepare()
        self.assertEqual([s["id"] for s in self.all_sources()], ["notes:personal/now.md"])
        self.commit_all()
        self.run_prepare()
        self.assertEqual(self.all_sources(), [])  # unchanged notes are not offered again
        self.assertNotIn("my_notes_untagged:now.md", prepare.load_prepare(self.root)
                         ["summary"]["warnings"])
        with open(now_md, encoding="utf-8") as handle:
            text = handle.read()
        with open(now_md, "w", encoding="utf-8") as handle:
            handle.write(text.replace("## 내 메모\n", "## 내 메모\n\n태그 없는 메모\n"))
        self.run_prepare()
        summary = prepare.load_prepare(self.root)["summary"]
        self.assertIn("my_notes_untagged:now.md", summary["warnings"])
        self.assertEqual(self.all_sources(), [])  # untagged text is never staged


class PendingTest(PrepareCase):
    def test_pending_counts_and_finalize(self):
        mine = self.make_repo("mine", "git@github.com:%s/m.git" % ME)
        self.add_memory(self.project_folder(mine), "a.md", "개인")
        self.add_memory("-x-unknown", "u.md", "모름")
        kwargs = {"environ": self.env, "paths": self.paths(), "now": NOW, "fs_root": self.tmp}
        counts = prepare.pending_counts(self.root, **kwargs)
        self.assertEqual((counts["work"], counts["personal"], counts["unresolved"]), (0, 1, 1))
        self.assertEqual(prepare.pending_for_domain(counts, "work"), 1)
        self.assertEqual(prepare.pending_for_domain(counts, "personal"), 2)
        self.assertFalse(os.path.exists(common.run_json_path(self.root)))
        self.run_prepare()
        self.commit_all()
        counts = prepare.pending_counts(self.root, **kwargs)
        self.assertEqual((counts["personal"], counts["unresolved"]), (0, 0))
        # An unresolved source that becomes resolvable is offered as new.
        self.write_domains(overrides={"mem:-x-unknown/u.md": "work"})
        counts = prepare.pending_counts(self.root, **kwargs)
        self.assertEqual(counts["work"], 1)
        self.run_prepare()
        self.assertEqual(self.source("mem:-x-unknown/u.md")["op"], "new")


class HelpersTest(unittest.TestCase):
    def test_fs_encode(self):
        self.assertEqual(prepare.fs_encode("/a/.b/c_d e"), "-a--b-c-d-e")

    def test_parse_iso_date(self):
        self.assertEqual(prepare.parse_iso_date("2026-11-04"), "2026-11-04")
        self.assertIsNone(prepare.parse_iso_date("2026-13-01"))
        self.assertIsNone(prepare.parse_iso_date("yesterday"))
        local = datetime.datetime(2026, 11, 4, 12, 0).astimezone()
        self.assertEqual(prepare.parse_iso_date(local.isoformat()), "2026-11-04")

    def test_loose_frontmatter_nested(self):
        fm = prepare.loose_frontmatter("---\nname: x\nmetadata:\n  type: feedback\n"
                                       "  modified: 2026-11-01T00:00:00Z\ntags:\n  - a\n  - b\n---\n")
        self.assertEqual(fm["metadata.modified"], "2026-11-01T00:00:00Z")
        self.assertEqual(fm["tags"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
