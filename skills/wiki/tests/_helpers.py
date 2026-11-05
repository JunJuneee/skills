"""Shared test helpers: import path and an isolated HOME/git environment.

Tests never touch the real ~/wiki, ~/.claude, launchd or the user's git
config: HOME and WIKI_ROOT point into a temp dir and git reads no global or
system config unless a test supplies one.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TESTS_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
TEMPLATES_DIR = os.path.join(SKILL_DIR, "templates")
REPO_ROOT = os.path.dirname(os.path.dirname(SKILL_DIR))
WIKI_PY = os.path.join(SCRIPTS_DIR, "wiki.py")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


def isolated_env(home, extra=None):
    env = {
        "HOME": home,
        "USER": os.environ.get("USER", "tester"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LLM_WIKI_HOOK": "0",
    }
    if extra:
        env.update(extra)
    return env


class TempHomeCase(unittest.TestCase):
    """Creates self.home (a fake HOME) and self.root (WIKI_ROOT inside it)."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="wiki-test-"))
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.root = os.path.join(self.home, "wiki")
        self.env = isolated_env(self.home, {"WIKI_ROOT": self.root})

    def tearDown(self):
        for dirpath, dirnames, _files in os.walk(self.tmp):
            for name in dirnames:
                try:
                    os.chmod(os.path.join(dirpath, name), 0o755)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, **kwargs):
        env = dict(self.env)
        env.update(kwargs.pop("env", {}) or {})
        return subprocess.run(
            [sys.executable, WIKI_PY] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            cwd=kwargs.pop("cwd", self.tmp), timeout=60,
        )

    def git(self, cwd, *args, **kwargs):
        env = dict(self.env)
        env.update(kwargs.pop("env", {}) or {})
        return subprocess.run(["git", "-C", cwd] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env, timeout=60)
