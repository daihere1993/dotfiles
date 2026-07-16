from __future__ import annotations

import unittest
from pathlib import Path

from dotfiles_cli.errors import BuildError
from dotfiles_cli.models import MachineIdentity
from dotfiles_cli.nix import CommandResult, SubprocessRunner, build_domain


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command, *, check=True):
        self.commands.append(list(command))
        if command[0] == "nix-instantiate":
            return CommandResult(0, "/nix/store/test-domain.drv\n", "")
        return CommandResult(0, "/nix/store/test-domain\n", "")


class NixCommandTests(unittest.TestCase):
    def test_build_domain_selects_derivation_outputs(self) -> None:
        runner = RecordingRunner()
        output = build_domain(
            runner,
            Path("/repository"),
            MachineIdentity("alice", "/Users/alice"),
            "codex",
        )
        self.assertEqual(output, Path("/nix/store/test-domain"))
        self.assertEqual(
            runner.commands[0][1:3],
            ["--extra-experimental-features", "nix-command flakes"],
        )
        self.assertEqual(runner.commands[1][-1], "/nix/store/test-domain.drv^*")

    def test_missing_command_becomes_build_error(self) -> None:
        with self.assertRaisesRegex(BuildError, "could not execute"):
            SubprocessRunner().run(["definitely-not-a-real-command"])


if __name__ == "__main__":
    unittest.main()
