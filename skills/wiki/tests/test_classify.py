"""Per-prompt domain classification (dev:prompt_classify): classify.py,
prepare.build_prompt_items/gather, absorb.build_classify_argv/prompt_classifier
and the tools_off request. The runner is a fake callable; fixtures are
synthetic and nothing touches the real wiki, ~/.claude or the network."""

import contextlib
import datetime
import io
import json
import os
import re
import stat
import time
import unittest
from unittest import mock

import _helpers
import absorb
import classify
import common
import prepare
import redact
import verify
import wiki

NOW = datetime.datetime(2026, 11, 6, 12, 0)
TERM = "AcmeCorp"
DAY = "2026-11-05"


def j(*parts):
    return "".join(parts)


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def noon(date_text):
    moment = datetime.datetime.strptime(date_text, "%Y-%m-%d").replace(hour=12)
    return time.mktime(moment.timetuple())


def rec(n, text, date=DAY, cwd=None, epic=None, session=None):
    """A prompt record n minutes after midnight-ish; n orders the records."""
    return {"ts": noon(date) + n, "date": date, "time": "10:%02d" % (n % 60), "label": "x",
            "cwd": cwd, "epic": epic, "text": text, "session": session}


def class_of(classes, record):
    value = classes.get(classify.prompt_key(record))
    return value["c"] if value and value["c"] in common.DOMAINS else None


def answer(domain_by_id):
    return {"ok": True, "reason": None,
            "structured": {"items": [{"id": k, "domain": v} for k, v in domain_by_id.items()]}}


class FakeRunner(object):
    def __init__(self, fn):
        self.fn = fn
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.fn(request)

    def lines(self, index=-1):
        found = []
        for line in self.requests[index]["prompt"].splitlines():
            if line.startswith('{"id"'):
                found.append(json.loads(line))
        return found


def all_to(domain):
    def fn(request):
        ids = [json.loads(line)["id"] for line in request["prompt"].splitlines()
               if line.startswith('{"id"')]
        return answer(dict((i, domain) for i in ids))
    return fn


class ClassifyCase(_helpers.TempHomeCase):
    def setUp(self):
        _helpers.TempHomeCase.setUp(self)
        patcher = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                               "GIT_CONFIG_NOSYSTEM": "1",
                                               "GIT_TERMINAL_PROMPT": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)
        wiki.init_wiki(self.root, environ=self.env)
        self.domains = {"owners": {}, "work_terms": [TERM], "overrides": {},
                        "redact_allow": [], "obsidian_plugins_allow": []}
        with open(os.path.join(self.root, "domains.json"), "w", encoding="utf-8") as handle:
            json.dump(self.domains, handle)
        self.template = absorb.read_template(classify.TEMPLATE)
        self.warnings = []

    def resolver(self):
        return prepare.Resolver(self.domains, remote_fn=lambda cwd: [], home=self.home)

    def run_classify(self, pending, runner, classes=None, since="2026-10-01", factory=None):
        return classify.classify(self.root, pending, classes or {}, self.domains,
                                 factory or (lambda: runner), self.template, self.warnings,
                                 since_date=since)

    def items(self, records, classifier=None, classes=None):
        found = prepare.build_prompt_items(records, self.resolver(), None, classes, classifier)
        return dict((item["id"], item) for item in found)

    def stored(self):
        with open(classify.classes_path(self.root), encoding="utf-8") as handle:
            return json.load(handle)


class FolderAndTermsTest(ClassifyCase):
    def test_work_term_goes_to_work_without_llm(self):  # case 1
        calls = []

        def classifier(pending):
            calls.append(pending)
            return {}
        records = [rec(1, "%s 배포 일정 확인해줘" % TERM, cwd=self.home)]
        found = self.items(records, classifier)
        self.assertEqual(list(found), ["prompts:work/" + DAY])
        self.assertEqual(calls, [])

    def test_work_term_in_cwd_goes_to_work_without_llm(self):  # case 1
        os.makedirs(os.path.join(self.home, TERM + "-api"))
        cwd = os.path.join(self.home, TERM + "-api")
        calls = []
        found = self.items([rec(1, "점심 메뉴 추천해줘", cwd=cwd)],
                           lambda pending: calls.append(pending) or {})
        self.assertEqual(list(found), ["prompts:work/" + DAY])
        self.assertEqual(calls, [])

    def test_stored_class_routes_to_domain_digest(self):  # case 2
        records = [rec(1, "주말에 장보기 목록 정리"), rec(2, "분기 보고서 초안 작성해줘"),
                   rec(3, "그냥 아무 말이나 해봄"), rec(4, "아직 안 물어본 프롬프트")]
        classes = {classify.prompt_key(records[0]): {"c": "personal", "d": DAY},
                   classify.prompt_key(records[1]): {"c": "work", "d": DAY},
                   classify.prompt_key(records[2]): {"c": "unknown", "d": DAY}}
        found = self.items(records, None, classes)
        self.assertEqual(sorted(found), ["prompts:personal/" + DAY, "prompts:unresolved/" + DAY,
                                         "prompts:work/" + DAY])
        self.assertEqual(found["prompts:unresolved/" + DAY]["prompt_count"], 2)
        self.assertEqual(found["prompts:personal/" + DAY]["prompt_count"], 1)

    def test_unknown_is_not_asked_again(self):  # case 2
        record = rec(1, "그냥 아무 말이나 해봄")
        seen = []
        self.items([record], lambda pending: seen.append(pending) or {},
                   {classify.prompt_key(record): {"c": "unknown", "d": DAY}})
        self.assertEqual(seen, [])

    def test_folder_domain_never_reaches_classifier(self):  # case 3
        seen = []
        records = [rec(1, "폴더로 정해지는 프롬프트", cwd=self.home + "/repo")]
        resolver = self.resolver()
        resolver.cwd_domain = lambda cwd: "personal"
        found = prepare.build_prompt_items(records, resolver, None, {},
                                           lambda pending: seen.append(pending) or {})
        self.assertEqual([i["id"] for i in found], ["prompts:personal/" + DAY])
        self.assertEqual(seen, [])

    def test_epic_domain_never_reaches_classifier(self):  # case 3
        class Epics(object):
            def domain(self, epic):
                return "work", "/somewhere/proj"
        seen = []
        found = prepare.build_prompt_items([rec(1, "에픽에서 친 프롬프트", epic="e1")],
                                           self.resolver(), Epics(), {},
                                           lambda pending: seen.append(pending) or {})
        self.assertEqual([i["id"] for i in found], ["prompts:work/" + DAY])
        self.assertEqual(seen, [])

    def test_only_folderless_prompts_are_pending(self):  # case 3
        seen = []
        resolver = self.resolver()
        resolver.cwd_domain = lambda cwd: "personal" if cwd == "/folder" else None
        records = [rec(1, "폴더 있는 프롬프트", cwd="/folder"), rec(2, "폴더 없는 프롬프트")]
        prepare.build_prompt_items(records, resolver, None, {},
                                   lambda pending: seen.append(pending) or {})
        self.assertEqual([r["text"] for r in seen[0]], ["폴더 없는 프롬프트"])

    def test_personal_class_with_work_term_in_text_is_still_work(self):  # case 1
        found = self.items([rec(1, "%s 관련 개인 메모" % TERM)],
                           lambda pending: {})
        self.assertEqual(list(found), ["prompts:work/" + DAY])


class ClassifyCallTest(ClassifyCase):
    def test_short_prompts_are_unknown_without_llm(self):  # case 4
        called = []
        pending = [rec(1, "응"), rec(2, "ㄱㄱ"), rec(3, " 고 쳐 줘 ")]
        classes = self.run_classify(pending, None,
                                    factory=lambda: called.append(1) or FakeRunner(all_to("work")))
        self.assertEqual(called, [])
        for record in pending:
            self.assertEqual(classes[classify.prompt_key(record)]["c"], "unknown")
            self.assertIsNone(class_of(classes, record))
        self.assertEqual(sorted(v["c"] for v in self.stored()["classes"].values()),
                         ["unknown"] * 3)

    def test_six_chars_is_asked(self):  # case 4
        runner = FakeRunner(all_to("personal"))
        record = rec(1, "여섯글자요!")  # 6 chars
        self.assertEqual(len(record["text"]), 6)
        classes = self.run_classify([record], runner)
        self.assertEqual(len(runner.requests), 1)
        self.assertEqual(class_of(classes, record), "personal")

    def test_runner_prompt_is_redacted_and_tools_off(self):  # case 5
        secret = j("ghp", "_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
        self.assertTrue(redact.scan(secret))
        runner = FakeRunner(all_to("personal"))
        self.run_classify([rec(1, "토큰 %s 로 로그인해줘" % secret)], runner)
        request = runner.requests[0]
        self.assertIs(request["tools_off"], True)
        self.assertNotIn(secret, request["prompt"])
        self.assertNotIn(secret[4:], request["prompt"])
        self.assertIn("[REDACTED", request["prompt"])
        self.assertEqual(request["cwd"], request["staging_dir"])
        self.assertTrue(os.path.isdir(request["cwd"]))

    def test_over_max_chars_is_unknown_without_asking(self):  # case 8
        long_text = "가나다라마바사 " * 100
        self.assertGreater(len(long_text), classify.MAX_CHARS)
        called = []
        record = rec(1, long_text)
        classes = self.run_classify([record], None,
                                    factory=lambda: called.append(1) or FakeRunner(all_to("work")))
        self.assertEqual(called, [])
        self.assertEqual(classes[classify.prompt_key(record)]["c"], "unknown")

    def test_length_is_measured_after_redaction(self):  # case 8
        secret = j("ghp", "_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
        text = (" 토큰 " + secret) * 20
        self.assertGreater(len(text), classify.MAX_CHARS)
        self.assertLessEqual(len(redact.redact(text, ()).text), classify.MAX_CHARS)
        runner = FakeRunner(all_to("personal"))
        self.run_classify([rec(1, text)], runner)
        self.assertEqual(len(runner.requests), 1)
        self.assertNotIn(secret, runner.requests[0]["prompt"])

    def test_invalid_id_and_domain_are_not_stored_and_asked_again(self):  # case 6
        records = [rec(1, "첫번째 프롬프트 내용"), rec(2, "두번째 프롬프트 내용"),
                   rec(3, "세번째 프롬프트 내용")]

        def fn(request):
            ids = [line["id"] for line in FakeRunner.lines(self.runner)]
            return answer({"zz": "work", ids[0]: "bogus", ids[1]: "personal"})
        self.runner = FakeRunner(fn)
        classes = self.run_classify(records, self.runner)
        stored = [class_of(classes, r) for r in records]
        self.assertEqual(sorted(s for s in stored if s), ["personal"])
        self.assertEqual(len(self.stored()["classes"]), 1)
        # Next run: only the unanswered two are pending.
        pending = [r for r in records if classify.prompt_key(r) not in classes]
        self.assertEqual(len(pending), 2)
        self.assertEqual(len(self.stored()["classes"]), 1)

    def test_non_list_items_and_non_dict_item_are_ignored(self):  # case 6
        for structured in ({"items": "nope"}, {"items": [None, 3, "x"]}, {}):
            runner = FakeRunner(lambda request, s=structured: {"ok": True, "structured": s})
            classes = self.run_classify([rec(1, "프롬프트 하나 입니다")], runner)
            self.assertEqual(classes, {})

    def test_runner_not_ok_keeps_state_and_warns(self):  # case 7
        old = rec(1, "예전에 판정된 프롬프트")
        classes = self.run_classify([old], FakeRunner(all_to("work")))
        before = self.stored()
        runner = FakeRunner(lambda request: {"ok": False, "reason": "llm_timeout"})
        after = self.run_classify([rec(2, "새로 들어온 프롬프트")], runner, classes)
        self.assertIn("prompt_classify_failed:llm_timeout", self.warnings)
        self.assertEqual(class_of(after, old), "work")
        self.assertEqual(self.stored(), before)

    def test_runner_not_ok_without_reason(self):  # case 7
        runner = FakeRunner(lambda request: {"ok": False})
        self.run_classify([rec(1, "프롬프트 하나 입니다")], runner)
        self.assertIn("prompt_classify_failed:llm_error", self.warnings)

    def test_factory_wiki_error_warns_without_raising(self):  # case 7

        def factory():
            raise common.WikiError("claude_missing", "no claude")
        previous = rec(1, "이전에 판정된 프롬프트")
        classes = {classify.prompt_key(previous): {"c": "personal", "d": DAY}}
        after = self.run_classify([rec(2, "새로 들어온 프롬프트")], None, classes,
                                  factory=factory)
        self.assertIn("prompt_classify_failed:claude_missing", self.warnings)
        self.assertEqual(class_of(after, previous), "personal")

    def test_earlier_chunk_answers_survive_later_failure(self):  # case 7
        records = [rec(n, "프롬프트 번호 %03d 입니다" % n) for n in range(1, 6)]
        calls = []

        def fn(request):
            calls.append(1)
            if len(calls) == 1:
                return all_to("personal")(request)
            return {"ok": False, "reason": "llm_error"}
        with mock.patch.object(classify, "CHUNK", 2):
            classes = self.run_classify(records, FakeRunner(fn))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(classes), 2)
        self.assertEqual(len(self.stored()["classes"]), 2)
        self.assertIn("prompt_classify_failed:llm_error", self.warnings)
        # Newest first: the two newest were answered.
        answered = [r for r in records if class_of(classes, r)]
        self.assertEqual([r["time"] for r in answered], ["10:04", "10:05"])

    def test_deferred_over_max_per_run_asks_newest_first(self):  # case 8
        records = [rec(n, "프롬프트 번호 %03d 입니다" % n) for n in range(1, 8)]
        runner = FakeRunner(all_to("personal"))
        with mock.patch.object(classify, "MAX_PER_RUN", 3):
            classes = self.run_classify(records, runner)
        self.assertIn("prompt_classify_deferred:4", self.warnings)
        asked_texts = [line["text"] for line in runner.lines(0)]
        self.assertEqual(sorted(asked_texts),
                         ["프롬프트 번호 %03d 입니다" % n for n in (5, 6, 7)])
        self.assertEqual(len(classes), 3)

    def test_no_deferred_warning_at_limit(self):  # case 8
        records = [rec(n, "프롬프트 번호 %03d 입니다" % n) for n in range(1, 4)]
        with mock.patch.object(classify, "MAX_PER_RUN", 3):
            self.run_classify(records, FakeRunner(all_to("work")))
        self.assertFalse([w for w in self.warnings if "deferred" in w])


class StoreTest(ClassifyCase):
    def test_file_has_no_prompt_text_and_is_0600(self):  # case 9
        text = "고유한프롬프트문구 절대 저장되면 안됨"
        record = rec(1, text)
        self.run_classify([record], FakeRunner(all_to("personal")))
        path = classify.classes_path(self.root)
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn("고유한프롬프트문구", raw)
        self.assertNotIn(text, raw)
        self.assertEqual(mode(path), 0o600)
        self.assertEqual(list(self.stored()["classes"]), [classify.prompt_key(record)])

    def test_mode_stays_0600_on_rewrite(self):  # case 9
        os.makedirs(common.state_dir(self.root), exist_ok=True)
        classify.save_classes(self.root, {})
        os.chmod(classify.classes_path(self.root), 0o644)
        classify.save_classes(self.root, {"k": {"c": "work", "d": DAY}})
        self.assertEqual(mode(classify.classes_path(self.root)), 0o600)

    def test_entries_older_than_since_date_dropped_on_save(self):  # case 9
        classes = {"old": {"c": "work", "d": "2026-09-01"}, "new": {"c": "work", "d": DAY},
                   "edge": {"c": "personal", "d": "2026-10-01"}}
        classify.save_classes(self.root, classes, "2026-10-01")
        self.assertEqual(sorted(self.stored()["classes"]), ["edge", "new"])

    def test_old_entries_dropped_through_classify_run(self):  # case 9
        old = rec(1, "오래된 프롬프트 하나", date="2026-08-01")
        classes = {classify.prompt_key(old): {"c": "work", "d": "2026-08-01"}}
        self.run_classify([rec(2, "새 프롬프트 하나 있음")], FakeRunner(all_to("work")),
                          classes, since="2026-10-01")
        self.assertNotIn(classify.prompt_key(old), self.stored()["classes"])

    def test_corrupt_file_reads_as_empty(self):  # case 9
        os.makedirs(common.state_dir(self.root), exist_ok=True)
        path = classify.classes_path(self.root)
        for content in ("{not json", "[]", '{"classes": []}', '{"classes": "x"}', ""):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
            self.assertEqual(classify.load_classes(self.root), {}, content)

    def test_missing_file_and_bad_entries(self):  # case 9
        self.assertEqual(classify.load_classes(self.root), {})
        os.makedirs(common.state_dir(self.root), exist_ok=True)
        with open(classify.classes_path(self.root), "w", encoding="utf-8") as handle:
            json.dump({"classes": {"a": {"c": "work", "d": DAY}, "b": {"c": "evil", "d": DAY},
                                   "c": "work", "d": 3}}, handle)
        self.assertEqual(sorted(classify.load_classes(self.root)), ["a"])


class ArgvAndRunnerTest(unittest.TestCase):
    def test_build_classify_argv_flags(self):  # case 10
        argv = absorb.build_classify_argv("/bin/claude", "m", 0.5, "{}")
        for flag in ("--restricted", "--strict-mcp-config"):
            self.assertIn(flag, argv)
        for flag, value in (("--tools", ""), ("--setting-sources", "")):
            self.assertEqual(argv[argv.index(flag) + 1], value, flag)
        self.assertNotIn("--add-dir", argv)
        self.assertNotIn("--permission-mode", argv)
        self.assertNotIn("acceptEdits", argv)

    def test_runner_uses_classify_argv_only_when_tools_off(self):  # case 5
        runner = absorb.ClaudeRunner("/bin/claude", "m", 0.5, {"PATH": "/usr/bin"})
        seen = []

        def fake_run(argv, **kwargs):
            seen.append((argv, kwargs))
            out = json.dumps({"subtype": "success", "structured_output": {"items": []}})
            return mock.Mock(stdout=out.encode(), stderr=b"", returncode=0)
        base = {"prompt": "p", "schema": {"type": "object"}, "cwd": "/tmp", "staging_dir": "/s"}
        with mock.patch.object(absorb.subprocess, "run", side_effect=fake_run):
            on = runner(dict(base, tools_off=True))
            off = runner(dict(base))
        self.assertTrue(on["ok"])
        self.assertTrue(off["ok"])
        self.assertNotIn("--add-dir", seen[0][0])
        self.assertIn("--tools", seen[0][0])
        self.assertIn("--add-dir", seen[1][0])
        self.assertIn("acceptEdits", seen[1][0])
        self.assertEqual(seen[0][0][seen[0][0].index("--tools") + 1], "")
        self.assertNotEqual(seen[1][0][seen[1][0].index("--tools") + 1], "")


class WiringTest(ClassifyCase):
    def history(self, rows):
        path = os.path.join(self.tmp, "history.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for text in rows:
                handle.write(json.dumps({"display": text, "timestamp": int(noon(DAY) * 1000),
                                         "project": self.home}, ensure_ascii=False) + "\n")
        return prepare.SourcePaths(os.path.join(self.tmp, "none"), path, None, None, None, None)

    def test_absorb_with_runner_skips_classifier(self):  # case 11
        with mock.patch.object(absorb, "prompt_classifier") as factory:
            paths = self.history(["홈에서 친 프롬프트 입니다"])
            runner = FakeRunner(lambda request: {"ok": True, "structured": {
                "pages": [], "merges": [], "mentions": [], "withdrawn_src": [], "notes": ""}})
            try:
                absorb.absorb(self.root, environ=self.env, paths=paths, now=NOW, runner=runner,
                              fs_root=self.tmp, rules_path=os.path.join(self.tmp, "r", "r.md"))
            except common.WikiError:
                pass
        factory.assert_not_called()
        self.assertFalse(os.path.exists(classify.classes_path(self.root)))

    def test_pending_counts_never_calls_llm(self):  # case 11
        paths = self.history(["홈에서 친 프롬프트 입니다"])
        with mock.patch.object(absorb.ClaudeRunner, "from_settings",
                               side_effect=AssertionError("llm")):
            counts = prepare.pending_counts(self.root, self.env, paths, NOW, fs_root=self.tmp)
        self.assertIsNotNone(counts)

    def test_pending_counts_uses_stored_class(self):  # case 2, 11
        text = "홈에서 친 프롬프트 입니다"
        paths = self.history([text])
        record = rec(0, text)
        record["time"] = datetime.datetime.fromtimestamp(noon(DAY)).strftime("%H:%M")
        classify.save_classes(self.root, {classify.prompt_key(record): {"c": "personal", "d": DAY}})
        warnings = []
        items, _ = prepare.gather(self.root, paths, self.resolver(), self.domains,
                                  common.load_settings(self.root), NOW, warnings)
        self.assertEqual([i["id"] for i in items if i["kind"] == prepare.KIND_PROMPTS],
                         ["prompts:personal/" + DAY])

    def test_gather_calls_classifier_hook_with_unresolved_only(self):  # case 3
        paths = self.history(["홈에서 친 프롬프트 입니다", "%s 배포 확인" % TERM])
        calls = []

        def hook(root, pending, classes, domains, warnings, since_date):
            calls.append([r["text"] for r in pending])
            return classes
        warnings = []
        items, _ = prepare.gather(self.root, paths, self.resolver(), self.domains,
                                  common.load_settings(self.root), NOW, warnings, hook)
        self.assertEqual(calls, [["홈에서 친 프롬프트 입니다"]])
        ids = sorted(i["id"] for i in items if i["kind"] == prepare.KIND_PROMPTS)
        self.assertEqual(ids, ["prompts:unresolved/" + DAY, "prompts:work/" + DAY])

    def test_prompt_classifier_asks_through_runner_and_reuses(self):  # case 2, 11
        paths = self.history(["홈에서 친 프롬프트 입니다"])
        runner = FakeRunner(all_to("personal"))
        run = absorb.prompt_classifier(self.env)
        with mock.patch.object(absorb.ClaudeRunner, "from_settings", return_value=runner):
            prepare.prepare(self.root, self.env, paths, NOW, fs_root=self.tmp,
                            prompt_classifier=run)
            prepare.prepare(self.root, self.env, paths, NOW, fs_root=self.tmp,
                            prompt_classifier=run)
        self.assertEqual(len(runner.requests), 1)
        self.assertIs(runner.requests[0]["tools_off"], True)

    def test_prompt_classifier_factory_not_called_when_nothing_pending(self):  # case 11
        run = absorb.prompt_classifier(self.env)
        with mock.patch.object(absorb.ClaudeRunner, "from_settings",
                               side_effect=AssertionError("probe")):
            classes = run(self.root, [], {}, self.domains, self.warnings, "2026-10-01")
        self.assertEqual(classes, {})


class TemplateTest(ClassifyCase):
    def test_no_placeholder_left_after_render(self):  # case 12
        names = {"work": ["회사프로젝트A"], "personal": ["개인프로젝트B"]}
        text = classify.render_prompt(self.template, names, ['{"id": "p0", "text": "안녕하세요"}'])
        self.assertIsNone(re.search(r"\{\{[A-Z_]+\}\}", text))
        self.assertIn("회사프로젝트A", text)
        self.assertIn("개인프로젝트B", text)
        self.assertIn('{"id": "p0"', text)

    def test_empty_names_render_placeholder_text(self):  # case 12
        text = classify.render_prompt(self.template, {}, [])
        self.assertIsNone(re.search(r"\{\{[A-Z_]+\}\}", text))
        self.assertIn("work: []", text)

    def test_template_has_the_three_placeholders(self):  # case 12
        for name in ("{{WORK_PROJECTS}}", "{{PERSONAL_PROJECTS}}", "{{PROMPTS}}"):
            self.assertEqual(self.template.count(name), 1, name)

    def test_prompt_text_with_placeholder_is_not_expanded_again(self):  # case 12
        line = json.dumps({"id": "p0", "text": "{{WORK_PROJECTS}}"})
        text = classify.render_prompt(self.template, {"work": ["Zed"]}, [line])
        self.assertIn('"text": "{{WORK_PROJECTS}}"', text)

class SessionCase(ClassifyCase):
    """prepare.resolve_prompts with session rules; entries keyed by text."""

    def setUp(self):
        ClassifyCase.setUp(self)
        self.work_cwds = set(["/w"])
        self.pending_calls = []
        self.stats = {}

    def folder_resolver(self):
        resolver = self.resolver()
        resolver.cwd_domain = lambda cwd: "work" if cwd in self.work_cwds else None
        return resolver

    def resolve(self, records, classes=None, runner=None, resolver=None):
        state = {"classes": dict(classes or {})}

        def classifier(pending):
            self.pending_calls.append([r["text"] for r in pending])
            state["classes"] = classify.classify(
                self.root, pending, state["classes"], self.domains, lambda: runner,
                self.template, self.warnings, "2026-10-01", self.stats)
            return state["classes"]
        entries = prepare.resolve_prompts(records, resolver or self.folder_resolver(), None,
                                          dict(classes or {}),
                                          classifier if runner is not None else None)
        self.last_classes = state["classes"]
        return dict((e["record"]["text"], e) for e in entries)

    def verdict(self, found, text):
        return found[text]["domain"], found[text]["via"]


def answering(by_text):
    """Runner answering by prompt text; texts not listed get no answer."""
    def fn(request):
        items = []
        for line in request["prompt"].splitlines():
            if line.startswith('{"id"'):
                row = json.loads(line)
                if row["text"] in by_text:
                    items.append({"id": row["id"], "domain": by_text[row["text"]]})
        return {"ok": True, "structured": {"items": items}, "cost": 0.5}
    return FakeRunner(fn)


class SessionRuleTest(SessionCase):
    def test_term_in_session_makes_rest_work_without_llm(self):  # case 1
        records = [rec(1, "%s 배포 확인해줘" % TERM, session="s"),
                   rec(2, "다음 단계 진행해줘요", session="s"),
                   rec(3, "응", session="s")]
        runner = answering({})
        found = self.resolve(records, runner=runner)
        self.assertEqual(self.verdict(found, "다음 단계 진행해줘요"), ("work", "session"))
        self.assertEqual(runner.requests, [])
        self.assertEqual(self.pending_calls, [])
        self.assertEqual(self.verdict(found, "응")[0], None)  # short stays unresolved
        items = prepare.build_prompt_items(records, self.folder_resolver(), None)
        by_id = dict((i["id"], i) for i in items)
        self.assertEqual(by_id["prompts:work/" + DAY]["prompt_count"], 2)
        self.assertEqual(by_id["prompts:unresolved/" + DAY]["prompt_count"], 1)

    def test_other_session_is_still_asked(self):  # case 1
        records = [rec(1, "%s 배포 확인해줘" % TERM, session="s"),
                   rec(2, "다음 단계 진행해줘요", session="s"),
                   rec(3, "주말 장보기 목록 정리", session="t")]
        runner = answering({"주말 장보기 목록 정리": "personal"})
        found = self.resolve(records, runner=runner)
        self.assertEqual(self.pending_calls, [["주말 장보기 목록 정리"]])
        self.assertEqual(self.verdict(found, "주말 장보기 목록 정리"), ("personal", "llm"))

    def test_folder_work_in_session_makes_rest_work(self):  # case 2
        records = [rec(1, "폴더가 정해주는 프롬프트", cwd="/w", session="s"),
                   rec(2, "다음 단계 진행해줘요", session="s"),
                   rec(3, "응", session="s")]
        runner = answering({})
        found = self.resolve(records, runner=runner)
        self.assertEqual(self.verdict(found, "폴더가 정해주는 프롬프트"), ("work", "folder"))
        self.assertEqual(self.verdict(found, "다음 단계 진행해줘요"), ("work", "session"))
        self.assertEqual(self.verdict(found, "응")[0], None)
        self.assertEqual(runner.requests, [])

    def test_llm_work_pulls_whole_session_and_persists(self):  # case 3
        records = [rec(1, "회사 일 같은 프롬프트", session="s"),
                   rec(2, "개인 일 같은 프롬프트", session="s"),
                   rec(3, "애매한 프롬프트 하나", session="s")]
        runner = answering({"회사 일 같은 프롬프트": "work", "개인 일 같은 프롬프트": "personal",
                            "애매한 프롬프트 하나": "unknown"})
        found = self.resolve(records, runner=runner)
        for text in ("회사 일 같은 프롬프트", "개인 일 같은 프롬프트", "애매한 프롬프트 하나"):
            self.assertEqual(found[text]["domain"], "work", text)
        self.assertEqual(self.verdict(found, "개인 일 같은 프롬프트"), ("work", "session"))
        # Next run: stored answers alone give the same result, with no LLM.
        again = self.resolve(records, classes=classify.load_classes(self.root))
        for text in found:
            self.assertEqual(again[text]["domain"], "work", text)

    def test_personal_needs_every_prompt_of_session_answered(self):  # case 4
        records = [rec(1, "첫 프롬프트 내용 입니다", session="s"),
                   rec(2, "둘째 프롬프트 내용 입니다", session="s")]
        runner = answering({"첫 프롬프트 내용 입니다": "personal",
                            "둘째 프롬프트 내용 입니다": "personal"})
        with mock.patch.object(classify, "MAX_PER_RUN", 1):
            found = self.resolve(records, runner=runner)
        # Newest asked first; the older one is deferred, so nothing is personal yet.
        self.assertEqual(self.verdict(found, "둘째 프롬프트 내용 입니다")[0], None)
        self.assertEqual(self.verdict(found, "첫 프롬프트 내용 입니다")[0], None)
        self.assertIn("prompt_classify_deferred:1", self.warnings)
        found = self.resolve(records, classes=classify.load_classes(self.root), runner=runner)
        self.assertEqual(self.verdict(found, "첫 프롬프트 내용 입니다"), ("personal", "llm"))
        self.assertEqual(self.verdict(found, "둘째 프롬프트 내용 입니다"), ("personal", "llm"))

    def test_failed_call_leaves_session_unresolved(self):  # case 4
        records = [rec(1, "첫 프롬프트 내용 입니다", session="s"),
                   rec(2, "둘째 프롬프트 내용 입니다", session="s")]
        calls = []

        def fn(request):
            calls.append(1)
            return {"ok": False, "reason": "llm_error"}
        found = self.resolve(records, runner=FakeRunner(fn))
        self.assertEqual([found[t]["domain"] for t in found], [None, None])

    def test_session_none_prompts_are_not_tied_together(self):  # case 4
        records = [rec(1, "답을 받은 프롬프트요", session=None),
                   rec(2, "답 못 받은 프롬프트요", session=None)]
        found = self.resolve(records, runner=answering({"답을 받은 프롬프트요": "personal"}))
        self.assertEqual(self.verdict(found, "답을 받은 프롬프트요"), ("personal", "llm"))
        self.assertEqual(found["답 못 받은 프롬프트요"]["domain"], None)

    def test_session_none_work_does_not_spread(self):  # case 4
        records = [rec(1, "%s 배포 확인해줘" % TERM, session=None),
                   rec(2, "다른 프롬프트 내용요", session=None)]
        found = self.resolve(records, runner=answering({"다른 프롬프트 내용요": "personal"}))
        self.assertEqual(self.verdict(found, "다른 프롬프트 내용요"), ("personal", "llm"))


class HumanAnswerTest(SessionCase):
    def work_session(self):
        return [rec(1, "%s 배포 확인해줘" % TERM, session="s"),
                rec(2, "사람이 고칠 프롬프트요", session="s")]

    def human(self, record, domain):
        classify.set_human(self.root, classify.prompt_key(record), domain, record["date"])
        return classify.load_classes(self.root)

    def test_human_personal_beats_work_session(self):  # case 5
        records = self.work_session()
        classes = self.human(records[1], "personal")
        self.assertEqual(classes[classify.prompt_key(records[1])]["by"], "human")
        found = self.resolve(records, classes=classes)
        self.assertEqual(self.verdict(found, "사람이 고칠 프롬프트요"), ("personal", "human"))

    def test_human_unknown_is_left_out(self):  # case 5
        records = self.work_session()
        found = self.resolve(records, classes=self.human(records[1], "unknown"))
        self.assertEqual(self.verdict(found, "사람이 고칠 프롬프트요"), (None, "human"))

    def test_human_work_is_work(self):  # case 5
        records = [rec(1, "사람이 고칠 프롬프트요", session="s")]
        found = self.resolve(records, classes=self.human(records[0], "work"))
        self.assertEqual(self.verdict(found, "사람이 고칠 프롬프트요"), ("work", "human"))

    def test_human_work_pulls_session(self):  # case 5
        records = [rec(1, "사람이 고칠 프롬프트요", session="s"),
                   rec(2, "같은 세션의 다른 프롬프트", session="s")]
        found = self.resolve(records, classes=self.human(records[0], "work"))
        self.assertEqual(self.verdict(found, "같은 세션의 다른 프롬프트"), ("work", "session"))

    def test_human_personal_does_not_pull_session(self):  # case 5
        records = [rec(1, "사람이 고칠 프롬프트요", session="s"),
                   rec(2, "같은 세션의 다른 프롬프트", session="s")]
        found = self.resolve(records, classes=self.human(records[0], "personal"))
        self.assertEqual(self.verdict(found, "사람이 고칠 프롬프트요"), ("personal", "human"))
        self.assertIsNone(found["같은 세션의 다른 프롬프트"]["domain"])

    def test_human_unknown_does_not_count_as_waiting_or_work(self):  # case 5
        records = [rec(1, "사람이 고칠 프롬프트요", session="s"),
                   rec(2, "같은 세션의 다른 프롬프트", session="s")]
        classes = self.human(records[0], "unknown")
        found = self.resolve(records, classes=classes,
                             runner=answering({"같은 세션의 다른 프롬프트": "personal"}))
        self.assertEqual(self.verdict(found, "같은 세션의 다른 프롬프트"), ("personal", "llm"))

    def test_work_term_prompt_gets_no_human_answer(self):  # case 5
        record = rec(1, "%s 배포 확인해줘" % TERM, session="s")
        found = self.resolve([record], classes=self.human(record, "personal"))
        self.assertEqual(self.verdict(found, record["text"]), ("work", "folder"))

    def test_set_human_rejects_bad_class(self):  # case 5
        with self.assertRaises(common.WikiError):
            classify.set_human(self.root, "k", "other", DAY)


class DedupTest(SessionCase):
    def pair(self, home_label, work_label):
        home = rec(5, "같은 프롬프트 두 곳", cwd=self.home, session="s1")
        home["label"] = home_label
        work = rec(5, "같은 프롬프트 두 곳", cwd="/w", session="s2")
        work["label"] = work_label
        return home, work

    def test_work_copy_wins_in_either_order(self):  # case 6
        for labels in (("a", "b"), ("b", "a")):
            home, work = self.pair(*labels)
            other = rec(6, "s2의 다른 프롬프트요", session="s2")
            other_home = rec(7, "s1의 다른 프롬프트요", session="s1")
            found = self.resolve([home, work, other, other_home])
            self.assertEqual(self.verdict(found, "같은 프롬프트 두 곳")[0], "work", labels)
            self.assertEqual(found["같은 프롬프트 두 곳"]["sessions"], set(["s1", "s2"]))
            self.assertEqual(found["s2의 다른 프롬프트요"]["domain"], "work")
            self.assertEqual(found["s1의 다른 프롬프트요"]["domain"], "work")
            self.assertEqual(len(found), 3)

    def test_only_one_entry_in_digest(self):  # case 6
        home, work = self.pair("a", "b")
        items = prepare.build_prompt_items([home, work], self.folder_resolver(), None)
        self.assertEqual([i["id"] for i in items], ["prompts:work/" + DAY])
        self.assertEqual(items[0]["prompt_count"], 1)


class AnswerValidationTest(ClassifyCase):
    def test_duplicate_ids_are_not_stored(self):  # case 7
        records = [rec(1, "충돌하는 답 프롬프트"), rec(2, "중복된 답 프롬프트"),
                   rec(3, "정상 답 프롬프트요")]

        def fn(request):
            ids = dict((json.loads(l)["text"], json.loads(l)["id"])
                       for l in request["prompt"].splitlines() if l.startswith('{"id"'))
            a, b, c = ids["충돌하는 답 프롬프트"], ids["중복된 답 프롬프트"], ids["정상 답 프롬프트요"]
            return answer_rows([(a, "work"), (a, "personal"), (b, "personal"), (b, "personal"),
                                (c, "personal")])
        classes = self.run_classify(records, FakeRunner(fn))
        self.assertEqual([class_of(classes, r) for r in records], [None, None, "personal"])
        self.assertEqual(len(self.stored()["classes"]), 1)


def answer_rows(rows):
    return {"ok": True, "structured": {"items": [{"id": i, "domain": d} for i, d in rows]}}


class LongPromptSessionTest(SessionCase):
    def test_long_prompt_in_work_session_is_work(self):  # case 8
        long_text = "가나다라마바사 " * 100
        records = [rec(1, "%s 배포 확인해줘" % TERM, session="s"),
                   rec(2, long_text.strip(), session="s")]
        runner = answering({})
        found = self.resolve(records, runner=runner)
        self.assertEqual(self.verdict(found, long_text.strip()), ("work", "session"))
        self.assertEqual(runner.requests, [])

    def test_long_prompt_alone_stays_unresolved(self):  # case 8
        long_text = ("가나다라마바사 " * 100).strip()
        found = self.resolve([rec(1, long_text, session="s")], runner=answering({}))
        self.assertEqual(self.verdict(found, long_text)[0], None)
        self.assertEqual(list(self.last_classes.values())[0]["c"], "unknown")

    def test_secret_shrunk_prompt_in_work_session_is_work(self):  # case 8
        secret = j("ghp", "_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
        text = ((" 토큰 " + secret) * 20).strip()
        records = [rec(1, "%s 배포 확인해줘" % TERM, session="s"), rec(2, text, session="s")]
        found = self.resolve(records, runner=answering({}))
        self.assertEqual(self.verdict(found, text), ("work", "session"))


class HomeLabelAndPlanTest(ClassifyCase):
    def test_home_label_is_tilde_and_personal_digest_is_active(self):  # case 9
        home = os.path.join(self.tmp, "AcmeCorp")  # account name equals a work term
        os.makedirs(home)
        self.domains["work_terms"] = [TERM]
        resolver = prepare.Resolver(self.domains, remote_fn=lambda cwd: [], home=home)
        record = rec(1, "주말에 장보기 목록 정리", cwd=home, session="s")
        record["label"] = os.path.basename(home)
        classes = {classify.prompt_key(record): {"c": "personal", "d": DAY}}
        entries = prepare.resolve_prompts([record], resolver, None, classes)
        self.assertEqual(entries[0]["record"]["label"], "~")
        items = prepare.build_prompt_items([record], resolver, None, classes)
        self.assertEqual([i["id"] for i in items], ["prompts:personal/" + DAY])
        self.assertNotIn(TERM, items[0]["text"])
        paths = prepare.SourcePaths(os.path.join(self.tmp, "p"), None, None, None, None, None)
        plan = prepare.plan_sources(self.root, items, set([prepare.KIND_PROMPTS]),
                                    prepare.load_sources(self.root), paths, resolver,
                                    self.domains)
        ops = [op for op in plan.ops if op["id"] == "prompts:personal/" + DAY]
        self.assertEqual([op["op"] for op in ops], ["new"])
        self.assertEqual(plan.counts.get(prepare.STATUS_QUARANTINED, 0), 0)

    def test_other_cwd_keeps_folder_label(self):  # case 9
        record = rec(1, "주말에 장보기 목록 정리", cwd=os.path.join(self.home, "proj"))
        record["label"] = "proj"
        entries = prepare.resolve_prompts([record], self.resolver(), None, {})
        self.assertEqual(entries[0]["record"]["label"], "proj")


class WithdrawalTest(ClassifyCase):
    """A digest is withdrawn only when a prompt it held is seen right now in
    another bucket; a prompt that is just gone proves nothing."""

    def setUp(self):
        ClassifyCase.setUp(self)
        self.paths = prepare.SourcePaths(os.path.join(self.tmp, "p"), None, None, None, None,
                                         None)

    def personal_resolver(self):
        resolver = self.resolver()
        resolver.cwd_domain = lambda cwd: "personal" if cwd == "/me" else None
        return resolver

    def plan(self, records, entries):
        resolver = self.personal_resolver()
        items = prepare.build_prompt_items(records, resolver, None, {})
        return prepare.plan_sources(self.root, items, set(), {"sources": entries}, self.paths,
                                    resolver, self.domains)

    @staticmethod
    def entry(keys, domain="personal", status="active"):
        found = {"kind": "prompts", "status": status, "domain": domain, "date": DAY}
        if keys is not None:
            found["keys"] = keys
        return found

    def deleted(self, plan):
        return [(op["id"], op["domain"]) for op in plan.ops if op["op"] == "deleted"]

    def test_digest_gone_and_prompt_now_in_work_is_deleted(self):  # case 1
        moved = rec(1, "%s 배포 확인해줘" % TERM, cwd="/me")  # work_terms: work, not personal
        key = classify.prompt_key(moved)
        plan = self.plan([moved], {"prompts:personal/" + DAY: self.entry({key: moved["time"]})})
        self.assertEqual(self.deleted(plan), [("prompts:personal/" + DAY, "personal")])

    def test_digest_gone_and_key_nowhere_is_kept(self):  # case 2
        gone = rec(1, "회전으로 사라진 프롬프트", cwd="/me")
        plan = self.plan([], {"prompts:personal/" + DAY:
                              self.entry({classify.prompt_key(gone): gone["time"]})})
        self.assertEqual(plan.ops, [])
        # Other prompts exist, but not this one: still no proof.
        other = rec(2, "%s 배포 확인해줘" % TERM, cwd="/me")
        plan = self.plan([other], {"prompts:personal/" + DAY:
                                   self.entry({classify.prompt_key(gone): gone["time"]})})
        self.assertEqual(self.deleted(plan), [])

    def test_empty_history_file_deletes_nothing(self):  # case 2
        history = os.path.join(self.tmp, "empty.jsonl")
        open(history, "w").close()
        paths = prepare.SourcePaths(os.path.join(self.tmp, "p"), history, None, None, None, None)
        records = prepare.read_history(history, "2026-10-01", [])
        self.assertEqual(records, [])
        items = prepare.build_prompt_items(records, self.personal_resolver(), None, {})
        plan = prepare.plan_sources(self.root, items, set([prepare.KIND_PROMPTS]),
                                    {"sources": {"prompts:personal/" + DAY:
                                                 self.entry({"k" * 24: "10:01"})}},
                                    paths, self.personal_resolver(), self.domains)
        self.assertEqual(plan.ops, [])

    def test_moved_to_quarantine_or_unresolved_counts_as_moved(self):  # case 4
        quarantined = rec(1, "%s 개인 레포에서" % TERM, cwd="/me")
        resolver = self.personal_resolver()
        resolver.terms = prepare.TermMatcher([TERM])
        # Work term text with a personal folder: work wins, so use a stored
        # personal class on a folderless prompt whose text carries the term
        # only after the folder decided personal.
        entries = {"prompts:personal/" + DAY:
                   self.entry({classify.prompt_key(quarantined): quarantined["time"]})}
        items = [prepare._item(prepare.make_id(prepare.KIND_PROMPTS, "quarantine/" + DAY),
                               prepare.KIND_PROMPTS, "x", DAY, None, None, "t",
                               forced_status=prepare.STATUS_QUARANTINED,
                               keys=[classify.prompt_key(quarantined)])]
        plan = prepare.plan_sources(self.root, items, set(), {"sources": entries}, self.paths,
                                    resolver, self.domains)
        self.assertEqual(self.deleted(plan), [("prompts:personal/" + DAY, "personal")])
        items[0]["id"] = prepare.make_id(prepare.KIND_PROMPTS, "unresolved/" + DAY)
        items[0]["forced_status"] = prepare.STATUS_UNRESOLVED
        plan = prepare.plan_sources(self.root, items, set(), {"sources": entries}, self.paths,
                                    resolver, self.domains)
        self.assertEqual(self.deleted(plan), [("prompts:personal/" + DAY, "personal")])

    def test_entry_without_keys_is_never_withdrawn(self):  # case 5
        moved = rec(1, "%s 배포 확인해줘" % TERM, cwd="/me")
        for keys in (None, {}):
            plan = self.plan([moved], {"prompts:personal/" + DAY: self.entry(keys)})
            self.assertEqual(self.deleted(plan), [], keys)

    def test_unresolved_entry_vanishing_makes_no_op(self):  # case 4
        plan = self.plan([], {"prompts:unresolved/" + DAY:
                              self.entry({"k" * 24: "10:01"}, domain=None, status="unresolved")})
        self.assertEqual(plan.ops, [])

    def test_moved_prompts(self):  # case 3
        entry = {"keys": {"a": "10:01", "b": "10:02", "c": "10:03"}}
        item = {"keys": ["a"]}
        self.assertEqual(prepare.moved_prompts(entry, item, set(["a", "b"])), ["10:02"])
        self.assertEqual(prepare.moved_prompts(entry, None, set(["b", "c"])), ["10:02", "10:03"])
        self.assertEqual(prepare.moved_prompts(entry, item, set()), [])
        self.assertEqual(prepare.moved_prompts(None, item, set(["b"])), [])
        self.assertEqual(prepare.moved_prompts({}, item, set(["b"])), [])


class MoveFlowTest(ClassifyCase):
    """prepare + commit_batch twice over a real history file."""

    def setUp(self):
        ClassifyCase.setUp(self)
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        self.git(repo, "init", "-q")
        self.git(repo, "remote", "add", "o", "git@github.com:MeUser/r.git")
        self.repo = repo
        self.domains["owners"] = {"MeUser": "personal"}
        with open(os.path.join(self.root, "domains.json"), "w", encoding="utf-8") as handle:
            json.dump(self.domains, handle)
        self.hist = os.path.join(self.tmp, "history.jsonl")
        self.paths = prepare.SourcePaths(os.path.join(self.tmp, "none"), self.hist, None, None,
                                         None, None)

    def write_history(self, rows):
        with open(self.hist, "w", encoding="utf-8") as handle:
            for index, (text, project) in enumerate(rows):
                handle.write(json.dumps({"display": text, "project": project,
                                         "timestamp": int((noon(DAY) + index * 60) * 1000),
                                         "sessionId": "s%d" % index}, ensure_ascii=False) + "\n")

    def write_rows(self, rows):
        """rows: (index, text, project); the index fixes the timestamp, so the
        same prompt keeps the same key when other rows come and go."""
        with open(self.hist, "w", encoding="utf-8") as handle:
            for index, text, project in rows:
                handle.write(json.dumps({"display": text, "project": project,
                                         "timestamp": int((noon(DAY) + index * 60) * 1000),
                                         "sessionId": "s%d" % index}, ensure_ascii=False) + "\n")

    def record(self, index, text):
        moment = datetime.datetime.fromtimestamp(noon(DAY) + index * 60)
        return {"date": DAY, "time": moment.strftime("%H:%M"), "text": text}

    def do_prepare(self):
        prepare.prepare(self.root, environ=self.env, paths=self.paths, now=NOW, fs_root=self.tmp)
        with open(common.run_json_path(self.root), encoding="utf-8") as handle:
            return json.load(handle)

    def commit_all(self, run):
        for batch in run["batches"]:
            prepare.commit_batch(self.root, batch["batch_id"])
        prepare.finalize_run(self.root)

    def sources(self, run):
        return [s for b in run["batches"] for s in b["sources"]]

    def diff_of(self, source):
        with open(os.path.join(self.root, ".state", source["diff_path"]), encoding="utf-8") as h:
            return h.read()

    def seed(self):
        self.write_history([("개인 레포 프롬프트 하나", self.repo),
                            ("홈에서 친 프롬프트 하나", self.home)])
        keys = [classify.prompt_key(self.record(i, t)) for i, t in
                enumerate(["개인 레포 프롬프트 하나", "홈에서 친 프롬프트 하나"])]
        classify.save_classes(self.root, {keys[1]: {"c": "personal", "d": DAY}})
        run = self.do_prepare()
        self.commit_all(run)
        return keys

    def test_commit_stores_keys_and_next_plan_uses_them(self):  # case 6
        keys = self.seed()
        entry = prepare.load_sources(self.root)["sources"]["prompts:personal/" + DAY]
        self.assertEqual(entry["keys"], {keys[0]: self.record(0, "x")["time"],
                                         keys[1]: self.record(1, "x")["time"]})
        # Second run: the home prompt is corrected to work -> the digest is
        # still there, so it changes and names the moved time.
        classify.set_human(self.root, keys[1], "work", DAY)
        run = self.do_prepare()
        changed = [s for s in self.sources(run) if s["id"] == "prompts:personal/" + DAY]
        self.assertEqual([s["op"] for s in changed], ["changed"])
        self.assertEqual(self.diff_of(changed[0]).splitlines()[0],
                         "옮겨진 프롬프트 시각: %s" % self.record(1, "x")["time"])

    def test_changed_digest_has_no_moved_line_when_prompt_just_left(self):  # case 3
        self.seed()
        self.write_history([("개인 레포 프롬프트 하나", self.repo),
                            ("새로 친 프롬프트 하나", self.repo)])
        run = self.do_prepare()
        changed = [s for s in self.sources(run) if s["id"] == "prompts:personal/" + DAY]
        self.assertEqual([s["op"] for s in changed], ["changed"])
        self.assertNotIn("옮겨진 프롬프트", self.diff_of(changed[0]))

    def test_whole_digest_moved_is_deleted(self):  # case 1
        keys = self.seed()
        classify.set_human(self.root, keys[1], "work", DAY)
        self.write_history([("개인 레포 프롬프트 하나", "/nonexistent-folder"),
                            ("홈에서 친 프롬프트 하나", self.home)])
        classify.set_human(self.root, keys[0], "work", DAY)
        run = self.do_prepare()
        ops = [(s["id"], s["op"]) for s in self.sources(run)]
        self.assertIn(("prompts:personal/" + DAY, "deleted"), ops)

    def test_human_unknown_correction_moves_prompt_to_unresolved(self):  # case 4
        keys = self.seed()
        classify.set_human(self.root, keys[1], "unknown", DAY)
        run = self.do_prepare()
        changed = [s for s in self.sources(run) if s["id"] == "prompts:personal/" + DAY]
        self.assertEqual(self.diff_of(changed[0]).splitlines()[0],
                         "옮겨진 프롬프트 시각: %s" % self.record(1, "x")["time"])

    A_TEXT, B_TEXT = "개인 레포 프롬프트 하나", "홈에서 친 프롬프트 하나"

    def test_old_keys_survive_a_commit_without_them(self):  # case 2
        keys = self.seed()
        self.write_rows([(0, self.A_TEXT, self.repo)])  # B rotated out
        self.commit_all(self.do_prepare())
        entry = prepare.load_sources(self.root)["sources"]["prompts:personal/" + DAY]
        self.assertEqual(sorted(entry["keys"]), sorted(keys))
        self.assertEqual(entry["keys"][keys[1]], self.record(1, "x")["time"])

    def test_later_move_of_dropped_prompt_deletes_digest(self):  # case 2
        keys = self.seed()
        self.write_rows([(0, self.A_TEXT, self.repo)])
        self.commit_all(self.do_prepare())
        # Both left the history except B, which shows up again as work.
        classify.set_human(self.root, keys[1], "work", DAY)
        self.write_rows([(1, self.B_TEXT, self.home)])
        run = self.do_prepare()
        ops = [(s["id"], s["op"]) for s in self.sources(run)]
        self.assertIn(("prompts:personal/" + DAY, "deleted"), ops)
        self.assertIn(("prompts:work/" + DAY, "new"), ops)

    def test_later_move_of_dropped_prompt_is_named_in_changed_diff(self):  # case 2
        keys = self.seed()
        self.write_rows([(0, self.A_TEXT, self.repo)])
        self.commit_all(self.do_prepare())
        classify.set_human(self.root, keys[1], "work", DAY)
        self.write_rows([(0, self.A_TEXT, self.repo), (1, self.B_TEXT, self.home),
                         (2, "새로 친 개인 프롬프트", self.repo)])
        run = self.do_prepare()
        changed = [s for s in self.sources(run) if s["id"] == "prompts:personal/" + DAY]
        self.assertEqual([s["op"] for s in changed], ["changed"])
        self.assertEqual(self.diff_of(changed[0]).splitlines()[0],
                         "옮겨진 프롬프트 시각: %s" % self.record(1, "x")["time"])

    def test_new_keys_are_merged_into_old_ones(self):  # case 2
        keys = self.seed()
        self.write_rows([(0, self.A_TEXT, self.repo), (2, "새로 친 개인 프롬프트", self.repo)])
        self.commit_all(self.do_prepare())
        entry = prepare.load_sources(self.root)["sources"]["prompts:personal/" + DAY]
        new_key = classify.prompt_key(self.record(2, "새로 친 개인 프롬프트"))
        self.assertEqual(sorted(entry["keys"]), sorted(keys + [new_key]))

    def test_history_rotation_is_not_a_withdrawal(self):  # case 2
        self.seed()
        self.write_history([])
        run = self.do_prepare()
        self.assertEqual(self.sources(run), [])
        self.write_history([("전혀 다른 프롬프트 내용", self.home)])
        run = self.do_prepare()
        self.assertNotIn("deleted", [s["op"] for s in self.sources(run)])


class StoredMentionsTest(unittest.TestCase):
    def data(self, status):
        ids = ["memory:a", "memory:b", "memory:c"]
        return {"sources": dict((i, {"domain": "personal", "status": status}) for i in ids),
                "mentions": {"personal": {"Foo": ids}}}

    def promoted(self, data):
        mentions, merges = verify.stored_mentions(data, "personal")
        return verify.promotions(mentions, merges, [])

    def test_deleted_sources_do_not_promote(self):  # case 7
        self.assertEqual(self.promoted(self.data("deleted")), [])

    def test_active_sources_promote(self):  # case 7
        self.assertEqual([(n, c) for n, c, _p in self.promoted(self.data("active"))],
                         [(["Foo"], 3)])

    def test_other_domain_does_not_count_and_missing_does(self):  # case 7
        data = self.data("active")
        data["sources"]["memory:c"]["domain"] = "work"
        self.assertEqual(self.promoted(data), [])
        del data["sources"]["memory:c"]
        self.assertEqual(len(self.promoted(data)), 1)


class RetiredMentionsTest(unittest.TestCase):
    LIVE = ["memory:l1", "memory:l2", "memory:l3"]
    DEAD = ["memory:d1", "memory:d2", "memory:d3"]

    def data(self):
        sources = dict((i, {"domain": "personal", "status": "active"}) for i in self.LIVE)
        sources.update(dict((i, {"domain": "personal", "status": "deleted"}) for i in self.DEAD))
        return {"sources": sources,
                "mentions": {"personal": {"Live": self.LIVE, "Dead": self.DEAD, "Empty": []}},
                "mention_groups": {"personal": [["Live", "Dead"], ["Dead", "Empty"],
                                                ["Live", "Empty"]]}}

    def test_retired_name_leaves_mentions_and_groups(self):  # case 1
        mentions, merges = verify.stored_mentions(self.data(), "personal")
        self.assertNotIn("Dead", mentions)
        self.assertEqual(mentions["Live"], set(self.LIVE))
        self.assertEqual(mentions["Empty"], set())  # no ids: kept as it was
        self.assertEqual(merges, [["Live", "Empty"]])  # one-name groups vanish

    def test_retired_name_is_not_promoted_even_when_merged(self):  # case 1
        mentions, merges = verify.stored_mentions(self.data(), "personal")
        promoted = verify.promotions(mentions, merges, [])
        names = [name for group, _count, _page in promoted for name in group]
        self.assertNotIn("Dead", names)
        self.assertIn("Live", names)

    def test_group_keeps_other_names(self):  # case 1
        data = self.data()
        data["mention_groups"]["personal"] = [["Live", "Dead", "Empty"]]
        _mentions, merges = verify.stored_mentions(data, "personal")
        self.assertEqual(merges, [["Live", "Empty"]])

    def test_sync_aliases_does_not_write_retired_name(self):  # case 1
        wt = os.path.join(_helpers.make_temp_dir(), "wt")
        self.addCleanup(__import__("shutil").rmtree, os.path.dirname(wt), True)
        os.makedirs(os.path.join(wt, "personal", "projects"))
        path = os.path.join(wt, "personal", "projects", "live.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("---\ntitle: Live\ntype: project\ndomain: personal\n"
                         "updated: 2026-11-06\n---\n# Live\n\n## 개요\n\n내용 있음\n\n"
                         "## 내 메모\n")
        _mentions, merges = verify.stored_mentions(self.data(), "personal")
        changed = verify.sync_aliases(wt, "personal", merges)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("Dead", text)
        self.assertEqual(changed, ["personal/projects/live.md"])
        self.assertIn("Empty", text)


class BridgeTest(SessionCase):
    def records(self):
        a = rec(1, "회사 쪽 프롬프트 하나요", cwd="/w", session="A")
        p1 = rec(2, "두 세션에 걸친 프롬프트", session="A")
        p2 = rec(2, "두 세션에 걸친 프롬프트", session="B")
        q = rec(3, "B 세션의 다른 프롬프트", session="B")
        return a, p1, p2, q

    def test_work_travels_over_duplicate_bridge_in_any_order(self):  # case 8
        import itertools
        a, p1, p2, q = self.records()
        classes = {classify.prompt_key(q): {"c": "personal", "d": DAY}}
        for order in itertools.permutations([a, p1, p2, q]):
            found = self.resolve(list(order), classes=classes)
            self.assertEqual(self.verdict(found, q["text"]), ("work", "session"), order)
            self.assertEqual(self.verdict(found, p1["text"]), ("work", "session"), order)

    def test_human_personal_or_unknown_is_not_a_bridge(self):  # case 8
        a, p1, p2, q = self.records()
        for answer_class in ("personal", "unknown"):
            classes = {classify.prompt_key(q): {"c": "personal", "d": DAY},
                       classify.prompt_key(p1): {"c": answer_class, "d": DAY, "by": "human"}}
            found = self.resolve([a, p1, p2, q], classes=classes)
            self.assertEqual(self.verdict(found, q["text"]), ("personal", "llm"), answer_class)

    def test_human_work_bridge_still_spreads(self):  # case 8
        a, p1, p2, q = self.records()
        classes = {classify.prompt_key(q): {"c": "personal", "d": DAY},
                   classify.prompt_key(p1): {"c": "work", "d": DAY, "by": "human"}}
        found = self.resolve([p1, p2, q], classes=classes)
        self.assertEqual(self.verdict(found, q["text"]), ("work", "session"))


class HintTest(ClassifyCase):
    def page(self, title, aliases):
        return verify.Page("x.md", {"type": "project", "title": title}, "", title, aliases,
                           [title] + aliases)

    def test_secret_name_dropped_and_newline_escaped(self):  # case 11
        secret = j("ghp", "_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
        self.assertTrue(redact.scan(secret))
        pages = {"work": [self.page("회사프로젝트", ["줄\n바꿈", secret])],
                 "personal": [self.page("개인프로젝트", [])]}
        runner = FakeRunner(all_to("personal"))
        with mock.patch.object(verify, "live_pages", side_effect=lambda root, d: pages[d]):
            self.run_classify([rec(1, "주말 프롬프트 내용 입니다")], runner)
        prompt = runner.requests[0]["prompt"]
        self.assertNotIn(secret, prompt)
        self.assertIn("- work: " + json.dumps(["줄\n바꿈", "회사프로젝트"], ensure_ascii=False),
                      prompt)
        self.assertIn('- personal: ["개인프로젝트"]', prompt)
        self.assertEqual(len([l for l in prompt.splitlines() if l.startswith("- work:")]), 1)

    def test_no_projects_is_empty_array(self):  # case 11
        runner = FakeRunner(all_to("personal"))
        self.run_classify([rec(1, "주말 프롬프트 내용 입니다")], runner)
        prompt = runner.requests[0]["prompt"]
        self.assertIn("- work: []", prompt)
        self.assertIn("- personal: []", prompt)


class CliTest(ClassifyCase):
    def setUp(self):
        ClassifyCase.setUp(self)
        self.hist = os.path.join(self.tmp, "history.jsonl")
        self.texts = ["홈에서 친 첫 프롬프트요", "홈에서 친 둘째 프롬프트", "폴더로 정해진 프롬프트"]
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        self.git(repo, "init", "-q")
        self.git(repo, "remote", "add", "o", "git@github.com:MeUser/r.git")
        self.domains["owners"] = {"MeUser": "personal"}
        with open(os.path.join(self.root, "domains.json"), "w", encoding="utf-8") as handle:
            json.dump(self.domains, handle)
        with open(self.hist, "w", encoding="utf-8") as handle:
            for index, text in enumerate(self.texts):
                row = {"display": text, "timestamp": int((noon(DAY) + index * 60) * 1000),
                       "project": repo if index == 2 else self.home, "sessionId": "s%d" % index}
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.env["WIKI_SRC_HISTORY"] = self.hist
        for name in ("PROJECTS", "HANDOFF", "DESIGN"):
            self.env["WIKI_SRC_" + name] = os.path.join(self.tmp, "none-" + name)
        self.env["WIKI_SRC_TRAYCER_DB"] = os.path.join(self.tmp, "none.db")
        self.env["WIKI_SRC_TRAYCER_EPICS_DB"] = os.path.join(self.tmp, "none2.db")

        previous = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, previous)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wiki.main(list(args) + ["--root", self.root], self.env)
        return code, out.getvalue(), err.getvalue()

    def keys(self):
        entries, _since, _w = prepare.prompt_entries(self.root, self.env, now=datetime.datetime.now())
        return entries

    def fixed_now(self):
        return mock.patch.object(prepare.datetime, "datetime", wraps=datetime.datetime)

    def test_list_hides_folder_decided_prompts(self):  # case 12
        code, out, _err = self.cli("prompts", "list")
        self.assertEqual(code, wiki.EXIT_OK)
        self.assertIn("홈에서 친 첫 프롬프트요", out)
        self.assertIn("홈에서 친 둘째 프롬프트", out)
        self.assertNotIn("폴더로 정해진 프롬프트", out)

    def test_list_class_filter(self):  # case 12
        record = [e["record"] for e in self.keys() if e["record"]["text"] == self.texts[0]][0]
        classify.save_classes(self.root, {classify.prompt_key(record):
                                          {"c": "personal", "d": record["date"]}})
        code, out, _err = self.cli("prompts", "list", "personal")
        self.assertEqual(code, wiki.EXIT_OK)
        self.assertIn(self.texts[0], out)
        self.assertNotIn(self.texts[1], out)

    def test_list_bogus_class_is_an_error(self):  # case 12
        code, out, err = self.cli("prompts", "list", "bogus")
        self.assertEqual(code, wiki.EXIT_ERROR)
        self.assertTrue(err)
        self.assertNotIn(self.texts[0], out)

    def store_classes(self):
        by_text = dict((e["record"]["text"], e["record"]) for e in self.keys())
        classify.save_classes(self.root, {
            classify.prompt_key(by_text[self.texts[0]]): {"c": "personal", "d": DAY},
            classify.prompt_key(by_text[self.texts[1]]): {"c": "unknown", "d": DAY}})

    def test_list_in_personal_repo_shows_only_personal(self):  # case 9
        self.store_classes()
        os.chdir(os.path.join(self.tmp, "repo"))
        code, out, _err = self.cli("prompts", "list")
        self.assertEqual(code, wiki.EXIT_OK)
        self.assertIn(self.texts[0], out)
        self.assertNotIn(self.texts[1], out)
        code, out, _err = self.cli("prompts", "list", "personal")
        self.assertEqual(code, wiki.EXIT_OK)
        self.assertIn(self.texts[0], out)

    def test_list_work_or_unknown_in_personal_repo_is_domain_conflict(self):  # case 9
        self.store_classes()
        os.chdir(os.path.join(self.tmp, "repo"))
        for wanted in ("work", "unknown"):
            code, out, err = self.cli("prompts", "list", wanted)
            self.assertEqual(code, wiki.EXIT_ERROR, wanted)
            self.assertIn("domain_conflict", out + err)
            self.assertNotIn(self.texts[1], out)

    def test_list_in_undeterminable_folder_shows_everything(self):  # case 9
        self.store_classes()
        for folder in (self.home, self.tmp):
            os.chdir(folder)
            code, out, _err = self.cli("prompts", "list")
            self.assertEqual(code, wiki.EXIT_OK)
            self.assertIn(self.texts[0], out)
            self.assertIn(self.texts[1], out)
            code, out, _err = self.cli("prompts", "list", "unknown")
            self.assertEqual(code, wiki.EXIT_OK)
            self.assertIn(self.texts[1], out)
            self.assertNotIn(self.texts[0], out)

    def test_list_preview_hides_secret_shaped_text(self):  # case 9
        secret = j("ghp", "_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
        self.assertTrue(redact.scan(secret))
        with open(self.hist, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"display": "토큰 %s 로 로그인해줘" % secret,
                                     "timestamp": int((noon(DAY) + 600) * 1000),
                                     "project": self.home, "sessionId": "sx"},
                                    ensure_ascii=False) + "\n")
        code, out, _err = self.cli("prompts", "list")
        self.assertEqual(code, wiki.EXIT_OK)
        self.assertIn("로그인해줘", out)
        self.assertNotIn(secret, out)
        self.assertIn("[REDACTED", out)

    def test_set_is_saved_and_reflected(self):  # case 12
        entry = [e for e in self.keys() if e["record"]["text"] == self.texts[1]][0]
        key = classify.prompt_key(entry["record"])
        code, _out, _err = self.cli("prompts", "set", key[:8], "work")
        self.assertEqual(code, wiki.EXIT_OK)
        saved = classify.load_classes(self.root)[key]
        self.assertEqual((saved["c"], saved["by"]), ("work", "human"))
        again = [e for e in self.keys() if e["record"]["text"] == self.texts[1]][0]
        self.assertEqual((again["domain"], again["via"]), ("work", "human"))

    def test_set_errors(self):  # case 12
        entry = [e for e in self.keys() if e["record"]["text"] == self.texts[1]][0]
        key = classify.prompt_key(entry["record"])
        for args in (("set", "zzzzzzzz", "work"), ("set", key[:8], "bogus"), ("set", key[:8]),
                     ("set",)):
            code, _out, err = self.cli("prompts", *args)
            self.assertEqual(code, wiki.EXIT_ERROR, args)
            self.assertTrue(err, args)
        self.assertEqual(classify.load_classes(self.root), {})

    def test_classify_changes_neither_pages_nor_sources(self):  # case 12
        def snapshot():
            found = {}
            for dirpath, dirnames, files in os.walk(self.root):
                dirnames[:] = [d for d in dirnames if d not in (".git", ".state")]
                for name in files:
                    path = os.path.join(dirpath, name)
                    with open(path, "rb") as handle:
                        found[path] = handle.read()
            return found
        before = snapshot()
        sources_before = os.path.exists(prepare.sources_path(self.root))
        runner = answering({self.texts[0]: "personal", self.texts[1]: "unknown"})
        with mock.patch.object(absorb.ClaudeRunner, "from_settings", return_value=runner):
            code, out, _err = self.cli("prompts", "classify")
        self.assertEqual(code, wiki.EXIT_OK)
        self.assertEqual(len(runner.requests), 1)
        self.assertEqual(json.loads(out)["personal"], 1)
        self.assertEqual(snapshot(), before)
        self.assertEqual(os.path.exists(prepare.sources_path(self.root)), sources_before)
        self.assertEqual(sorted(v["c"] for v in classify.load_classes(self.root).values()),
                         ["personal", "unknown"])


class ReportTest(ClassifyCase):
    def setUp(self):
        ClassifyCase.setUp(self)
        hist = os.path.join(self.tmp, "history.jsonl")
        with open(hist, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"display": "홈에서 친 프롬프트 입니다",
                                     "timestamp": int(noon(DAY) * 1000), "project": self.home,
                                     "sessionId": "s"}, ensure_ascii=False) + "\n")
        self.paths = prepare.SourcePaths(os.path.join(self.tmp, "p"), hist, None, None, None,
                                         None)
        self.runner = FakeRunner(lambda request: {"ok": True, "structured": {
            "pages": [], "merges": [], "mentions": [], "withdrawn_src": [], "notes": ""}})

    def absorb(self, **kwargs):
        return absorb.absorb(self.root, environ=self.env, paths=self.paths, now=NOW,
                             runner=self.runner, fs_root=self.tmp,
                             rules_path=os.path.join(self.tmp, "r", "r.md"), **kwargs)

    def test_report_has_classified_from_injected_classifier(self):  # case 13
        stats = {"work": 0, "personal": 1, "unknown": 0, "cost_usd": 0.5}

        def classifier(root, pending, classes, domains, warnings, since_date):
            return classes
        classifier.stats = stats
        report = self.absorb(classifier=classifier)
        self.assertEqual(report["classified"], stats)

    def test_report_classified_empty_without_classifier(self):  # case 13
        self.assertEqual(self.absorb()["classified"], {})

    def test_prompt_classifier_collects_stats(self):  # case 13
        run = absorb.prompt_classifier(self.env)
        self.assertEqual(run.stats, {})
        runner = answering({"홈에서 친 프롬프트 입니다": "personal"})
        record = rec(0, "홈에서 친 프롬프트 입니다")
        with mock.patch.object(absorb.ClaudeRunner, "from_settings", return_value=runner):
            run(self.root, [record], {}, self.domains, [], "2026-10-01")
        self.assertEqual(run.stats["personal"], 1)
        self.assertEqual(run.stats["cost_usd"], 0.5)


if __name__ == "__main__":
    unittest.main()
