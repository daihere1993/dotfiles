"""Behavioral tests using disposable repositories, never the user's refs."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("with-integration-lock.py")


class IntegrationLockTests(unittest.TestCase):
    def test_shared_worktrees_exclude_a_second_session_and_release_after_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, linked = root / "repo", root / "linked"
            repo.mkdir()
            subprocess.run(
                ["git", "init", "-b", "main", str(repo)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.test",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "fixture",
                ],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(linked)],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            ready = root / "ready"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--",
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import time,sys; "
                    "Path(sys.argv[1]).touch(); time.sleep(30)",
                    str(ready),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--repo",
                        str(linked),
                        "--",
                        sys.executable,
                        "-c",
                        'raise SystemExit("must not run")',
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 75, result.stderr)
                process.kill()
                process.communicate(timeout=5)
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--repo",
                        str(linked),
                        "--",
                        sys.executable,
                        "-c",
                        'print("acquired")',
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "acquired")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)

    def test_shell_retains_lock_while_executing_a_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            # A nested helper in this same shell must still see the outer lock.
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--",
                    "/bin/sh",
                    "-c",
                    '"$1" "$2" --repo "$3" -- /bin/true; code=$?; test "$code" = 75',
                    "test-shell",
                    sys.executable,
                    str(SCRIPT),
                    str(repo),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lock = repo / ".git/agent-integration.lock"
            self.assertEqual(os.stat(lock).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
