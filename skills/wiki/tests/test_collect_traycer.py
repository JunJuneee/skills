"""collect's Traycer source: the local chat index and task folders.

Both databases and the task folders are synthetic files in the temp home."""

import datetime
import json
import os
import sqlite3
import unittest

import _helpers
import collect
import common
import wiki

DOMAINS = {"owners": {"WorkOrg": "work", "MeUser": "personal"}, "work_terms": ["acmecorp"],
           "overrides": {}, "redact_allow": [], "obsidian_plugins_allow": []}
NOW = datetime.datetime(2026, 3, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)


def ms(text):
    return int(collect.parse_time(text).timestamp() * 1000)


class TraycerCase(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        wiki.init_wiki(self.root, self.env)
        with open(os.path.join(self.root, "domains.json"), "w") as handle:
            json.dump(DOMAINS, handle)
        with open(collect.config_path(self.root), "w") as handle:
            json.dump({"traycer": True}, handle)
        self.chats_db = os.path.join(self.tmp, "chats.db")
        self.epics_db = os.path.join(self.tmp, "epics.db")
        self.folders = os.path.join(self.env["HOME"], ".traycer", "epics")
        self.env.update({"WIKI_SRC_TRAYCER_DB": self.chats_db,
                         "WIKI_SRC_TRAYCER_EPICS_DB": self.epics_db,
                         "WIKI_SRC_TRAYCER_EPICS_DIR": self.folders})
        conn = sqlite3.connect(self.chats_db)
        conn.execute("CREATE TABLE search_chat (chat_key TEXT PRIMARY KEY, epic_id TEXT, "
                     "chat_id TEXT, title TEXT, lifecycle_state TEXT)")
        conn.execute("CREATE TABLE search_doc (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                     "chat_key TEXT, tier TEXT, inter_agent INTEGER, created_at INTEGER, text TEXT)")
        conn.commit()
        conn.close()
        conn = sqlite3.connect(self.epics_db)
        conn.execute("CREATE TABLE local_epic (epic_id TEXT PRIMARY KEY, creation_payload TEXT, "
                     "list_projection_json TEXT)")
        conn.commit()
        conn.close()

    def epic(self, epic_id, title, owners):
        payload = {"repoIdentifiers": [{"owner": owner, "repo": "r"} for owner in owners]}
        conn = sqlite3.connect(self.epics_db)
        conn.execute("INSERT INTO local_epic VALUES (?, ?, ?)",
                     (epic_id, json.dumps(payload), json.dumps({"title": title})))
        conn.commit()
        conn.close()

    def chat(self, epic_id, chat_id, title, docs, state="active"):
        conn = sqlite3.connect(self.chats_db)
        key = "%s/%s" % (epic_id, chat_id)
        conn.execute("INSERT INTO search_chat VALUES (?, ?, ?, ?, ?)",
                     (key, epic_id, chat_id, title, state))
        for tier, inter_agent, at, text in docs:
            conn.execute("INSERT INTO search_doc (chat_key, tier, inter_agent, created_at, text) "
                         "VALUES (?, ?, ?, ?, ?)", (key, tier, inter_agent, ms(at), text))
        conn.commit()
        conn.close()

    def run_collect(self, **kwargs):
        return collect.collect(self.root, self.env, now=NOW, tools=object(), **kwargs)

    def note(self, domain):
        base = os.path.join(self.root, "inbox", domain, "activity")
        names = sorted(os.listdir(base)) if os.path.isdir(base) else []
        self.assertEqual(len(names), 1, names)
        self.assertTrue(names[0].startswith("traycer-"))
        with open(os.path.join(base, names[0]), encoding="utf-8") as handle:
            return handle.read()


class TraycerTest(TraycerCase):
    def test_conversations_go_to_the_task_domain(self):
        self.epic("epic-work", "결제 개편", ["WorkOrg"])
        self.epic("epic-home", "장난감", ["MeUser"])
        self.epic("epic-mixed", "섞인 작업", ["MeUser", "WorkOrg"])
        self.epic("epic-unknown", "모르는 작업", ["Stranger"])
        self.chat("epic-work", "c1", "환불 흐름 설계", [
            ("user", 0, "2026-03-09T01:00:00Z", "환불 흐름을\n## 설계해줘"),
            ("assistant", 0, "2026-03-09T01:10:00Z", "중간 답"),
            ("assistant", 0, "2026-03-09T01:20:00Z", "두 번째 답"),
            ("assistant", 0, "2026-03-09T01:30:00Z", "마지막 답: PR https://github.com/WorkOrg/r/pull/9"),
            ("user", 0, "2026-01-01T00:00:00Z", "옛 요청")])
        self.chat("epic-work", "c2", "하위 에이전트", [
            ("user", 1, "2026-03-09T02:00:00Z", "에이전트끼리의 요청"),
            ("assistant", 0, "2026-03-09T02:10:00Z", "하위 답")])
        self.chat("epic-home", "c3", "장난감 고치기", [
            ("user", 0, "2026-03-09T03:00:00Z", "바퀴 고쳐줘")])
        self.chat("epic-mixed", "c4", "섞인 대화", [
            ("user", 0, "2026-03-09T04:00:00Z", "회사 레포도 있는 작업")])
        self.chat("epic-unknown", "c5", "모르는 대화", [
            ("user", 0, "2026-03-09T05:00:00Z", "어디 것인지 모름")])
        self.chat("epic-home", "c6", "지운 대화", [
            ("user", 0, "2026-03-09T06:00:00Z", "지운 요청")], state="deleted")
        result = self.run_collect()
        self.assertEqual(result["status"], "ok")
        tally = result["sources"]["traycer"]
        self.assertEqual((tally["events"], tally["notes"], tally["skipped_unknown_domain"]),
                         (3, 2, 1))
        work, home = self.note("work"), self.note("personal")
        self.assertIn("## 작업: 결제 개편 (작업 id `epic-work`)", work)
        self.assertIn("### 대화: 환불 흐름 설계 (대화 id `c1` · 내 요청 1 · 답 3)", work)
        self.assertIn("나: 환불 흐름을 ## 설계해줘", work)  # one line, no forged heading
        self.assertIn("에이전트: 마지막 답: PR https://github.com/WorkOrg/r/pull/9", work)
        self.assertIn("두 번째 답", work)
        self.assertNotIn("중간 답", work)   # only the last replies
        self.assertNotIn("옛 요청", work)   # before the window
        self.assertNotIn("하위 에이전트", work)  # agent-to-agent only
        self.assertIn("섞인 대화", work)    # any work workspace makes the task work
        self.assertNotIn("장난감", work)
        self.assertIn("바퀴 고쳐줘", home)
        self.assertNotIn("결제", home)
        self.assertNotIn("모르는", work + home)
        self.assertNotIn("지운", work + home)
        self.assertEqual(collect.load_state(self.root)["cursors"],
                         {"traycer:local": "2026-03-10T12:00:00Z"})

    def test_artifacts_made_in_the_window_are_listed_with_paths(self):
        self.epic("epic-home", "장난감", ["MeUser"])
        self.chat("epic-home", "c3", "장난감 고치기", [
            ("user", 0, "2026-03-09T03:00:00Z", "계획 세워줘")])
        base = os.path.join(self.folders, "epic-home")
        os.makedirs(base)
        with open(os.path.join(base, "status.txt"), "w", encoding="utf-8") as handle:
            handle.write("Generated artifact status.\n"
                         "path\tkind\tbytes\tstate\ttitle\tcapturedAt\tcomments\n"
                         'wheel-plan\thtml\t10\tsynced\ttitle="바퀴 계획"\t'
                         "capturedAt=2026-03-09T04:00:00.000Z\tcomments: unknown\n"
                         "  wheel-plan/index.html\t10\tsynced\n"
                         'old-plan\tspec\t10\tsynced\ttitle="옛 계획"\t'
                         "capturedAt=2026-01-01T00:00:00.000Z\tcomments: unknown\n"
                         '../escape\thtml\t10\tsynced\ttitle="밖"\t'
                         "capturedAt=2026-03-09T04:00:00.000Z\tcomments: unknown\n")
        self.run_collect()
        note = self.note("personal")
        self.assertIn("- 산출물 바퀴 계획 (html) — `~/.traycer/epics/epic-home/artifacts/wheel-plan/`", note)
        self.assertNotIn("옛 계획", note)
        self.assertNotIn("escape", note)
        self.assertNotIn(self.env["HOME"], note)  # the home folder is written as ~

    def test_nothing_in_the_window_writes_no_note(self):
        self.epic("epic-home", "장난감", ["MeUser"])
        self.chat("epic-home", "c3", "장난감 고치기", [
            ("user", 0, "2026-01-01T00:00:00Z", "옛 요청")])
        result = self.run_collect()
        self.assertEqual((result["status"], result["notes"]), ("ok", 0))

    def test_missing_or_changed_database_is_a_failed_fetch(self):
        os.unlink(self.chats_db)
        self.assertEqual(self.run_collect()["errors"], ["traycer:traycer_missing"])
        conn = sqlite3.connect(self.chats_db)
        conn.execute("CREATE TABLE search_chat (chat_key TEXT)")
        conn.execute("CREATE TABLE search_doc (chat_key TEXT)")
        conn.commit()
        conn.close()
        self.assertEqual(self.run_collect()["errors"], ["traycer:traycer_schema"])
        self.assertEqual(collect.load_state(self.root)["cursors"], {})

    def test_missing_task_database_is_a_failed_fetch(self):
        os.unlink(self.epics_db)
        self.assertEqual(self.run_collect()["errors"], ["traycer:traycer_missing"])

    def test_full_domain_resumes_at_the_first_conversation_left_out(self):
        self.epic("epic-home", "장난감", ["MeUser"])
        total = collect.TRAYCER_MAX_CHATS + 2
        for i in range(total):
            self.chat("epic-home", "c%02d" % i, "대화 %02d" % i, [
                ("user", 0, "2026-03-09T03:%02d:00Z" % i, "요청 %02d" % i)])
        result = self.run_collect()
        self.assertEqual(result["notices"], ["traycer:truncated"])
        note = self.note("personal")
        self.assertIn("요청 00", note)
        self.assertIn("요청 39", note)
        self.assertNotIn("요청 40", note)
        self.assertEqual(collect.load_state(self.root)["cursors"],
                         {"traycer:local": "2026-03-09T03:40:00Z"})

    def test_exactly_full_domain_is_not_called_truncated(self):
        self.epic("epic-home", "장난감", ["MeUser"])
        for i in range(collect.TRAYCER_MAX_CHATS):
            self.chat("epic-home", "c%02d" % i, "대화 %02d" % i, [
                ("user", 0, "2026-03-09T03:%02d:00Z" % i, "요청 %02d" % i)])
        result = self.run_collect()
        self.assertEqual(result["notices"], [])
        self.assertNotIn("다음 수집에 들어온다", self.note("personal"))

    def test_flag_must_be_a_boolean(self):
        self.assertEqual(collect.validate_config({"traycer": False})["traycer"], [])
        with self.assertRaises(common.ConfigError):
            collect.validate_config({"traycer": [{}]})


if __name__ == "__main__":
    unittest.main()
