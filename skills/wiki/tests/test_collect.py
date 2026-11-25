"""collect: GitHub, Linear and Discord activity into inbox notes.

The two command line tools (gh, composio) are always a fake object; nothing
here reaches the network or a real account."""

import datetime
import json
import os
import stat
import sys
import unittest

import _helpers
import collect
import common
import prepare
import schedule
import wiki

DOMAINS = {"owners": {"WorkOrg": "work", "MeUser": "personal"}, "work_terms": ["acmecorp"],
           "overrides": {}, "redact_allow": [], "obsidian_plugins_allow": []}
NOW = datetime.datetime(2026, 3, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)
ME = "900"
GUILD = "500"


def pr(repo, number, title, user="me-login", state="closed", created="2026-03-09T01:00:00Z",
       closed=None, merged=None, body="", draft=False):
    return {"repository_url": "https://api.github.com/repos/%s" % repo, "number": number,
            "title": title, "user": {"login": user}, "state": state, "draft": draft,
            "created_at": created, "closed_at": closed, "body": body,
            "html_url": "https://github.com/%s/pull/%d" % (repo, number),
            "pull_request": {"merged_at": merged}}


def message(mid, channel, author, content, at="2026-03-09T05:00:00+00:00", mentions=(),
            bot=False, name=None):
    return {"id": str(mid), "channel_id": str(channel), "content": content, "timestamp": at,
            "author": {"id": author, "username": name or "user%s" % author, "bot": bot},
            "mentions": [{"id": m, "username": "user%s" % m} for m in mentions]}


class FakeTools(object):
    def __init__(self):
        self.calls = []
        self.search = {}      # query prefix -> items
        self.fail = set()     # "gh_token", "gh_search", or a composio slug
        self.linear = None
        self.discord_search = {"mine": [], "mentions": []}
        self.discord_threads = []
        self.discord_channels = {}
        self.discord_messages = {}

    def gh_token(self, login):
        self.calls.append(("gh_token", login))
        if "gh_token" in self.fail:
            raise collect.CollectError("gh_token_failed", login)
        return "token-%s" % login

    def gh_search(self, token, query, page):
        self.calls.append(("gh_search", token, query, page))
        if "gh_search" in self.fail:
            raise collect.CollectError("gh_api_failed", "search")
        for prefix, items in self.search.items():
            if query.startswith(prefix):
                return {"items": items if page == 1 else []}
        return {"items": []}

    def composio(self, slug, data, account=None):
        self.calls.append((slug, data, account))
        if slug in self.fail:
            raise collect.CollectError("composio_failed", slug)
        if slug == "LINEAR_RUN_QUERY_OR_MUTATION":
            return {"data": self.linear}
        if slug == "DISCORDBOT_SEARCH_GUILD_MESSAGES":
            rows = self.discord_search["mine" if "author_id" in data else "mentions"]
            rows = rows[data["offset"]:data["offset"] + data["limit"]]
            return {"messages": [[row] for row in rows], "threads": self.discord_threads}
        if slug == "DISCORDBOT_LIST_GUILD_CHANNELS":
            return {"channels": [{"id": cid, "name": name}
                                 for cid, name in self.discord_channels.items()]}
        if slug == "DISCORDBOT_LIST_MESSAGES":
            if data["channel_id"] in self.fail:
                raise collect.CollectError("composio_failed", slug)
            return {"messages": list(reversed(self.discord_messages.get(data["channel_id"], [])))}
        raise AssertionError(slug)


class CollectCase(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        wiki.init_wiki(self.root, self.env)
        with open(os.path.join(self.root, "domains.json"), "w") as handle:
            json.dump(DOMAINS, handle)
        self.tools = FakeTools()

    def configure(self, **cfg):
        with open(collect.config_path(self.root), "w") as handle:
            json.dump(cfg, handle)

    def run_collect(self, now=NOW, **kwargs):
        return collect.collect(self.root, self.env, now=now, tools=self.tools, **kwargs)

    def notes(self, domain):
        base = os.path.join(self.root, "inbox", domain, "activity")
        if not os.path.isdir(base):
            return {}
        out = {}
        for name in sorted(os.listdir(base)):
            with open(os.path.join(base, name), encoding="utf-8") as handle:
                out[name] = handle.read()
        return out

    def one_note(self, domain):
        notes = self.notes(domain)
        self.assertEqual(len(notes), 1, notes.keys())
        return list(notes.values())[0]


class ConfigTest(CollectCase):
    def test_without_config_nothing_happens(self):
        result = self.run_collect()
        self.assertEqual(result["status"], "not_configured")
        self.assertEqual(self.tools.calls, [])
        self.assertFalse(os.path.exists(collect.state_path(self.root)))

    def test_disabled(self):
        self.configure(enabled=False, github=[{"login": "me-login"}])
        self.assertEqual(self.run_collect()["status"], "disabled")
        self.assertEqual(self.tools.calls, [])

    def test_invalid_config_is_refused(self):
        for bad in ({"githubb": []}, {"github": [{"login": ""}]}, {"github": [{"user": "x"}]},
                    {"linear": [{"domain": "other", "account": "a"}]},
                    {"linear": [{"domain": "work"}]}, {"first_run_days": 0},
                    {"discord": [{"domain": "work", "guild_id": "1", "user_id": "2",
                                  "max_channels": 0}]}):
            with self.assertRaises(common.ConfigError) as ctx:
                collect.validate_config(bad)
            self.assertEqual(ctx.exception.reason, "collect_config_invalid", bad)

    def test_invalid_key_is_never_echoed(self):
        secret = "ghp_" + "a" * 36
        for bad in ({secret: 1}, {"github": [{secret: "x"}]}):
            with self.assertRaises(common.ConfigError) as ctx:
                collect.validate_config(bad)
            self.assertNotIn(secret, str(ctx.exception))
        self.configure(**{secret: 1})
        for args in (("--json", "collect"), ("collect",)):
            proc = self.run_cli(*args)
            self.assertEqual(proc.returncode, 1)
            self.assertNotIn(secret.encode(), proc.stdout + proc.stderr)

    def test_ids_and_names_are_plain(self):
        for bad in ({"discord": [{"domain": "work", "guild_id": "1\n## x", "user_id": "2"}]},
                    {"discord": [{"domain": "work", "guild_id": "1", "user_id": "a"}]},
                    {"github": [{"login": "me\n## x"}]}, {"github": [{"login": "-x"}]},
                    {"linear": [{"domain": "work", "account": "a b"}]}):
            with self.assertRaises(common.ConfigError):
                collect.validate_config(bad)

    def test_tool_paths_must_be_absolute(self):
        with self.assertRaises(common.ConfigError):
            collect.validate_config({"gh_path": "bin/gh"})

    def test_comment_keys_are_ignored(self):
        cfg = collect.validate_config({"_comment": "x", "github": [{"login": "a", "_why": "y"}]})
        self.assertEqual(cfg["github"], [{"login": "a"}])

    def test_config_file_is_gitignored(self):
        self.configure(github=[])
        proc = self.git(self.root, "check-ignore", "-q", "collect.json")
        self.assertEqual(proc.returncode, 0)


class WindowTest(unittest.TestCase):
    def test_first_run_and_old_cursor(self):
        day = datetime.timedelta(days=1)
        self.assertEqual(collect.window_start(None, NOW, 3), NOW - 3 * day)
        self.assertEqual(collect.window_start("2026-03-09T00:00:00Z", NOW, 3),
                         datetime.datetime(2026, 3, 9, tzinfo=datetime.timezone.utc))
        # A cursor from the future or older than the cap is not trusted.
        self.assertEqual(collect.window_start("2027-01-01T00:00:00Z", NOW, 3), NOW - 3 * day)
        self.assertEqual(collect.window_start("2025-01-01T00:00:00Z", NOW, 3),
                         NOW - collect.MAX_WINDOW_DAYS * day)

    def test_parse_time_fraction_digits(self):
        self.assertEqual(collect.parse_time("2026-03-09T05:00:00.5Z"),
                         collect.parse_time("2026-03-09T05:00:00.500000+00:00"))
        self.assertIsNone(collect.parse_time("yesterday"))


class GithubTest(CollectCase):
    def setUp(self):
        CollectCase.setUp(self)
        self.configure(github=[{"login": "me-login"}])
        self.tools.search["involves:@me"] = [
            pr("WorkOrg/api", 1, "로그 형식 통일", merged="2026-03-09T03:00:00Z",
               closed="2026-03-09T03:00:00Z", body="## 무엇\n로그에 trace_id를 넣는다"),
            pr("WorkOrg/api", 2, "남의 PR", user="other", merged="2026-03-09T04:00:00Z",
               closed="2026-03-09T04:00:00Z", body="남의 본문"),
            pr("workorg/web", 3, "새 화면", state="open"),
            pr("MeUser/toy", 4, "장난감 고침", merged="2026-03-09T02:00:00Z",
               closed="2026-03-09T02:00:00Z"),
            pr("Stranger/lib", 5, "모르는 곳", merged="2026-03-09T02:00:00Z"),
            pr("WorkOrg/api", 6, "예전에 병합", merged="2026-01-01T00:00:00Z",
               closed="2026-01-01T00:00:00Z"),
        ]
        self.tools.search["is:pr is:open review-requested"] = [
            pr("WorkOrg/api", 7, "봐 달라는 PR", user="other", state="open")]

    def test_notes_go_to_the_owner_domain(self):
        result = self.run_collect()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["notes"], 2)
        self.assertEqual(result["sources"]["github"]["skipped_unknown_owner"], 1)
        work, personal = self.one_note("work"), self.one_note("personal")
        self.assertIn("## 병합된 PR (2)", work)
        self.assertIn("[WorkOrg/api#1](https://github.com/WorkOrg/api/pull/1) 로그 형식 통일", work)
        self.assertIn("본문 발췌: ## 무엇 로그에 trace_id를 넣는다", work)
        self.assertNotIn("남의 본문", work)  # only my own PR bodies
        self.assertIn("## 새로 연 PR (아직 열려 있음) (1)", work)  # owner match ignores case
        self.assertIn("## 내가 리뷰할 PR", work)
        self.assertIn("봐 달라는 PR", work)
        self.assertNotIn("예전에 병합", work)
        self.assertNotIn("장난감", work)
        self.assertIn("장난감 고침", personal)
        self.assertNotIn("WorkOrg", personal)
        self.assertNotIn("모르는 곳", work + personal)

    def test_note_is_private_and_absorb_sees_it(self):
        self.run_collect()
        base = os.path.join(self.root, "inbox", "work", "activity")
        path = os.path.join(base, os.listdir(base)[0])
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(base).st_mode), 0o700)
        self.assertNotIn(b"inbox", self.git(self.root, "status", "--porcelain",
                                             "--untracked-files=all").stdout)
        items = prepare.discover_inbox(self.root)
        self.assertEqual(sorted((item["domain"], item["kind"]) for item in items),
                         [("personal", "inbox"), ("work", "inbox")])
        self.assertTrue(all(item["id"].startswith("inbox:%s/activity/github-" % item["domain"])
                            for item in items))

    def test_cursor_moves_only_on_success(self):
        self.run_collect()
        query = [call[2] for call in self.tools.calls if call[0] == "gh_search"][0]
        self.assertEqual(query, "involves:@me updated:>=2026-03-07T12:00:00Z")  # 3 days back
        self.tools.calls = []
        later = NOW + datetime.timedelta(hours=5)
        self.tools.fail.add("gh_search")
        result = self.run_collect(now=later)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["github:gh_api_failed"])
        self.tools.fail.clear()
        self.tools.calls = []
        self.run_collect(now=later + datetime.timedelta(hours=1))
        query = [call[2] for call in self.tools.calls if call[0] == "gh_search"][0]
        self.assertEqual(query, "involves:@me updated:>=2026-03-10T12:00:00Z")  # the first run

    def test_token_failure(self):
        self.tools.fail.add("gh_token")
        result = self.run_collect()
        self.assertEqual(result["errors"], ["github:gh_token_failed"])
        self.assertEqual(self.notes("work"), {})

    def test_dry_run_writes_nothing(self):
        result = self.run_collect(dry_run=True)
        self.assertEqual(result["events"], 5)  # four changes and one new review request
        self.assertEqual(self.notes("work"), {})
        self.assertFalse(os.path.exists(collect.state_path(self.root)))

    def test_nothing_new_writes_no_note_but_moves_the_cursor(self):
        self.tools.search["involves:@me"] = []
        self.tools.search["is:pr is:open review-requested"] = []
        result = self.run_collect()
        self.assertEqual((result["status"], result["notes"]), ("ok", 0))
        self.assertEqual(self.notes("work"), {})
        self.assertEqual(collect.load_state(self.root)["cursors"],
                         {"github:me-login": "2026-03-10T12:00:00Z"})

    def test_a_new_review_request_is_an_event_once(self):
        self.tools.search["involves:@me"] = []
        self.assertEqual(self.run_collect()["notes"], 1)
        self.assertIn("봐 달라는 PR", self.one_note("work"))
        # The same standing request is not written again.
        self.assertEqual(self.run_collect(now=NOW + datetime.timedelta(hours=1))["notes"], 0)

    def test_review_request_is_listed_once(self):
        self.tools.search["involves:@me"] = [pr("WorkOrg/api", 7, "봐 달라는 PR", user="other",
                                                state="open")]
        self.run_collect()
        self.assertEqual(self.one_note("work").count("봐 달라는 PR"), 1)

    def test_full_window_resumes_at_the_last_item(self):
        collect_pages = collect.GITHUB_MAX_PAGES
        items = [dict(pr("WorkOrg/api", n, "병합 %d" % n, merged="2026-03-09T03:00:00Z",
                         closed="2026-03-09T03:00:00Z"), updated_at="2026-03-09T03:00:%02dZ" % (n % 60))
                 for n in range(100)]
        tools = self.tools
        tools.gh_search = lambda token, query, page: {
            "items": items if query.startswith("involves") and page <= collect_pages else []}
        result = self.run_collect()
        self.assertEqual(result["notices"], ["github:truncated"])
        self.assertEqual(collect.load_state(self.root)["cursors"]["github:me-login"],
                         "2026-03-09T03:00:59Z")

    def test_since_days_only_reaches_further_back(self):
        self.run_collect()
        self.tools.calls = []
        later = NOW + datetime.timedelta(days=3)
        self.run_collect(now=later, since_days=1)  # shorter than the gap: the cursor wins
        query = [call[2] for call in self.tools.calls if call[0] == "gh_search"][0]
        self.assertEqual(query, "involves:@me updated:>=2026-03-10T12:00:00Z")
        for bad in (0, -1, 31):
            with self.assertRaises(common.WikiError) as ctx:
                self.run_collect(since_days=bad)
            self.assertEqual(ctx.exception.reason, "since_days_invalid")

    def test_write_failure_shows_absorb_nothing(self):
        real = collect.stage_activity_note
        calls = []

        def flaky(root, text):
            calls.append(1)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(root, text)

        collect.stage_activity_note = flaky
        try:
            result = self.run_collect()
        finally:
            collect.stage_activity_note = real
        # Both notes are written out before either is published.
        self.assertEqual(result["errors"], ["github:write_failed"])
        self.assertEqual((self.notes("work"), self.notes("personal")), ({}, {}))
        self.assertEqual(collect.load_state(self.root)["cursors"], {})
        self.assertEqual([n for n in os.listdir(common.state_dir(self.root))
                          if n.startswith(".collect-")], [])

    def test_unexpected_shape_is_a_failed_fetch(self):
        self.tools.search["involves:@me"] = [{"repository_url": "https://api.github.com/repos/WorkOrg/api",
                                              "user": "not-a-dict", "pull_request": {}}]
        result = self.run_collect()
        self.assertEqual(result["errors"], ["github:invalid_response"])
        self.assertEqual(collect.load_state(self.root)["cursors"], {})

    def test_concurrent_collect_is_skipped(self):
        with collect.collect_lock(self.root) as held:
            self.assertTrue(held)
            self.assertEqual(self.run_collect()["status"], "busy")
        self.assertEqual(self.tools.calls, [])
        self.assertEqual(self.run_collect()["status"], "ok")

    def test_note_names_are_never_reused(self):
        a = collect.write_activity_note(self.root, "work", "github", "하나\n", NOW)
        self.assertRegex(os.path.basename(a), r"^github-\d{8}-\d{6}\.md$")
        b = collect.write_activity_note(self.root, "work", "github", "둘\n", NOW)
        self.assertRegex(os.path.basename(b), r"^github-\d{8}-\d{6}-2\.md$")
        # absorb consumed both and moved them to inbox-done.
        done = os.path.join(common.state_dir(self.root), "inbox-done", "work")
        os.makedirs(done, exist_ok=True)
        for path in (a, b):
            os.rename(path, os.path.join(done, os.path.basename(path)))
        c = collect.write_activity_note(self.root, "work", "github", "셋\n", NOW)
        self.assertRegex(os.path.basename(c), r"^github-\d{8}-\d{6}-3\.md$")
        self.assertEqual([n for n in os.listdir(common.state_dir(self.root))
                          if n.startswith(".collect-")], [])


class BackfillTest(CollectCase):
    """--from/--to: a past slice, cursors untouched."""

    WINDOW = ("2026-03-01", "2026-03-03")

    def test_window_bounds(self):
        since, until = collect.backfill_window("2026-03-01", "2026-03-03", NOW)
        self.assertEqual(until - since, datetime.timedelta(days=3, seconds=-1))
        self.assertEqual(since.astimezone().strftime("%Y-%m-%d %H:%M:%S"), "2026-03-01 00:00:00")
        # The end never passes now.
        _since, until = collect.backfill_window("2026-03-09", "2026-03-12", NOW)
        self.assertEqual(until, NOW)
        for bad in (("2026-03-03", "2026-03-01"), ("2026-03-11", "2026-03-12"),
                    ("2026-02-01", "2026-02-20"), ("x", "2026-03-01"), (None, None)):
            with self.assertRaises(common.WikiError) as ctx:
                collect.backfill_window(bad[0], bad[1], NOW)
            self.assertEqual(ctx.exception.reason, "window_invalid", bad)
        with self.assertRaises(common.WikiError):
            self.run_collect(window=self.WINDOW, since_days=2)

    def test_github_slice_by_what_happened_in_it(self):
        self.configure(github=[{"login": "me-login"}])
        local_noon = lambda day: collect.iso_z(
            datetime.datetime.strptime(day + " 12:00", "%Y-%m-%d %H:%M").astimezone())
        self.tools.search["involves:@me merged:"] = [
            pr("WorkOrg/api", 1, "구간 안 병합", merged=local_noon("2026-03-02"),
               closed=local_noon("2026-03-02"), created=local_noon("2026-02-20"))]
        self.tools.search["involves:@me created:"] = [
            pr("WorkOrg/api", 2, "구간 안에 열고 나중에 병합", created=local_noon("2026-03-03"),
               merged=local_noon("2026-03-08"), closed=local_noon("2026-03-08")),
            pr("WorkOrg/api", 1, "구간 안 병합", merged=local_noon("2026-03-02"),
               closed=local_noon("2026-03-02"), created=local_noon("2026-02-20"))]
        self.tools.search["is:pr is:open review-requested"] = [
            pr("WorkOrg/api", 7, "지금의 리뷰 요청", user="other", state="open")]
        self.run_collect()  # a normal run first: it owns the cursor
        cursors = dict(collect.load_state(self.root)["cursors"])
        last_run = collect.load_state(self.root)["last_run"]
        for path in [os.path.join(self.root, "inbox", "work", "activity", n)
                     for n in self.notes("work")]:
            os.unlink(path)
        self.tools.calls = []
        result = self.run_collect(window=self.WINDOW)
        self.assertEqual((result["status"], result["notes"]), ("ok", 1))
        queries = [call[2] for call in self.tools.calls if call[0] == "gh_search"]
        self.assertEqual([q.split(":")[1].split(" ")[1] for q in queries],
                         ["merged", "created", "closed"])
        self.assertTrue(all(".." in q and "updated" not in q for q in queries))
        note = self.one_note("work")
        self.assertEqual(note.splitlines()[2], collect.BACKFILL_LINE)
        self.assertIn("## 병합된 PR (1)", note)                     # listed once
        self.assertIn("## 이 기간에 새로 연 PR (그 뒤의 상태는 여기 없음) (1)", note)
        self.assertNotIn("지금의 리뷰 요청", note)
        state = collect.load_state(self.root)
        self.assertEqual((state["cursors"], state["last_run"]), (cursors, last_run))
        base = os.path.join(self.root, "inbox", "work", "activity")
        name = os.listdir(base)[0]
        _since, until = collect.backfill_window(self.WINDOW[0], self.WINDOW[1], NOW)
        self.assertEqual(int(os.stat(os.path.join(base, name)).st_mtime), int(until.timestamp()))
        self.assertTrue(name.startswith("github-20260303-235959"))

    def test_linear_and_discord_are_bounded(self):
        self.configure(linear=[{"domain": "work", "account": "acct-1"}],
                       discord=[{"domain": "work", "guild_id": GUILD, "user_id": ME}])
        self.tools.linear = {"changed": {"pageInfo": {"hasNextPage": False}, "nodes": [{
            "identifier": "T-1", "title": "구간 안에 끝남", "url": "https://linear.example/T-1",
            "createdAt": "2026-01-01T00:00:00.000Z", "updatedAt": "2026-03-09T00:00:00.000Z",
            "completedAt": "2026-03-02T03:00:00.000Z", "canceledAt": None,
            "state": {"name": "Done", "type": "completed"}, "comments": {"nodes": [
                {"createdAt": "2026-03-09T00:00:00.000Z", "body": "구간 뒤 댓글",
                 "user": {"name": "동료", "isMe": False}}]}}]},
            "open": {"pageInfo": {"hasNextPage": False}, "nodes": [
                {"identifier": "T-9", "title": "지금 열린 일", "state": {"name": "Todo"}}]}}
        self.run_collect(window=self.WINDOW)
        note = [text for text in self.notes("work").values() if "Linear" in text][0]
        self.assertIn("## 끝난 이슈 (완료·취소) (1)", note)
        self.assertNotIn("구간 뒤 댓글", note)
        self.assertNotIn("지금 열린 일", note)
        self.assertNotIn("미완료 이슈", note)
        query = [c[1]["query_or_mutation"] for c in self.tools.calls
                 if c[0] == "LINEAR_RUN_QUERY_OR_MUTATION"][0]
        self.assertIn("completedAt: {gte:", query)
        self.assertIn("lte:", query)
        searches = [c[1] for c in self.tools.calls if c[0] == "DISCORDBOT_SEARCH_GUILD_MESSAGES"]
        self.assertTrue(searches and all("max_id" in data for data in searches))
        self.assertEqual(collect.load_state(self.root)["cursors"], {})

    def test_only_some_sources(self):
        self.configure(github=[{"login": "me-login"}],
                       linear=[{"domain": "work", "account": "acct-1"}])
        result = self.run_collect(only=("github",))
        self.assertEqual(list(result["sources"]), ["github"])
        self.assertFalse([c for c in self.tools.calls if c[0] == "LINEAR_RUN_QUERY_OR_MUTATION"])
        with self.assertRaises(common.WikiError) as ctx:
            self.run_collect(only=("nope",))
        self.assertEqual(ctx.exception.reason, "source_invalid")


class LinearTest(CollectCase):
    def setUp(self):
        CollectCase.setUp(self)
        self.configure(linear=[{"domain": "work", "account": "acct-1"}])

        def issue(key, title, **extra):
            node = {"identifier": key, "title": title, "url": "https://linear.example/%s" % key,
                    "createdAt": "2026-01-01T00:00:00.000Z", "updatedAt": "2026-03-09T05:00:00.000Z",
                    "completedAt": None, "canceledAt": None,
                    "state": {"name": "작업 중", "type": "started"}, "team": {"key": "T"},
                    "project": None, "parent": None, "assignee": {"isMe": True, "name": "나"},
                    "comments": {"nodes": []}}
            node.update(extra)
            return node

        self.tools.linear = {
            "viewer": {"name": "나"},
            "changed": {"pageInfo": {"hasNextPage": False}, "nodes": [
                issue("T-1", "끝낸 일", completedAt="2026-03-09T04:00:00.000Z",
                      state={"name": "Done", "type": "completed"}),
                issue("T-2", "새 일", createdAt="2026-03-09T01:00:00.000Z",
                      project={"name": "큰 프로젝트"}),
                issue("T-3", "하던 일", comments={"nodes": [
                    {"createdAt": "2026-03-09T02:00:00.000Z", "body": "확인 부탁",
                     "user": {"name": "동료", "isMe": False}},
                    {"createdAt": "2026-01-01T00:00:00.000Z", "body": "옛 댓글",
                     "user": {"name": "동료", "isMe": False}}]}),
            ]},
            "open": {"pageInfo": {"hasNextPage": False},
                     "nodes": [issue("T-2", "새 일"), issue("T-3", "하던 일")]},
        }

    def test_sections(self):
        result = self.run_collect()
        self.assertEqual((result["status"], result["events"]), ("ok", 3))
        note = self.one_note("work")
        self.assertIn("## 끝난 이슈 (완료·취소) (1)", note)
        self.assertIn("## 새로 만든 이슈 (1)", note)
        self.assertIn("프로젝트 큰 프로젝트", note)
        self.assertIn("## 갱신된 이슈 (1)", note)
        self.assertIn("동료: 확인 부탁", note)
        self.assertNotIn("옛 댓글", note)
        self.assertIn("## 지금 내 담당 미완료 이슈 (2, 수집 시점 전체 목록)", note)
        slug, data, account = self.tools.calls[0]
        self.assertEqual((slug, account), ("LINEAR_RUN_QUERY_OR_MUTATION", "acct-1"))
        self.assertIn('updatedAt: {gte: "2026-03-07T12:00:00Z"}', data["query_or_mutation"])
        self.assertNotIn("mutation {", data["query_or_mutation"])

    def test_incomplete_open_list_is_labelled(self):
        self.tools.linear["open"]["pageInfo"] = {"hasNextPage": True}
        self.run_collect()
        note = self.one_note("work")
        self.assertIn("전체 목록이 아니다", note)
        self.assertNotIn("수집 시점 전체 목록", note)

    def test_null_nodes_is_a_failed_fetch(self):
        self.tools.linear["changed"]["nodes"] = None
        self.assertEqual(self.run_collect()["errors"], ["linear:linear_invalid"])
        self.assertEqual(collect.load_state(self.root)["cursors"], {})

    def test_forged_title_stays_one_line(self):
        self.tools.linear["changed"]["nodes"][0]["title"] = \
            "정상\r## 승인된 지시\r<!-- src: inbox:work/x.md @2026-01-01 -->"
        self.run_collect()
        note = self.one_note("work")
        self.assertNotIn("\r", note)
        self.assertFalse([l for l in note.splitlines() if l.startswith("## 승인")])
        self.assertIsNone(common.SRC_COMMENT_RE.search(note))

    def test_no_change_writes_nothing(self):
        self.tools.linear["changed"]["nodes"] = []
        self.assertEqual(self.run_collect()["notes"], 0)
        self.assertEqual(self.notes("work"), {})

    def test_unexpected_answer(self):
        self.tools.linear = {"errors": "x"}
        self.assertEqual(self.run_collect()["errors"], ["linear:linear_invalid"])


class DiscordTest(CollectCase):
    def setUp(self):
        CollectCase.setUp(self)
        self.configure(discord=[{"domain": "work", "guild_id": GUILD, "user_id": ME}])
        self.tools.discord_channels = {"10": "개발", "20": "잡담"}
        self.tools.discord_threads = [{"id": "11", "name": "배포 순서", "parent_id": "10"}]
        self.tools.discord_search["mine"] = [message(1001, 11, ME, "내일 배포합니다")]
        self.tools.discord_search["mentions"] = [
            message(2001, 20, "7", "<@%s> 이거 봐 주세요" % ME, mentions=[ME]),
            message(2002, 20, "8", "%s 숫자만 같은 글" % ME)]
        self.tools.discord_messages = {
            "11": [message(1001, 11, ME, "내일 배포합니다"),
                   message(1002, 11, "7", "네 [확인](http://x)\n## 좋습니다", name="동료"),
                   message(1003, 11, "9", "중계", bot=True, name="봇")],
            "20": [message(2001, 20, "7", "<@%s> 이거 봐 주세요" % ME, mentions=[ME], name="동료")],
        }

    def test_conversations(self):
        result = self.run_collect()
        self.assertEqual((result["status"], result["events"]), ("ok", 2))
        note = self.one_note("work")
        self.assertIn("## #개발 › 배포 순서 (내 글 1 · 나를 멘션 0)", note)
        self.assertIn("## #잡담 (내 글 0 · 나를 멘션 1)", note)
        self.assertIn("나: 내일 배포합니다", note)
        self.assertIn("동료: 네 (확인)(http://x) ## 좋습니다", note)  # one line, no link, no heading
        self.assertIn("봇(봇): 중계", note)
        self.assertIn("동료: @나 이거 봐 주세요", note)
        self.assertIn("https://discord.com/channels/%s/11/1001" % GUILD, note)
        listed = [call[1] for call in self.tools.calls if call[0] == "DISCORDBOT_LIST_MESSAGES"]
        self.assertEqual(sorted((d["channel_id"], d["after"]) for d in listed),
                         [("11", "1000"), ("20", "2000")])

    def test_unreadable_channel_is_reported(self):
        self.tools.fail.add("20")
        result = self.run_collect()
        self.assertEqual(result["sources"]["discord"]["unread_channels"], 1)
        note = self.one_note("work")
        self.assertIn("## 못 읽은 채널", note)
        self.assertIn("나: 내일 배포합니다", note)
        # The mention itself (a search hit) is kept without its surroundings.
        self.assertIn("앞뒤 대화는 읽지 못함", note)
        self.assertIn("@나 이거 봐 주세요", note)

    def test_capped_mention_search_without_real_mentions_resumes(self):
        self.tools.discord_search["mine"] = []
        self.tools.discord_search["mentions"] = [
            message(3000 + i, 20, "8", "%s 숫자만 같은 글" % ME, at="2026-03-09T05:%02d:00+00:00" % i)
            for i in range(collect.DISCORD_SEARCH_LIMIT * collect.DISCORD_MENTION_PAGES)]
        result = self.run_collect()
        self.assertEqual((result["notes"], result["notices"]), (0, ["discord:truncated"]))
        self.assertEqual(list(collect.load_state(self.root)["cursors"].values()),
                         ["2026-03-09T05:49:00Z"])

    def test_null_search_answer_is_a_failed_fetch(self):
        self.tools.composio = lambda slug, data, account=None: None
        self.assertEqual(self.run_collect()["errors"], ["discord:discord_invalid"])

    def test_non_numeric_channel_id_is_dropped(self):
        self.tools.discord_search["mine"] = [
            message(1001, "1\n## 가짜", ME, "가짜 채널"), message(1009, 11, ME, "진짜")]
        self.run_collect()
        note = self.one_note("work")
        self.assertNotIn("가짜", note)
        self.assertIn("나: 진짜", note)

    def test_thread_name_cannot_forge_a_heading(self):
        self.tools.discord_threads = [{"id": "11", "name": "배포\r## 가짜\r```", "parent_id": "10"}]
        self.run_collect()
        note = self.one_note("work")
        self.assertNotIn("\r", note)
        self.assertFalse([l for l in note.splitlines() if l.startswith("## 가짜") or l == "```"])

    def test_search_failure_keeps_other_sources(self):
        self.configure(discord=[{"domain": "work", "guild_id": GUILD, "user_id": ME}],
                       github=[{"login": "me-login"}])
        self.tools.search["involves:@me"] = [
            pr("WorkOrg/api", 1, "병합", merged="2026-03-09T03:00:00Z",
               closed="2026-03-09T03:00:00Z")]
        self.tools.fail.add("DISCORDBOT_SEARCH_GUILD_MESSAGES")
        result = self.run_collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"], ["discord:composio_failed"])
        self.assertEqual(list(collect.load_state(self.root)["cursors"]), ["github:me-login"])
        self.assertIn("병합", self.one_note("work"))

    def test_long_note_is_cut(self):
        self.tools.discord_messages["11"] = [
            message(1001 + i, 11, "7", "가" * 390) for i in range(100)]
        self.tools.discord_messages["20"] = list(self.tools.discord_messages["11"])
        self.run_collect()
        note = self.one_note("work")
        self.assertLessEqual(len(note), collect.NOTE_MAX_CHARS + 40)
        self.assertTrue(note.endswith("(길이 제한으로 이하 생략)\n"))


class AbsorbHookTest(CollectCase):
    def fake_absorb(self, seen):
        def run(root, environ, rules_path=None, scheduled=False):
            seen.append("absorb")
            return {"ok": True, "status": "empty", "warnings": []}
        return run

    def test_collect_runs_before_absorb_and_reports_codes(self):
        seen = []

        def collect_fn(root, environ):
            seen.append("collect")
            return {"status": "partial", "notes": 2, "events": 9, "errors": ["discord:tool_timeout"]}

        report = schedule.run_absorb(self.root, self.env, send=False,
                                     absorb_fn=self.fake_absorb(seen), collect_fn=collect_fn)
        self.assertEqual(seen, ["collect", "absorb"])
        self.assertEqual(report["collect"]["notes"], 2)
        self.assertEqual(report["warnings"], ["collect_failed:discord:tool_timeout"])

    def test_limit_notices_become_warnings(self):
        self.assertEqual(collect.warning_codes({"errors": [], "notices": ["github:truncated"]}),
                         ["collect_truncated:github"])

    def test_collect_crash_does_not_stop_absorb(self):
        seen = []

        def collect_fn(root, environ):
            raise RuntimeError("boom")

        report = schedule.run_absorb(self.root, self.env, send=False,
                                     absorb_fn=self.fake_absorb(seen), collect_fn=collect_fn)
        self.assertEqual(seen, ["absorb"])
        self.assertEqual(report["warnings"], ["collect_failed:internal_error"])

    def test_not_configured_adds_nothing(self):
        seen = []
        report = schedule.run_absorb(self.root, self.env, send=False,
                                     absorb_fn=self.fake_absorb(seen))
        self.assertNotIn("collect", report)
        self.assertEqual(report["warnings"], [])

    def test_skipped_when_not_due_or_turned_off(self):
        seen = []

        def collect_fn(root, environ):
            seen.append("collect")
            return {"status": "ok", "notes": 0, "events": 0, "errors": []}

        schedule.run_absorb(self.root, self.env, send=False, absorb_fn=self.fake_absorb(seen),
                            collect_fn=collect_fn, do_collect=False)
        self.assertEqual(seen, ["absorb"])
        # The manual run above is today's run: the scheduled tick is not due.
        self.assertIsNone(schedule.run_absorb(self.root, self.env, scheduled=True, send=False,
                                              absorb_fn=self.fake_absorb(seen),
                                              collect_fn=collect_fn))
        self.assertEqual(seen, ["absorb"])


class CliTest(CollectCase):
    def test_collect_without_config(self):
        proc = self.run_cli("--json", "collect")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(json.loads(proc.stdout.decode())["status"], "not_configured")

    def test_invalid_config_reason(self):
        self.configure(nope=1)
        proc = self.run_cli("--json", "collect")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "collect_config_invalid")

    def test_status_shows_last_collect_errors(self):
        self.configure(github=[{"login": "me-login"}])
        self.tools.fail.add("gh_token")
        self.run_collect()
        info = wiki.status_info(self.root, self.env)
        self.assertTrue(info["collect"]["configured"])
        self.assertIn("collect_failed:github:gh_token_failed", info["warnings"])


class LaunchdHealthTest(CollectCase):
    def fake_launchctl(self, text, code=0):
        path = os.path.join(self.tmp, "launchctl")
        with open(path, "w") as handle:
            handle.write("#!%s\nimport sys\nsys.stdout.write(%r)\nsys.exit(%d)\n"
                         % (sys.executable, text, code))
        os.chmod(path, 0o755)
        return path

    def test_last_exit_code(self):
        tool = self.fake_launchctl("state = not running\n\tlast exit code = 78: EX_CONFIG\n")
        self.assertEqual(schedule.job_last_exit(self.env, "x", launchctl=tool, uid=501), 78)
        tool = self.fake_launchctl("state = not running\n\tlast exit code = (never exited)\n")
        self.assertIsNone(schedule.job_last_exit(self.env, "x", launchctl=tool, uid=501))
        tool = self.fake_launchctl("", code=113)  # not loaded
        self.assertIsNone(schedule.job_last_exit(self.env, "x", launchctl=tool, uid=501))

    def test_root_under_a_guarded_folder(self):
        home = os.path.realpath(self.env["HOME"])
        self.assertTrue(schedule.root_protected(os.path.join(home, "Desktop", "x", "wiki"), self.env))
        self.assertTrue(schedule.root_protected(os.path.join(home, "Documents"), self.env))
        self.assertFalse(schedule.root_protected(os.path.join(home, "wiki"), self.env))
        self.assertFalse(schedule.root_protected(os.path.join(home, "Desktop2", "wiki"), self.env))

    def test_status_warns_when_launchd_cannot_run_the_job(self):
        agents = os.path.join(self.tmp, "LaunchAgents")
        os.makedirs(agents)
        import plistlib
        with open(os.path.join(agents, "io.github.local.wiki-absorb.plist"), "wb") as handle:
            plistlib.dump({"ProgramArguments": ["/usr/bin/python3", "/nowhere/wiki.py"]}, handle)
        env = dict(self.env, WIKI_LAUNCH_AGENTS_DIR=agents,
                   WIKI_LAUNCHCTL=self.fake_launchctl("\tlast exit code = 78: EX_CONFIG\n"))
        self.assertIn("launchd_failing:78", wiki.status_info(self.root, env)["warnings"])
        env["WIKI_LAUNCHCTL"] = self.fake_launchctl("\tlast exit code = 0\n")
        warnings = wiki.status_info(self.root, env)["warnings"]
        self.assertFalse([w for w in warnings if w.startswith("launchd_failing")])


if __name__ == "__main__":
    unittest.main()
