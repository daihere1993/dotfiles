from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .errors import BuildError, ValidationError
from .jsonutil import canonical_json
from .models import MachineIdentity

NIX_FEATURE_ARGS = ["--extra-experimental-features", "nix-command flakes"]


def nix_command(*arguments: str) -> list[str]:
    return ["nix", *NIX_FEATURE_ARGS, *arguments]


def nix_instantiate_command(*arguments: str) -> list[str]:
    return ["nix-instantiate", *NIX_FEATURE_ARGS, *arguments]


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        check: bool = True,
        stream: bool = False,
        on_line: Callable[[str], None] | None = None,
    ) -> CommandResult: ...


@dataclass
class SubprocessRunner:
    default_stream: bool = False
    default_on_line: Callable[[str], None] | None = None
    _stderr_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def run(
        self,
        command: Sequence[str],
        *,
        check: bool = True,
        stream: bool | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> CommandResult:
        use_stream = self.default_stream if stream is None else stream
        line_handler = on_line or self.default_on_line
        try:
            if use_stream and line_handler is not None:
                return self._run_streaming(command, check=check, on_line=line_handler)
            process = subprocess.run(command, check=False, capture_output=True, text=True)
        except OSError as error:
            raise BuildError(
                f"could not execute {command[0]}: {error}",
                next_step="Install the required command or repair the dot CLI profile, then retry.",
            ) from error
        result = CommandResult(process.returncode, process.stdout, process.stderr)
        if check and process.returncode:
            detail = f"{' '.join(command)}\n{process.stderr.strip()}"
            raise BuildError(
                f"command failed ({process.returncode}): {detail}",
                next_step="Review the build output, fix the configuration, then retry.",
            )
        return result

    def _run_streaming(
        self,
        command: Sequence[str],
        *,
        check: bool,
        on_line: Callable[[str], None],
    ) -> CommandResult:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as error:
            raise BuildError(
                f"could not execute {command[0]}: {error}",
                next_step="Install the required command or repair the dot CLI profile, then retry.",
            ) from error

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def consume(stream, collector: list[str], forward: bool) -> None:
            assert process.stdout is not None or process.stderr is not None
            for line in iter(stream.readline, ""):
                collector.append(line)
                if forward and line.rstrip():
                    on_line(line.rstrip("\n"))

        threads = []
        if process.stdout is not None:
            threads.append(
                threading.Thread(
                    target=consume,
                    args=(process.stdout, stdout_lines, False),
                    daemon=True,
                )
            )
        if process.stderr is not None:
            threads.append(
                threading.Thread(
                    target=consume,
                    args=(process.stderr, stderr_lines, True),
                    daemon=True,
                )
            )
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        returncode = process.wait()
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        result = CommandResult(returncode, stdout, stderr)
        if check and returncode:
            detail = f"{' '.join(command)}\n{stderr.strip()}"
            raise BuildError(
                f"command failed ({returncode}): {detail}",
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
    result = runner.run(nix_command("flake", "archive", "--json", f"path:{repository}"))
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


BuildSubstepCallback = Callable[[str, str], None]


def build_domain(
    runner: CommandRunner,
    repository: Path,
    identity: MachineIdentity,
    domain: str,
    *,
    verbose: bool = False,
    on_substep: BuildSubstepCallback | None = None,
) -> Path:
    def substep(label: str) -> None:
        if on_substep is not None:
            on_substep(domain, label)

    def on_line(line: str) -> None:
        if on_substep is not None:
            on_substep(domain, line)

    substep("evaluating derivation")
    instantiated = runner.run(
        nix_instantiate_command(
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
        ),
        stream=verbose,
        on_line=on_line if verbose else None,
    )
    drv_paths = [line for line in instantiated.stdout.splitlines() if line.endswith(".drv")]
    if len(drv_paths) != 1:
        raise BuildError(
            f"Nix returned {len(drv_paths)} derivations for {domain}: {instantiated.stdout!r}"
        )
    substep("building")
    result = runner.run(
        nix_command("build", "--no-link", "--print-out-paths", f"{drv_paths[0]}^*"),
        stream=verbose,
        on_line=on_line if verbose else None,
    )
    paths = [Path(line) for line in result.stdout.splitlines() if line.startswith("/nix/store/")]
    if len(paths) != 1:
        raise BuildError(f"Nix returned {len(paths)} output paths for {domain}: {result.stdout!r}")
    return paths[0]


def evaluate_system(runner: CommandRunner, repository: Path, identity: MachineIdentity) -> str:
    result = runner.run(
        nix_instantiate_command(
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
        )
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BuildError(f"Nix returned an invalid system drvPath: {result.stdout!r}") from error


def read_agent_config(runner: CommandRunner, repository: Path) -> dict:
    result = runner.run(
        nix_instantiate_command(
            "--eval",
            "--strict",
            "--json",
            str(repository / "nix/cli-agent-config.nix"),
            "--argstr",
            "repository",
            str(repository),
        )
    )
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise BuildError(f"Nix returned invalid Agent configuration JSON: {error}") from error
