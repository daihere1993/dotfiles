from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import BuildError, ValidationError
from .jsonutil import canonical_json
from .models import MachineIdentity


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, command: Sequence[str], *, check: bool = True) -> CommandResult: ...


class SubprocessRunner:
    def run(self, command: Sequence[str], *, check: bool = True) -> CommandResult:
        process = subprocess.run(command, check=False, capture_output=True, text=True)
        result = CommandResult(process.returncode, process.stdout, process.stderr)
        if check and process.returncode:
            detail = f"{' '.join(command)}\n{process.stderr.strip()}"
            raise BuildError(
                f"command failed ({process.returncode}): {detail}",
                next_step="Review the build output, fix the configuration, then retry.",
            )
        return result


def find_repository(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() and (candidate / "flake.nix").is_file():
            return candidate
    raise ValidationError(
        f"could not find a repository containing both .git and flake.nix above {start}",
        next_step="Run this command from the dotfiles repository.",
    )


def identity_json(identity: MachineIdentity) -> str:
    return canonical_json(identity.to_dict()).decode().strip()


def archive_repository(runner: CommandRunner, repository: Path) -> Path:
    result = runner.run(["nix", "flake", "archive", "--json", f"path:{repository}"])
    try:
        path = Path(json.loads(result.stdout)["path"])
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise BuildError(
            f"Nix returned an invalid flake archive result: {result.stdout!r}"
        ) from error
    if not str(path).startswith("/nix/store/"):
        raise BuildError(f"flake archive is not in the Nix Store: {path}")
    return path


def reject_concurrent_apply(runner: CommandRunner) -> None:
    result = runner.run(["ps", "-axo", "pid=,command="], check=False)
    current_pid = os.getpid()
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not fields[0].isdigit() or int(fields[0]) == current_pid:
            continue
        try:
            command = shlex.split(fields[1])
        except ValueError:
            continue
        executable = Path(command[0]).name if command else ""
        is_dot = executable == "dot"
        is_python_dot = executable.startswith("python") and any(
            "dotfiles_cli" in argument or argument.endswith("/dot") for argument in command[1:]
        )
        if "apply" in command and (is_dot or is_python_dot):
            raise ValidationError(
                f"another recognizable dot apply process is running: pid {fields[0]}",
                next_step="Wait for the other apply to finish, then retry.",
            )


def build_domain(
    runner: CommandRunner,
    repository: Path,
    identity: MachineIdentity,
    domain: str,
) -> Path:
    instantiated = runner.run(
        [
            "nix-instantiate",
            str(repository / "nix/cli-domain.nix"),
            "--argstr",
            "repository",
            str(repository),
            "--argstr",
            "identityJson",
            identity_json(identity),
            "--argstr",
            "platform",
            domain,
        ]
    )
    drv_paths = [line for line in instantiated.stdout.splitlines() if line.endswith(".drv")]
    if len(drv_paths) != 1:
        raise BuildError(
            f"Nix returned {len(drv_paths)} derivations for {domain}: {instantiated.stdout!r}"
        )
    result = runner.run(["nix", "build", "--no-link", "--print-out-paths", f"{drv_paths[0]}^*"])
    paths = [Path(line) for line in result.stdout.splitlines() if line.startswith("/nix/store/")]
    if len(paths) != 1:
        raise BuildError(f"Nix returned {len(paths)} output paths for {domain}: {result.stdout!r}")
    return paths[0]


def evaluate_system(runner: CommandRunner, repository: Path, identity: MachineIdentity) -> str:
    result = runner.run(
        [
            "nix-instantiate",
            "--eval",
            "--strict",
            "--json",
            str(repository / "nix/cli-system-eval.nix"),
            "--argstr",
            "repository",
            str(repository),
            "--argstr",
            "identityJson",
            identity_json(identity),
        ]
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BuildError(f"Nix returned an invalid system drvPath: {result.stdout!r}") from error


def read_agent_config(runner: CommandRunner, repository: Path) -> dict:
    result = runner.run(
        [
            "nix-instantiate",
            "--eval",
            "--strict",
            "--json",
            str(repository / "nix/cli-agent-config.nix"),
            "--argstr",
            "repository",
            str(repository),
        ]
    )
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise BuildError(f"Nix returned invalid Agent configuration JSON: {error}") from error
