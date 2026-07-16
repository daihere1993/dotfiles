from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .jsonutil import canonical_json


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_path(value: bytes, context: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(f"{context} is not valid UTF-8") from error


def directory_entries(root: Path) -> list[dict[str, Any]]:
    if root.is_symlink() or not root.is_dir():
        raise ValidationError(f"directory hash root must be a real directory: {root}")
    root_real = root.resolve(strict=True)
    entries: list[dict[str, Any]] = []

    def visit(directory: Path, relative: Path) -> None:
        names = os.listdir(os.fsencode(directory))
        for raw_name in names:
            name = _text_path(raw_name, f"path below {root}")
            child = directory / name
            child_relative = relative / name
            posix = child_relative.as_posix()
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                raw_target = os.readlink(os.fsencode(child))
                target = _text_path(raw_target, f"symlink target at {child}")
                resolved = (child.parent / target).resolve(strict=False)
                try:
                    resolved.relative_to(root_real)
                except ValueError as error:
                    raise ValidationError(
                        f"symlink escapes directory: {child} -> {target}"
                    ) from error
                entries.append({"path": posix, "target": target, "type": "symlink"})
            elif stat.S_ISDIR(info.st_mode):
                entries.append({"path": posix, "type": "directory"})
                visit(child, child_relative)
            elif stat.S_ISREG(info.st_mode):
                entries.append(
                    {
                        "executable": bool(info.st_mode & 0o111),
                        "path": posix,
                        "sha256": file_sha256(child),
                        "type": "file",
                    }
                )
            else:
                raise ValidationError(f"unsupported filesystem entry in skill: {child}")

    visit(root, Path())
    entries.sort(key=lambda entry: entry["path"].encode("utf-8"))
    return entries


def directory_sha256(root: Path) -> str:
    return hashlib.sha256(canonical_json(directory_entries(root))).hexdigest()
