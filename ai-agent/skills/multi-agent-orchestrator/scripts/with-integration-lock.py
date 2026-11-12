#!/usr/bin/env python3
"""Exec an integration shell/command while holding the repository's kernel lock."""

import argparse
import fcntl
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command after -- is required")
    repo = Path(args.repo).resolve(strict=True)
    common = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=repo,
        text=True,
    ).strip()
    lock_path = Path(common).resolve(strict=True) / "agent-integration.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        print(
            "Another integration session holds this repository lock.", file=sys.stderr
        )
        return 75
    # The persistent shell retains the descriptor, including while commands run.
    os.set_inheritable(descriptor, True)
    os.chdir(repo)
    try:
        os.execvp(command[0], command)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    sys.exit(main())
