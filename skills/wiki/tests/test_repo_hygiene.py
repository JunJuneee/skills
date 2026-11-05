"""Public-repo guards for skills/wiki (no real paths, placeholders only,
nothing silently gitignored, Python 3.9 syntax)."""

import ast
import json
import os
import subprocess
import sys
import unittest

import _helpers
import common

TEXT_EXTENSIONS = (".py", ".md", ".json", ".yaml", ".txt")


def skill_files():
    for dirpath, dirnames, filenames in os.walk(_helpers.SKILL_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(TEXT_EXTENSIONS):
                yield os.path.join(dirpath, name)


def public_files():
    """skills/wiki plus the repo files this skill ships with (the plugin
    hooks and the README): the hygiene scans cover all of them (fix round
    1: a real file name once slipped into a fixture)."""
    for path in skill_files():
        yield path
    hooks = os.path.join(_helpers.REPO_ROOT, "hooks")
    if os.path.isdir(hooks):
        for name in sorted(os.listdir(hooks)):
            if name.endswith(TEXT_EXTENSIONS):
                yield os.path.join(hooks, name)
    readme = os.path.join(_helpers.REPO_ROOT, "README.md")
    if os.path.isfile(readme):
        yield readme


class HygieneTest(unittest.TestCase):
    def test_no_real_home_paths(self):
        needles = ["/" + "Users" + "/", "/" + "home" + "/" + os.environ.get("USER", "nobody") + "/"]
        for path in public_files():
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            for needle in needles:
                self.assertNotIn(needle, text, path)

    def test_no_encoded_real_home_folders(self):
        """Claude Code encodes a home path with "/" turned into "-"; only
        the neutral 'someone' placeholder may appear (review round 3). A
        local, untracked term list can be given in WIKI_HYGIENE_TERMS_FILE
        (one term per line) to also check employer names; it never lives
        in the repo."""
        import re

        encoded = re.compile(r"-(?:Users|home)-(?!someone-)[A-Za-z0-9_.]+-")
        terms = []
        terms_file = os.environ.get("WIKI_HYGIENE_TERMS_FILE")
        if terms_file and os.path.isfile(terms_file):
            with open(terms_file, encoding="utf-8") as handle:
                terms = [line.strip().lower() for line in handle if line.strip()]
        for path in public_files():
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertIsNone(encoded.search(text), path)
            lowered = text.lower()
            for term in terms:
                self.assertNotIn(term, lowered, path)

    def test_domains_template_is_placeholders_only(self):
        with open(os.path.join(_helpers.TEMPLATES_DIR, "domains.example.json"), encoding="utf-8") as h:
            data = json.load(h)
        for owner in data["owners"]:
            self.assertRegex(owner, r"^<[^<>]+>$")
        for term in data["work_terms"] + data["redact_allow"]:
            self.assertRegex(term, r"^<[^<>]+>$")

    def test_skill_frontmatter(self):
        with open(os.path.join(_helpers.SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
            fm, body = common.parse_frontmatter(handle.read())
        self.assertEqual(fm["name"], "wiki")
        self.assertTrue(fm["description"])
        self.assertIn("init", body)
        self.assertTrue(os.path.isfile(os.path.join(_helpers.SKILL_DIR, "agents", "openai.yaml")))

    def test_page_templates_parse_and_validate(self):
        pages = os.path.join(_helpers.TEMPLATES_DIR, "pages")
        for name in sorted(os.listdir(pages)):
            with open(os.path.join(pages, name), encoding="utf-8") as handle:
                text = handle.read()
            fm, body = common.parse_frontmatter(text)
            self.assertEqual(common.validate_page_frontmatter(fm), [], name)
            self.assertTrue(common.split_my_notes(body)[1], name)
            for match in common.SRC_COMMENT_RE.finditer(body):
                self.assertTrue(common.is_valid_source_id(match.group(1)), name)

    def test_deviations_match_skill_md(self):
        """Every SKILL.md deviation bullet carries a `dev:<code>` tag and
        run.json's PLAN_DEVIATIONS has exactly the same codes (panel: every
        deviation documented in both places)."""
        import re

        with open(os.path.join(_helpers.SKILL_DIR, "SKILL.md"), encoding="utf-8") as handle:
            text = handle.read()
        section = text.split("## 계획과 달라진 점", 1)[1].split("\n## ", 1)[0]
        bullets = [line for line in section.splitlines() if line.startswith("- ")]
        tags = []
        for line in bullets:
            match = re.search(r"`dev:([a-z0-9_]+)`\s*$", line)
            self.assertIsNotNone(match, line[:60])
            tags.append(match.group(1))
        codes = [item.split(":", 1)[0] for item in common.PLAN_DEVIATIONS]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(sorted(tags), sorted(codes))

    def test_python39_syntax(self):
        for path in skill_files():
            if path.endswith(".py"):
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                if sys.version_info >= (3, 8):
                    ast.parse(source, path, feature_version=(3, 9))

    def test_nothing_is_gitignored(self):
        probe = subprocess.run(["git", "-C", _helpers.REPO_ROOT, "rev-parse", "--is-inside-work-tree"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if probe.returncode != 0 or probe.stdout.strip() != b"true":
            self.skipTest("not inside a git checkout")
        rel = [os.path.relpath(path, _helpers.REPO_ROOT) for path in skill_files()]
        proc = subprocess.run(["git", "-C", _helpers.REPO_ROOT, "check-ignore", "--no-index", "--"] + rel,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.stdout.decode(), "", "gitignored files under skills/wiki")


if __name__ == "__main__":
    unittest.main()
