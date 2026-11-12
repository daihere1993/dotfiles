#!/usr/bin/env python3
"""Exec an integration shell/command while holding the repository's kernel lock."""

import argparse
import os
import sys
from pathlib import Path

from integration_lock import integration_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command after -- is required")
    repo = Path(args.repo).resolve(strict=True)
    try:
        lock_context = integration_lock(repo)
        descriptor = lock_context.__enter__()
    except BlockingIOError:
        print(
            "Another integration session holds this repository lock.", file=sys.stderr
        )
        return 75
    os.chdir(repo)
    try:
        os.execvp(command[0], command)
    finally:
        lock_context.__exit__(None, None, None)


if __name__ == "__main__":
    sys.exit(main())
