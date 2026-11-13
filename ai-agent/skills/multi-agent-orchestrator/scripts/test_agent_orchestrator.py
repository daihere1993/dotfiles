"""Behavioral tests for the orchestrator CLI using disposable repositories."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).with_name("agent_orchestrator.py")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def commit(root: Path, message: str, filename: str | None = None) -> str:
    filename = filename or f"{message.replace(' ', '-')}.txt"
    (root / filename).write_text(message + "\n", encoding="utf-8")
    git(root, "add", filename)
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def commit_index(root: Path, message: str) -> str:
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def git_true(root: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def command_output(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def write_config(root: Path, *, verify_code: str = "pass", allow_remove: bool = True) -> None:
    config = {
        "schemaVersion": 2,
        "baseBranch": "main",
        "taskBranchPrefix": "agent/",
        "allowWorktreeRemove": allow_remove,
        "runtimeStoppedStates": ["stopped", "not-started"],
        "commands": {
            "setup": command_output("print('setup')"),
            "verify": command_output(verify_code),
            "runtimeStatus": command_output(
                "import json; print(json.dumps({'state':'stopped','phase':'stopped','processes':{}}))"
            ),
            "runtimeStop": command_output("print('stop')"),
        },
    }
    (root / ".agent-integration.json").write_text(json.dumps(config), encoding="utf-8")


def make_fixture(task_name: str = "agent/test") -> tuple[Path, Path, str, str, str]:
    temporary = Path(tempfile.mkdtemp(prefix="orchestrator-cli-"))
    root = temporary / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    base = commit(root, "base")
    write_config(root)
    git(root, "add", ".agent-integration.json")
    base = commit_index(root, "repository integration config")
    git(root, "branch", task_name)
    task_root = temporary / "task"
    git(root, "worktree", "add", str(task_root), task_name)
    task = commit(task_root, "task change")
    return temporary, root, task_root, base, task


def cli(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"CLI did not emit JSON: {result.stdout}\n{result.stderr}") from error
    payload["_returncode"] = result.returncode
    payload["_stderr"] = result.stderr
    return payload


class OrchestratorCliTests(unittest.TestCase):
    maxDiff = None

    def test_discovery_lists_a_committed_clean_task_as_a_candidate(self):
        temporary, root, task_root, base, task = make_fixture()
        payload = cli("discover", "--repo", str(root), "--json")
        self.assertEqual(payload["_returncode"], 0)
        self.assertEqual(payload["baseHead"], base)
        self.assertEqual(len(payload["candidates"]), 1)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["branch"], "agent/test")
        self.assertEqual(candidate["sha"], task)
        self.assertTrue(candidate["hasContentDiff"])
        self.assertEqual(candidate["aheadCount"], 1)
        self.assertEqual(candidate["worktree"]["state"], "clean")
        self.assertEqual(candidate["status"], "candidate")

    def test_discovery_excludes_a_dirty_task(self):
        temporary, root, task_root, base, task = make_fixture()
        (task_root / "uncommitted.txt").write_text("work in progress\n", encoding="utf-8")
        payload = cli("discover", "--repo", str(root), "--json")
        self.assertEqual(payload["candidates"][0]["status"], "dirty")

    def test_integrate_requires_an_unchanged_expected_base(self):
        temporary, root, task_root, base, task = make_fixture()
        commit(root, "unrelated main movement")
        current = git(root, "rev-parse", "main")
        payload = cli(
            "integrate", "--repo", str(root), "--expected-base-head", base,
            "--merge", f"agent/test={task}",
        )
        self.assertEqual(payload["_returncode"], 1)
        self.assertEqual(payload["status"], "base-moved")
        self.assertEqual(git(root, "rev-parse", "main"), current)

    def test_integrate_merge_verify_and_cleanup(self):
        temporary, root, task_root, base, task = make_fixture()
        payload = cli(
            "integrate",
            "--repo", str(root),
            "--expected-base-head", base,
            "--merge", f"agent/test={task}",
            "--cleanup", f"agent/test={task}",
            "--result-file", str(temporary / "result.json"),
        )
        self.assertEqual(payload["_returncode"], 0, payload)
        self.assertEqual(payload["status"], "verified-and-cleaned")
        self.assertEqual(payload["merges"][0]["mode"], "squash")
        self.assertEqual(payload["merges"][0]["result"], "squashed")
        self.assertNotEqual(payload["merges"][0]["integratedSha"], task)
        self.assertEqual(payload["cleanup"][0]["result"], "deleted")
        self.assertEqual(payload["cleanup"][0]["mode"], "squash")
        self.assertEqual(git(root, "rev-parse", "main"), payload["finalBaseHead"])
        self.assertFalse(git_true(root, "merge-base", "--is-ancestor", task, "main"))
        self.assertTrue(git_true(root, "merge-base", "--is-ancestor", payload["merges"][0]["integratedSha"], "main"))
        result = subprocess.run(["git", "rev-parse", "--verify", "agent/test"], cwd=root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_regular_merge_preserves_commits_and_cleans_with_ancestry(self):
        temporary, root, task_root, base, task = make_fixture()
        payload = cli(
            "integrate",
            "--repo", str(root),
            "--expected-base-head", base,
            "--merge-mode", "merge",
            "--merge", f"agent/test={task}",
            "--cleanup", f"agent/test={task}",
        )
        self.assertEqual(payload["_returncode"], 0, payload)
        self.assertEqual(payload["status"], "verified-and-cleaned")
        self.assertEqual(payload["merges"][0]["mode"], "merge")
        self.assertEqual(payload["merges"][0]["result"], "merged")
        self.assertTrue(git_true(root, "merge-base", "--is-ancestor", task, "main"))
        self.assertEqual(git(root, "branch", "--list", "agent/test", "--format=%(refname:short)"), "")

    def test_squash_cleanup_requires_the_integrated_commit_mapping(self):
        temporary, root, task_root, base, task = make_fixture()
        integration = cli(
            "integrate",
            "--repo", str(root),
            "--expected-base-head", base,
            "--merge", f"agent/test={task}",
        )
        self.assertEqual(integration["_returncode"], 0, integration)
        integrated = integration["merges"][0]["integratedSha"]
        payload = cli(
            "cleanup",
            "--repo", str(root),
            "--expected-base-head", integration["finalBaseHead"],
            "--cleanup", f"agent/test={task}={integrated}",
        )
        self.assertEqual(payload["_returncode"], 0, payload)
        self.assertEqual(payload["cleanup"][0]["result"], "deleted")
        self.assertEqual(payload["cleanup"][0]["mode"], "squash")
        result = subprocess.run(["git", "rev-parse", "--verify", "agent/test"], cwd=root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_verification_failure_preserves_the_merge_and_skips_cleanup(self):
        temporary, root, task_root, base, task = make_fixture()
        config = json.loads((root / ".agent-integration.json").read_text())
        config["commands"]["verify"] = [sys.executable, "-c", "raise SystemExit('verify failed')"]
        (task_root / ".agent-integration.json").write_text(json.dumps(config))
        git(task_root, "add", ".agent-integration.json")
        git(task_root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-m", "failing verify config")
        task = git(task_root, "rev-parse", "HEAD")
        payload = cli(
            "integrate",
            "--repo", str(root),
            "--expected-base-head", base,
            "--merge", f"agent/test={task}",
            "--cleanup", f"agent/test={task}",
        )
        self.assertEqual(payload["_returncode"], 1)
        self.assertEqual(payload["status"], "verification-failed")
        self.assertEqual(payload["merges"][0]["result"], "squashed")
        self.assertEqual(payload["cleanup"], [])
        integrated = payload["merges"][0]["integratedSha"]
        self.assertTrue(git_true(root, "merge-base", "--is-ancestor", integrated, "main"))
        self.assertEqual(git(root, "branch", "--list", "agent/test", "--format=%(refname:short)"), "agent/test")

    def test_cleanup_rejects_a_moved_branch_tip(self):
        temporary, root, task_root, base, task = make_fixture()
        git(task_root, "checkout", "--detach", "main")
        git(root, "branch", "-f", "agent/test", "main")
        payload = cli(
            "cleanup", "--repo", str(root), "--expected-base-head", base,
            "--cleanup", f"agent/test={task}",
        )
        self.assertEqual(payload["_returncode"], 1)
        self.assertEqual(payload["status"], "cleanup-failed")
        self.assertEqual(payload["cleanup"][0]["reason"], "tip-moved")


if __name__ == "__main__":
    unittest.main()
