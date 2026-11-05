import os
import subprocess
import unittest
from unittest import mock

import _helpers
import common


OWNERS = {"Example-Corp": "work", "SomeUser": "personal"}


class ParseRemoteUrlTest(unittest.TestCase):
    def test_forms(self):
        cases = {
            "https://github.com/Example-Corp/Repo.git": ("github.com", "example-corp", "repo"),
            "https://github.com/example-corp/repo": ("github.com", "example-corp", "repo"),
            "https://github.com/Example-Corp/repo/": ("github.com", "example-corp", "repo"),
            "https://github.com/Example-Corp/repo.git/": ("github.com", "example-corp", "repo"),
            "http://GitHub.com/SomeUser/x": ("github.com", "someuser", "x"),
            "https://user:pw@github.com:443/SomeUser/x.git": ("github.com", "someuser", "x"),
            "ssh://git@github.com/SomeUser/x.git": ("github.com", "someuser", "x"),
            "ssh://git@github.com:22/SomeUser/x": ("github.com", "someuser", "x"),
            "git://github.com/SomeUser/x.git": ("github.com", "someuser", "x"),
            "git@github.com:Example-Corp/Repo.git": ("github.com", "example-corp", "repo"),
            "git@github.com:/Example-Corp/Repo.git": ("github.com", "example-corp", "repo"),
            "github-work:Example-Corp/repo": ("github-work", "example-corp", "repo"),
            "github-work:Example-Corp/repo.git": ("github-work", "example-corp", "repo"),
            "me@github-personal:SomeUser/x.GIT": ("github-personal", "someuser", "x"),
            "https://gitlab.com/Group/Sub/project.git": ("gitlab.com", "group", "project"),
            "ssh://git@host/~SomeUser/x": ("host", "someuser", "x"),
        }
        for url, expected in cases.items():
            info = common.parse_remote_url(url)
            self.assertIsNotNone(info, url)
            self.assertEqual(tuple(info), expected, url)

    def test_local_and_invalid(self):
        for url in ("/srv/git/repo.git", "./relative/repo", "../up:dir/repo", "file:///srv/repo.git",
                    "C:/repos/x", "", "   ", "https://github.com/onlyowner", "host:", None,
                    "relative/path:with/colon"):
            self.assertIsNone(common.parse_remote_url(url), url)


class RemoteVTest(unittest.TestCase):
    OUTPUT = (
        "origin\tgit@github.com:SomeUser/x.git (fetch)\n"
        "origin\tgit@github.com:Example-Corp/x.git (push)\n"
        "upstream\thttps://github.com/SomeUser/x (fetch)\n"
        "upstream\thttps://github.com/SomeUser/x (push)\n"
    )

    def test_parse_fetch_and_push(self):
        self.assertEqual(common.parse_remote_v(self.OUTPUT), [
            "git@github.com:SomeUser/x.git",
            "git@github.com:Example-Corp/x.git",
            "https://github.com/SomeUser/x",
        ])

    def test_pushurl_to_work_makes_work(self):
        self.assertEqual(common.domain_for_remotes(common.parse_remote_v(self.OUTPUT), OWNERS), "work")


class DomainForRemotesTest(unittest.TestCase):
    def test_rules(self):
        d = common.domain_for_remotes
        self.assertEqual(d(["https://github.com/someuser/a"], OWNERS), "personal")
        self.assertEqual(d(["github-work:EXAMPLE-CORP/a"], OWNERS), "work")
        self.assertEqual(d(["https://github.com/someuser/a", "git@github.com:example-corp/b"],
                           OWNERS), "work")
        # personal + unlisted owner stays undetermined
        self.assertIsNone(d(["https://github.com/someuser/a", "https://github.com/other/b"], OWNERS))
        # work wins even next to an unlisted owner
        self.assertEqual(d(["https://github.com/other/b", "github-work:example-corp/a"], OWNERS),
                         "work")
        self.assertIsNone(d(["/local/path/repo"], OWNERS))
        self.assertIsNone(d(["https://github.com/someuser/a", "/local/mirror"], OWNERS))
        self.assertIsNone(d([], OWNERS))
        self.assertIsNone(d(["https://github.com/someuser/a"], {}))
        self.assertEqual(d(["https://github.com/someuser/a"], {" SomeUser ": "personal"}),
                         "personal")


class GitRemoteUrlsTest(_helpers.TempHomeCase):
    def test_real_repo_and_non_repo(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        with mock.patch.dict(os.environ, self.env):
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                            "git@github.com:SomeUser/x.git"], check=True)
            subprocess.run(["git", "-C", repo, "remote", "set-url", "--push", "origin",
                            "github-work:Example-Corp/x"], check=True)
            self.assertEqual(common.git_remote_urls(repo),
                             ["git@github.com:SomeUser/x.git", "github-work:Example-Corp/x"])
            self.assertEqual(common.repo_domain(repo, OWNERS), "work")
            plain = os.path.join(self.tmp, "plain")
            os.makedirs(plain)
            self.assertIsNone(common.git_remote_urls(plain))
            self.assertIsNone(common.repo_domain(plain, OWNERS))
            self.assertIsNone(common.git_remote_urls(os.path.join(self.tmp, "missing")))

    def test_git_missing_returns_none(self):
        with mock.patch.dict(os.environ, {"PATH": self.tmp}):
            self.assertIsNone(common.git_remote_urls(self.tmp))


if __name__ == "__main__":
    unittest.main()
