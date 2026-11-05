import json
import os
import stat
import unittest

import _helpers
import common


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class InitTest(_helpers.TempHomeCase):
    def init(self, *extra, **kwargs):
        proc = self.run_cli(*(list(extra) + ["--json", "init"]), **kwargs)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        return json.loads(proc.stdout.decode())

    def test_layout(self):
        summary = self.init()
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["root"], self.root)
        root = self.root
        for domain, subs in common.DOMAIN_SUBDIRS.items():
            for sub in subs:
                self.assertTrue(os.path.isfile(os.path.join(root, domain, sub, ".gitkeep")))
        self.assertFalse(os.path.exists(os.path.join(root, "personal", "people")))
        for name in ("SCHEMA.md", "domains.json", "settings.json", "index.md", "log.md",
                     "now.md", "about-me.md", ".gitignore"):
            self.assertTrue(os.path.isfile(os.path.join(root, name)), name)
        for name in ("now.md", "about-me.md"):
            with open(os.path.join(root, name), encoding="utf-8") as handle:
                _before, notes = common.split_my_notes(handle.read())
            self.assertTrue(notes.startswith(common.MY_NOTES_HEADING))
            self.assertIn("### work", notes)
            self.assertIn("### personal", notes)
        self.assertEqual(mode(os.path.join(root, ".state")), 0o700)
        for sub in common.STATE_SUBDIRS:
            self.assertEqual(mode(os.path.join(root, ".state", sub)), 0o700)
        self.assertEqual(mode(os.path.join(root, "inbox")), 0o700)
        for domain in common.DOMAINS:
            self.assertEqual(mode(os.path.join(root, "inbox", domain)), 0o700)
        self.assertTrue(common.is_initialized(root))
        common.load_domains(root)
        self.assertEqual(common.load_settings(root)["model"], common.SETTINGS_DEFAULTS["model"])
        self.assertTrue(summary["domains_placeholders"])

    def test_git_repo(self):
        summary = self.init()
        head = self.git(self.root, "rev-parse", "HEAD").stdout.decode().strip()
        self.assertEqual(summary["head"], head)
        self.assertEqual(len(head), 40)
        branch = self.git(self.root, "symbolic-ref", "--short", "HEAD").stdout.decode().strip()
        self.assertEqual(branch, "main")
        self.assertEqual(self.git(self.root, "status", "--porcelain").stdout, b"")
        self.assertEqual(self.git(self.root, "remote").stdout, b"")
        author = self.git(self.root, "log", "-1", "--format=%ae").stdout.decode().strip()
        self.assertEqual(author, common.WIKI_GIT_EMAIL)
        files = self.git(self.root, "ls-files").stdout.decode().split()
        self.assertIn("SCHEMA.md", files)
        self.assertIn("personal/projects/.gitkeep", files)
        self.assertFalse([f for f in files if f.startswith((".state", "inbox"))])

    def test_gitignore_covers_private_paths(self):
        self.init()
        for path in (".absorb-wt/x", ".state/run.json", ".bin/1/wiki.py", "inbox/work/n.md",
                     ".obsidian/workspace.json", ".obsidian/workspace-mobile.json",
                     ".obsidian/plugins/foo/data.json", "personal/_drafts/now.md"):
            proc = self.git(self.root, "check-ignore", "-q", path)
            self.assertEqual(proc.returncode, 0, path)
        for path in ("personal/projects/x.md", "now.md", ".obsidian/community-plugins.json"):
            self.assertEqual(self.git(self.root, "check-ignore", "-q", path).returncode, 1, path)

    def test_idempotent_keeps_human_files(self):
        self.init()
        head = self.git(self.root, "rev-parse", "HEAD").stdout
        edits = {}
        for name in ("now.md", "about-me.md", "domains.json", "settings.json"):
            path = os.path.join(self.root, name)
            content = '{"owners": {}}\n' if name == "domains.json" else "사람이 고침\n"
            if name == "settings.json":
                content = '{"model": "opus"}\n'
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
            edits[name] = content
        summary = self.init()
        self.assertEqual(summary["created"], [])
        for name, content in edits.items():
            with open(os.path.join(self.root, name), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), content, name)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD").stdout, head)

    def test_resumes_partial_init_and_restores_missing(self):
        self.init()
        os.remove(os.path.join(self.root, "SCHEMA.md"))
        os.rmdir(os.path.join(self.root, ".state", "snapshots"))
        summary = self.init()
        self.assertIn("SCHEMA.md", summary["created"])
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".state", "snapshots")))

    def test_recovers_without_git_dir(self):
        self.init()
        import shutil
        shutil.rmtree(os.path.join(self.root, ".git"))
        summary = self.init()
        self.assertEqual(len(summary["head"]), 40)
        files = self.git(self.root, "ls-files").stdout.decode().split()
        for name in ("SCHEMA.md", "now.md", ".gitignore", "work/people/.gitkeep"):
            self.assertIn(name, files)

    def test_recovers_without_state_dir(self):
        self.init()
        import shutil
        shutil.rmtree(os.path.join(self.root, ".state"))
        summary = self.init()
        self.assertEqual(len(summary["head"]), 40)
        self.assertTrue(common.is_initialized(self.root))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.root, ".state")).st_mode), 0o700)

    def test_recovers_when_first_commit_never_happened(self):
        self.init()
        import shutil
        shutil.rmtree(os.path.join(self.root, ".git"))
        self.assertEqual(self.git(self.root, "init", "-q").returncode, 0)
        summary = self.init()
        self.assertEqual(len(summary["head"]), 40)
        self.assertEqual(self.git(self.root, "status", "--porcelain").stdout, b"")

    def test_flat_pinned_copy_runs(self):
        import shutil
        import subprocess
        import sys
        pinned = os.path.join(self.tmp, "bin", "0.0.0-abcdef12")
        os.makedirs(pinned)
        for name in os.listdir(_helpers.SCRIPTS_DIR):
            if name.endswith(".py"):
                shutil.copy(os.path.join(_helpers.SCRIPTS_DIR, name), pinned)
        shutil.copytree(_helpers.TEMPLATES_DIR, os.path.join(pinned, "templates"))
        target = os.path.join(self.tmp, "pinned-wiki")
        proc = subprocess.run([sys.executable, os.path.join(pinned, "wiki.py"), "init",
                               "--root", target, "--json"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env,
                              cwd=self.tmp, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertTrue(os.path.isfile(os.path.join(target, "SCHEMA.md")))

    def test_existing_gitignore_gets_missing_lines(self):
        self.init()
        path = os.path.join(self.root, ".gitignore")
        with open(path, "w") as handle:
            handle.write("custom-ignore\n")
        self.init()
        with open(path) as handle:
            text = handle.read()
        self.assertTrue(text.startswith("custom-ignore\n"))
        self.assertIn("/.state/", text)

    def test_refuses_non_wiki_dir(self):
        os.makedirs(self.root)
        with open(os.path.join(self.root, "notes.txt"), "w") as handle:
            handle.write("x")
        proc = self.run_cli("--json", "init")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "root_not_empty")
        self.assertEqual(sorted(os.listdir(self.root)), ["notes.txt"])

    def test_refuses_home_and_file(self):
        proc = self.run_cli("--json", "--root", self.home, "init")
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "root_not_allowed")
        target = os.path.join(self.tmp, "file")
        open(target, "w").close()
        proc = self.run_cli("--json", "--root", target, "init")
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "root_not_directory")

    def test_touches_nothing_else_under_home(self):
        self.init()
        # Apple's /usr/bin/python3 puts its bytecode cache (sys.pycache_prefix)
        # under $HOME/Library/Caches/com.apple.python; that is the interpreter,
        # not init. Anything else under HOME is a failure.
        allowed_cache = os.path.join(self.home, "Library", "Caches", "com.apple.python")
        for dirpath, dirnames, filenames in os.walk(self.home):
            if dirpath == self.home:
                self.assertEqual(sorted(set(dirnames + filenames) - {"Library"}), ["wiki"])
                dirnames[:] = [d for d in dirnames if d == "Library"]
                continue
            if dirpath.startswith(allowed_cache):
                continue
            self.assertTrue(allowed_cache.startswith(dirpath), dirpath)
            self.assertEqual(filenames, [], dirpath)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "Library", "LaunchAgents")))

    def test_root_from_env_and_flag(self):
        other = os.path.join(self.tmp, "elsewhere")
        summary = self.init("--root", other)
        self.assertEqual(summary["root"], other)
        self.assertFalse(os.path.exists(self.root))
        proc = self.run_cli("--json", "init", env={"WIKI_ROOT": ""})
        self.assertEqual(json.loads(proc.stdout.decode())["root"], os.path.join(self.home, "wiki"))

    def test_user_git_hooks_and_signing_are_ignored(self):
        hooks = os.path.join(self.tmp, "hooks")
        os.makedirs(hooks)
        marker = os.path.join(self.tmp, "hook-ran")
        for name in ("pre-commit", "post-commit", "commit-msg"):
            hook = os.path.join(hooks, name)
            with open(hook, "w") as handle:
                handle.write("#!/bin/sh\necho ran >> '%s'\nexit 1\n" % marker)
            os.chmod(hook, 0o755)
        gitconfig = os.path.join(self.tmp, "gitconfig")
        with open(gitconfig, "w") as handle:
            handle.write("[core]\n\thooksPath = %s\n[commit]\n\tgpgsign = true\n"
                         "[user]\n\tname = Someone\n\temail = someone@example.invalid\n" % hooks)
        self.init(env={"GIT_CONFIG_GLOBAL": gitconfig})
        self.assertFalse(os.path.exists(marker))
        author = self.git(self.root, "log", "-1", "--format=%ae",
                          env={"GIT_CONFIG_GLOBAL": gitconfig}).stdout.decode().strip()
        self.assertEqual(author, "someone@example.invalid")

    def test_git_missing_reason(self):
        proc = self.run_cli("--json", "init", env={"PATH": os.path.join(self.tmp, "no-bin")})
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "git_missing")

    def test_text_output(self):
        proc = self.run_cli("init")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("wiki init", proc.stdout.decode())


class CliTest(_helpers.TempHomeCase):
    def test_commands_without_wiki_create_nothing(self):
        agents = os.path.join(self.tmp, "agents")
        env = {"WIKI_LAUNCH_AGENTS_DIR": agents, "WIKI_LAUNCHCTL": os.path.join(self.tmp, "nope")}
        for args in (["note", "--domain", "work", "x"],
                     ["query", "--domain", "work", "x"], ["status"],
                     ["schedule", "install", "--no-load"], ["schedule", "print"]):
            proc = self.run_cli("--json", *args, env=env)
            self.assertEqual(proc.returncode, 1, args)
            self.assertEqual(json.loads(proc.stdout.decode())["reason"], "not_initialized", args)
        proc = self.run_cli("--json", "schedule", "uninstall", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertFalse(json.loads(proc.stdout.decode())["removed"])
        self.assertFalse(os.path.exists(self.root))
        self.assertFalse(os.path.exists(agents))

    def test_absorb_without_wiki_creates_nothing(self):
        proc = self.run_cli("--json", "absorb")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "not_initialized")
        # A scheduled tick without a wiki is a silent skip (launchd keeps
        # firing every 30 minutes; nothing to record or notify).
        proc = self.run_cli("--json", "absorb", "--scheduled")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertTrue(json.loads(proc.stdout.decode())["skipped"])
        self.assertFalse(os.path.exists(self.root))

    def test_options_before_or_after_command(self):
        other = os.path.join(self.tmp, "after")
        proc = self.run_cli("init", "--root", other, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(json.loads(proc.stdout.decode())["root"], other)
        proc = self.run_cli("--json", "--root", other, "init")
        self.assertEqual(json.loads(proc.stdout.decode())["root"], other)
        proc = self.run_cli("--root", other, "init", "--json")
        self.assertEqual(json.loads(proc.stdout.decode())["root"], other)
        proc = self.run_cli("status", "--json")
        self.assertEqual(json.loads(proc.stdout.decode())["reason"], "not_initialized")
        proc = self.run_cli("--root", other, "status", "--json")
        self.assertTrue(json.loads(proc.stdout.decode())["ok"])

    def test_usage_errors(self):
        self.assertEqual(self.run_cli("note", "x").returncode, 2)
        self.assertEqual(self.run_cli("note", "--domain", "both", "x").returncode, 2)
        self.assertEqual(self.run_cli().returncode, 2)


if __name__ == "__main__":
    unittest.main()
