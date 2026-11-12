"""Shared kernel-lock primitive for multi-agent integration tools."""

from __future__ import annotations

import fcntl
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def integration_lock(repo: Path) -> Iterator[int]:
    """Hold one nonblocking POSIX lock for the repository's canonical Git dir."""

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
        raise BlockingIOError(lock_path) from None
    try:
        # The lock is held by this open file description until the context exits.
        # Manual shell exec needs the descriptor inherited by its child.
        os.set_inheritable(descriptor, True)
        yield descriptor
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
