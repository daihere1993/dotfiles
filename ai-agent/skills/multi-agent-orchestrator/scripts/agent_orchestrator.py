#!/usr/bin/env python3
"""Machine-readable discovery and serialized integration for agent task branches."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integration_lock import integration_lock

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
RECEIPT_SCHEMA_VERSION = 1


class OrchestratorError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class Config:
    path: Path
    base_branch: str
    task_prefix: str
    allow_worktree_remove: bool
    runtime_stopped_states: tuple[str, ...]
    setup: list[str]
    verify: list[str]
    runtime_status: list[str]
    runtime_stop: list[str]


@dataclass(frozen=True)
class Task:
    branch: str
    sha: str


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise OrchestratorError(
            "git-command-failed",
            f"git {' '.join(args)} failed",
            {"returncode": result.returncode, "stderr": result.stderr.strip()},
        )
    return result.stdout.strip()


def git_ok(root: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", *args], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0


def run_stream(root: Path, command: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run a repository command while keeping detailed output out of JSON stdout."""

    try:
        stream = sys.stderr.fileno()
        stdout: Any = stream
        stderr: Any = subprocess.STDOUT
        captured = False
    except (AttributeError, OSError):
        stdout = subprocess.PIPE
        stderr = subprocess.STDOUT
        captured = True

    result = subprocess.run(command, cwd=root, check=False, stdout=stdout, stderr=stderr)
    if captured and result.stdout:
        sys.stderr.write(result.stdout.decode(errors="replace"))
    return result


def load_config(root: Path) -> Config:
    path = root / ".agent-integration.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise OrchestratorError("config-missing", "Repository has no .agent-integration.json") from error
    except (OSError, json.JSONDecodeError) as error:
        raise OrchestratorError("config-invalid", f"Cannot read repository config: {path}", str(error)) from error

    commands = raw.get("commands", {})
    if not isinstance(commands, dict):
        raise OrchestratorError("config-invalid", "Config commands must be an object")

    def command(name: str) -> list[str]:
        value = commands.get(name)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
            raise OrchestratorError("config-invalid", f"Config commands.{name} must be a nonempty string array")
        return value

    stopped = raw.get("runtimeStoppedStates", ["stopped", "not-started"])
    if not isinstance(stopped, list) or not stopped or not all(isinstance(item, str) for item in stopped):
        raise OrchestratorError("config-invalid", "runtimeStoppedStates must be a nonempty string array")
    prefix = raw.get("taskBranchPrefix", "agent/")
    if not isinstance(prefix, str) or not prefix:
        raise OrchestratorError("config-invalid", "taskBranchPrefix must be a nonempty string")
    base = raw.get("baseBranch")
    if not isinstance(base, str) or not base:
        raise OrchestratorError("config-invalid", "baseBranch must be a nonempty string")
    allow = raw.get("allowWorktreeRemove", False)
    if not isinstance(allow, bool):
        raise OrchestratorError("config-invalid", "allowWorktreeRemove must be boolean")
    schema_version = raw.get("schemaVersion")
    if type(schema_version) is not int or schema_version != RECEIPT_SCHEMA_VERSION:
        raise OrchestratorError("config-invalid", "Config schemaVersion must be 1")
    verify = command("verify")
    return Config(
        path=path,
        base_branch=base,
        task_prefix=prefix,
        allow_worktree_remove=allow,
        runtime_stopped_states=tuple(stopped),
        setup=command("setup"),
        verify=verify,
        runtime_status=command("runtimeStatus"),
        runtime_stop=command("runtimeStop"),
    )


def parse_task_values(values: list[str], argument: str) -> list[Task]:
    tasks: list[Task] = []
    seen: set[str] = set()
    for value in values:
        branch, separator, sha = value.partition("=")
        if not separator or not branch or not FULL_SHA.fullmatch(sha):
            raise OrchestratorError("invalid-task", f"{argument} entries must use branch=<40-character-full-sha>")
        if branch in seen:
            raise OrchestratorError("invalid-task", f"Branch repeated in {argument}: {branch}")
        seen.add(branch)
        tasks.append(Task(branch=branch, sha=sha))
    return tasks


def verify_full_commit(root: Path, sha: str, label: str) -> None:
    if not FULL_SHA.fullmatch(sha):
        raise OrchestratorError("invalid-sha", f"{label} is not a full commit SHA")
    if not git_ok(root, "cat-file", "-e", f"{sha}^{{commit}}"):
        raise OrchestratorError("unknown-sha", f"{label} does not exist in this repository")


def validate_receipt(root: Path, branch: str, sha: str, config: Config) -> dict[str, Any]:
    notes = git(root, "notes", "--ref=agent-task", "show", sha, check=False)
    if notes.startswith("error: ") or not notes.strip():
        return {"valid": False, "errors": ["missing-note"], "note": None}
    try:
        receipt = json.loads(notes)
    except json.JSONDecodeError:
        return {"valid": False, "errors": ["malformed-json"], "note": None}
    if not isinstance(receipt, dict):
        return {"valid": False, "errors": ["malformed-json"], "note": None}
    errors: list[str] = []
    if type(receipt.get("schemaVersion")) is not int or receipt.get("schemaVersion") != RECEIPT_SCHEMA_VERSION:
        errors.append("schemaVersion")
    if receipt.get("status") != "ready":
        errors.append("status")
    if receipt.get("branch") != branch:
        errors.append("branch")
    if receipt.get("testedHead") != sha:
        errors.append("testedHead")
    if receipt.get("baseBranch") != config.base_branch:
        errors.append("baseBranch")
    for field in ("testedHead", "baseHead", "observedBaseHead"):
        value = receipt.get(field)
        if not isinstance(value, str) or not FULL_SHA.fullmatch(value):
            errors.append(f"{field}-shape")
            continue
        if not git_ok(root, "cat-file", "-e", f"{value}^{{commit}}"):
            errors.append(f"{field}-unknown")
    base_head = receipt.get("baseHead")
    tested_head = receipt.get("testedHead")
    if isinstance(base_head, str) and isinstance(tested_head, str) and not errors:
        if not git_ok(root, "merge-base", "--is-ancestor", base_head, tested_head):
            errors.append("baseHead-not-ancestor")
    checks = receipt.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("checks-empty")
    else:
        for check in checks:
            if not isinstance(check, dict) or check.get("result") != "passed" or not isinstance(check.get("command"), str):
                errors.append("checks-not-passed")
    manual = receipt.get("manualAcceptance")
    if not isinstance(manual, dict):
        errors.append("manualAcceptance-shape")
    else:
        required = manual.get("required")
        result = manual.get("result")
        if type(required) is not bool:
            errors.append("manualAcceptance-required-shape")
        if required is True and result != "passed":
            errors.append("manualAcceptance-required")
        if required is False and result not in {"not-required", "passed"}:
            errors.append("manualAcceptance-result")
    runtime = receipt.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("state") not in {"stopped", "not-started"}:
        errors.append("runtime")
    return {"valid": not errors, "errors": sorted(set(errors)), "note": receipt}


def runtime_state(root: Path, config: Config) -> dict[str, Any]:
    result = subprocess.run(
        config.runtime_status,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = result.stdout
    if result.returncode != 0:
        return {"state": "unknown", "processes": None, "output": output.strip(), "returncode": result.returncode}
    start, end = output.find("{"), output.rfind("}")
    if start < 0 or end <= start:
        return {"state": "unknown", "processes": None, "output": output.strip(), "returncode": result.returncode}
    try:
        status = json.loads(output[start : end + 1])
    except json.JSONDecodeError:
        return {"state": "unknown", "processes": None, "output": output.strip(), "returncode": result.returncode}
    processes = status.get("processes")
    return {
        "state": status.get("state", "unknown"),
        "phase": status.get("phase", "unknown"),
        "processes": processes if isinstance(processes, dict) else None,
        "output": output.strip(),
        "returncode": result.returncode,
    }


def ensure_runtime_stopped(root: Path, config: Config, *, may_stop: bool) -> dict[str, Any]:
    state = runtime_state(root, config)
    if state["state"] in config.runtime_stopped_states:
        return state
    if not may_stop:
        raise OrchestratorError("runtime-running", f"Runtime is {state['state']}", state)
    result = run_stream(root, config.runtime_stop)
    if result.returncode != 0:
        raise OrchestratorError("runtime-stop-failed", "Configured runtime stop command failed")
    state = runtime_state(root, config)
    if state["state"] not in config.runtime_stopped_states:
        raise OrchestratorError("runtime-stop-failed", "Runtime did not reach a stopped state", state)
    return state


def worktree_status(root: Path, path: Path) -> str:
    if not path.is_dir():
        return "missing"
    return "dirty" if git(path, "status", "--porcelain=v1", "--untracked-files=all").strip() else "clean"


def parse_worktrees(root: Path) -> dict[str, Path]:
    raw = git(root, "worktree", "list", "--porcelain")
    worktrees: dict[str, Path] = {}
    current: dict[str, str] = {}
    def finish() -> None:
        branch_ref = current.get("branch")
        if branch_ref and branch_ref.startswith("refs/heads/"):
            worktrees[branch_ref.removeprefix("refs/heads/")] = Path(current["worktree"])

    for line in raw.splitlines() + [""]:
        if line:
            key, _, value = line.partition(" ")
            current[key] = value
            continue
        if "worktree" in current:
            finish()
        current = {}
    return worktrees


def discover(root: Path) -> dict[str, Any]:
    config = load_config(root)
    base_head = git(root, "rev-parse", config.base_branch)
    branches = git(root, "for-each-ref", f"refs/heads/{config.task_prefix}", "--format=%(refname:lstrip=2)|%(objectname)")
    worktrees = parse_worktrees(root)
    candidates: list[dict[str, Any]] = []
    for row in filter(None, branches.splitlines()):
        branch, sha = row.split("|", 1)
        receipt = validate_receipt(root, branch, sha, config)
        path = worktrees.get(branch)
        worktree = worktree_status(root, path) if path else "missing"
        runtime = (
            runtime_state(path, config)
            if path and worktree == "clean"
            else {"state": "unknown" if path else "not-started", "processes": None}
        )
        contained = git_ok(root, "merge-base", "--is-ancestor", sha, base_head)
        ahead = git_ok(root, "merge-base", "--is-ancestor", base_head, sha)
        subjects = git(root, "log", "--format=%s", f"{base_head}..{sha}").splitlines()
        verdict = "contained" if contained else "unverified"
        if receipt["valid"] and ahead and not contained:
            if worktree == "dirty":
                verdict = "dirty"
            elif runtime["state"] not in config.runtime_stopped_states:
                verdict = "runtime-running"
            else:
                verdict = "ready"
        candidates.append(
            {
                "branch": branch,
                "testedHead": sha,
                "task": subjects[0] if subjects else "",
                "commits": subjects,
                "receipt": receipt,
                "worktree": {"state": worktree, "path": str(path) if path else None},
                "runtime": runtime,
                "aheadOfBase": ahead,
                "containedInBase": contained,
                "verdict": verdict,
            }
        )
    return {
        "status": "discovered",
        "baseBranch": config.base_branch,
        "baseHead": base_head,
        "candidates": candidates,
    }


def clean_base(root: Path, config: Config) -> tuple[str, str, dict[str, Any]]:
    branch = git(root, "symbolic-ref", "--short", "HEAD")
    if branch != config.base_branch:
        raise OrchestratorError("wrong-target", f"Base checkout must be on {config.base_branch}", branch)
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all").strip()
    if status:
        raise OrchestratorError("base-dirty", "Base checkout has unaccounted changes", status)
    return branch, git(root, "rev-parse", "HEAD"), ensure_runtime_stopped(root, config, may_stop=True)


def require_expected_base(root: Path, config: Config, expected: str) -> tuple[str, str, dict[str, Any]]:
    verify_full_commit(root, expected, "expected base head")
    branch, head, runtime = clean_base(root, config)
    if head != expected:
        raise OrchestratorError("base-moved", f"Expected {config.base_branch} at {expected}, found {head}")
    return branch, head, runtime


def preflight_tasks(root: Path, config: Config, tasks: list[Task], base_head: str) -> list[dict[str, Any]]:
    worktrees = parse_worktrees(root)
    evidence: list[dict[str, Any]] = []
    for task in tasks:
        verify_full_commit(root, task.sha, f"{task.branch} sha")
        tip = git(root, "rev-parse", task.branch, check=False)
        if tip != task.sha:
            raise OrchestratorError("task-moved", f"Branch {task.branch} is no longer at {task.sha}", tip)
        receipt = validate_receipt(root, task.branch, task.sha, config)
        if not receipt["valid"]:
            raise OrchestratorError("unverified-task", f"Receipt is not ready for {task.branch}", receipt["errors"])
        if git_ok(root, "merge-base", "--is-ancestor", task.sha, base_head):
            evidence.append({"branch": task.branch, "sha": task.sha, "result": "already-contained"})
            continue
        if not git_ok(root, "merge-base", "--is-ancestor", base_head, task.sha):
            raise OrchestratorError("stale-task", f"{task.branch} does not contain current base {base_head}")
        path = worktrees.get(task.branch)
        if path:
            status = worktree_status(root, path)
            if status == "dirty":
                raise OrchestratorError("task-dirty", f"Task worktree is dirty: {path}")
            ensure_runtime_stopped(path, config, may_stop=False)
        evidence.append({"branch": task.branch, "sha": task.sha, "result": "approved"})
    return evidence


def replace_log_placeholder(command: list[str], log_path: Path) -> list[str]:
    return [log_path.as_posix() if item == "{verification_log}" else item for item in command]


def verification_log(root: Path) -> Path:
    directory = Path(tempfile.gettempdir()) / "agent-integration" / re.sub(r"[^A-Za-z0-9._-]", "-", str(root))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="verify-", suffix=".log", dir=directory)
    os.close(descriptor)
    path = Path(name)
    path.chmod(0o600)
    path.write_text("", encoding="utf-8")
    return path


def execute_environment(root: Path, config: Config, *, verify: bool) -> dict[str, Any]:
    setup = run_stream(root, config.setup)
    if setup.returncode != 0:
        raise OrchestratorError("setup-failed", "Repository setup command failed")
    if not verify:
        return {"setup": {"command": config.setup, "result": "passed"}, "verification": {"result": "not-requested"}}
    log = verification_log(root)
    command = replace_log_placeholder(config.verify, log)
    result = run_stream(root, command)
    verification = {
        "command": command,
        "result": "passed" if result.returncode == 0 else "failed",
        "log": str(log),
    }
    if result.returncode != 0:
        raise OrchestratorError("verification-failed", "Integration verification failed", verification)
    if git(root, "status", "--porcelain=v1", "--untracked-files=all").strip():
        raise OrchestratorError("verification-dirty", "Verification left tracked/untracked changes in base")
    return {
        "setup": {"command": config.setup, "result": "passed"},
        "verification": verification,
    }


def merge_task(root: Path, task: Task) -> dict[str, Any]:
    tip = git(root, "rev-parse", task.branch)
    if tip != task.sha:
        raise OrchestratorError("task-moved", f"Branch moved before merge: {task.branch}", {"expected": task.sha, "found": tip})
    result = subprocess.run(
        ["git", "merge", "--no-ff", "--no-edit", task.sha],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode == 0:
        return {"branch": task.branch, "sha": task.sha, "mergeHead": git(root, "rev-parse", "HEAD"), "result": "merged"}
    merge_head = root / ".git" / "MERGE_HEAD"
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    if (common / "MERGE_HEAD").exists() or merge_head.exists():
        git(root, "merge", "--abort")
        raise OrchestratorError("merge-conflict", f"Conflicts while merging {task.branch}", result.stdout.strip())
    raise OrchestratorError("merge-failed", f"Git failed while merging {task.branch}", result.stdout.strip())


def cleanup_task(root: Path, config: Config, task: Task, final_base: str) -> dict[str, Any]:
    tip = git(root, "rev-parse", task.branch, check=False)
    if tip != task.sha:
        return {"branch": task.branch, "sha": task.sha, "result": "skipped", "reason": "tip-moved", "tip": tip or None}
    if not git_ok(root, "merge-base", "--is-ancestor", task.sha, final_base):
        return {"branch": task.branch, "sha": task.sha, "result": "skipped", "reason": "not-contained"}
    receipt = validate_receipt(root, task.branch, task.sha, config)
    if not receipt["valid"]:
        return {"branch": task.branch, "sha": task.sha, "result": "skipped", "reason": "unverified", "errors": receipt["errors"]}
    worktrees = parse_worktrees(root)
    path = worktrees.get(task.branch)
    if path:
        if not config.allow_worktree_remove:
            return {"branch": task.branch, "sha": task.sha, "result": "skipped", "reason": "worktree-removal-disabled", "path": str(path)}
        status = worktree_status(root, path)
        if status == "dirty":
            return {"branch": task.branch, "sha": task.sha, "result": "skipped", "reason": "dirty-worktree", "path": str(path)}
        ensure_runtime_stopped(path, config, may_stop=True)
        result = subprocess.run(["git", "worktree", "remove", str(path)], cwd=root, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            return {"branch": task.branch, "sha": task.sha, "result": "skipped", "reason": "worktree-remove-failed", "stderr": result.stderr.strip()}
    result = subprocess.run(["git", "branch", "-d", task.branch], cwd=root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return {"branch": task.branch, "sha": task.sha, "result": "failed", "reason": "branch-delete-failed", "stderr": result.stderr.strip()}
    return {"branch": task.branch, "sha": task.sha, "result": "deleted", "worktreeRemoved": path is not None}


def emit(payload: dict[str, Any], result_file: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if result_file:
        result_file.write_text(text + "\n", encoding="utf-8")
    print(text)


def run_locked(command_name: str, root: Path, action) -> dict[str, Any]:
    try:
        with integration_lock(root):
            return action()
    except BlockingIOError:
        return {"status": "lock-busy", "command": command_name}


def integrate(root: Path, expected_base: str, merges: list[Task], cleanups: list[Task]) -> dict[str, Any]:
    for task in cleanups:
        if task.branch not in {item.branch for item in merges}:
            raise OrchestratorError("invalid-cleanup", f"Cleanup branch was not part of merge batch: {task.branch}")

    def action() -> dict[str, Any]:
        config = load_config(root)
        _, starting_base, runtime = require_expected_base(root, config, expected_base)
        evidence = preflight_tasks(root, config, merges, starting_base)
        final_base = starting_base
        merges_result: list[dict[str, Any]] = []
        environment: dict[str, Any] = {}
        try:
            for task in merges:
                if evidence_for(merges_result, evidence, task) == "already-contained":
                    merges_result.append({"branch": task.branch, "sha": task.sha, "result": "skipped", "reason": "already-contained"})
                    continue
                merges_result.append(merge_task(root, task))
            # A batch may intentionally update repository integration commands.
            # Verify with the merged contract, not the pre-merge configuration.
            merged_config = load_config(root)
            final_base = git(root, "rev-parse", "HEAD")
            environment = execute_environment(root, merged_config, verify=True)
            final_head = git(root, "rev-parse", "HEAD")
            if final_head != final_base:
                raise OrchestratorError("base-moved", "Base changed during verification", {"expected": final_base, "found": final_head})
        except OrchestratorError as error:
            payload = {
                "status": error.code,
                "message": error.message,
                "details": error.details,
                "baseBranch": config.base_branch,
                "startingBaseHead": starting_base,
                "finalBaseHead": git(root, "rev-parse", "HEAD"),
                "merges": merges_result,
                "environment": environment,
                "cleanup": [],
                "runtime": runtime_state(root, config),
            }
            if error.code == "verification-failed":
                payload["status"] = "verification-failed"
                payload["environment"] = error.details
            raise StoreResult(payload) from error

        cleanup_results = [cleanup_task(root, merged_config, task, final_base) for task in cleanups]
        failed_cleanup = any(item["result"] not in {"deleted"} for item in cleanup_results)
        return {
            "status": "cleanup-failed" if failed_cleanup else "verified-and-cleaned" if cleanups else "verified",
            "baseBranch": config.base_branch,
            "startingBaseHead": starting_base,
            "finalBaseHead": final_base,
            "merges": merges_result,
            "environment": environment,
            "cleanup": cleanup_results,
            "runtime": runtime_state(root, config),
        }

    try:
        return run_locked("integrate", root, action)
    except StoreResult as stored:
        return stored.payload


class StoreResult(Exception):
    def __init__(self, payload: dict[str, Any]):
        super().__init__(payload.get("message", "stored result"))
        self.payload = payload


def evidence_for(merges: list[dict[str, Any]], evidence: list[dict[str, Any]], task: Task) -> str:
    for item in evidence:
        if item.get("branch") == task.branch:
            return str(item.get("result", ""))
    return ""


def verify(root: Path, expected_base: str) -> dict[str, Any]:
    config = load_config(root)

    def action():
        _, starting_base, runtime = require_expected_base(root, config, expected_base)
        try:
            environment = execute_environment(root, config, verify=True)
            final_base = git(root, "rev-parse", "HEAD")
            if final_base != starting_base:
                raise OrchestratorError("base-moved", "Base changed during verification")
        except OrchestratorError as error:
            if error.code == "verification-failed":
                return {
                    "status": "verification-failed",
                    "message": error.message,
                    "baseBranch": config.base_branch,
                    "startingBaseHead": starting_base,
                    "finalBaseHead": git(root, "rev-parse", "HEAD"),
                    "environment": error.details,
                    "runtime": runtime_state(root, config),
                }
            raise
        return {
            "status": "verified",
            "baseBranch": config.base_branch,
            "startingBaseHead": starting_base,
            "finalBaseHead": final_base,
            "environment": environment,
            "runtime": runtime,
        }

    return run_locked("verify", root, action)


def cleanup(root: Path, expected_base: str, tasks: list[Task]) -> dict[str, Any]:
    config = load_config(root)

    def action():
        _, starting_base, runtime = require_expected_base(root, config, expected_base)
        results = [cleanup_task(root, config, task, starting_base) for task in tasks]
        failed = any(item["result"] not in {"deleted"} for item in results)
        return {
            "status": "cleanup-failed" if failed else "cleaned",
            "baseBranch": config.base_branch,
            "startingBaseHead": starting_base,
            "finalBaseHead": git(root, "rev-parse", "HEAD"),
            "cleanup": results,
            "runtime": runtime,
        }

    return run_locked("cleanup", root, action)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    discover_parser = sub.add_parser("discover")
    discover_parser.add_argument("--repo", required=True)
    discover_parser.add_argument("--json", action="store_true")
    for name in ("integrate", "verify", "cleanup"):
        command = sub.add_parser(name)
        command.add_argument("--repo", required=True)
        command.add_argument("--expected-base-head", required=True)
        command.add_argument("--result-file")
        if name == "integrate":
            command.add_argument("--merge", action="append", default=[], required=True)
            command.add_argument("--cleanup", action="append", default=[])
        elif name == "cleanup":
            command.add_argument("--cleanup", action="append", default=[], required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    root = Path(args.repo).resolve(strict=True)
    result_file = Path(args.result_file).resolve() if getattr(args, "result_file", None) else None
    try:
        if args.command == "discover":
            payload = discover(root)
        elif args.command == "integrate":
            merges = parse_task_values(args.merge, "--merge")
            cleanups = parse_task_values(args.cleanup, "--cleanup")
            payload = integrate(root, args.expected_base_head, merges, cleanups)
        elif args.command == "verify":
            payload = verify(root, args.expected_base_head)
        else:
            tasks = parse_task_values(args.cleanup, "--cleanup")
            payload = cleanup(root, args.expected_base_head, tasks)
        emit(payload, result_file)
        return 0 if payload.get("status") in {"discovered", "verified", "verified-and-cleaned", "cleaned"} else 1
    except OrchestratorError as error:
        emit(
            {
                "status": error.code,
                "message": error.message,
                "details": error.details,
            },
            result_file,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
