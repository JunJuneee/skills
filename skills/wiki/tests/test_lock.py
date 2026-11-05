import os
import subprocess
import sys
import textwrap
import unittest

import _helpers
import common


class LockTest(_helpers.TempHomeCase):
    def test_exclusive_and_release(self):
        lock = common.wiki_lock(self.root)
        with lock:
            with open(common.lock_path(self.root)) as handle:
                self.assertEqual(handle.read().strip(), str(os.getpid()))
            with self.assertRaises(common.LockBusy) as ctx:
                common.wiki_lock(self.root).acquire()
            self.assertEqual(ctx.exception.reason, "lock_busy")
            with open(common.lock_path(self.root)) as handle:
                self.assertEqual(handle.read().strip(), str(os.getpid()))
        again = common.wiki_lock(self.root).acquire()
        again.release()
        again.release()  # idempotent

    def test_other_process_is_refused(self):
        code = textwrap.dedent("""
            import sys
            sys.path.insert(0, %r)
            import common
            try:
                common.wiki_lock(%r).acquire()
            except common.LockBusy:
                sys.exit(7)
            sys.exit(0)
        """) % (_helpers.SCRIPTS_DIR, self.root)
        with common.wiki_lock(self.root):
            busy = subprocess.run([sys.executable, "-c", code], env=self.env, timeout=30)
            self.assertEqual(busy.returncode, 7)
        free = subprocess.run([sys.executable, "-c", code], env=self.env, timeout=30)
        self.assertEqual(free.returncode, 0)


if __name__ == "__main__":
    unittest.main()
