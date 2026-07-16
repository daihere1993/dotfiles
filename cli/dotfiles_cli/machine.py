from __future__ import annotations

import os
import platform
import pwd
import re
import stat
import subprocess
import tempfile
from pathlib import Path

from .errors import ValidationError
from .jsonutil import canonical_json, load_json
from .models import MachineIdentity

USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def default_state_path(identity: MachineIdentity | None = None) -> Path:
    home = identity.home if identity is not None else Path(pwd.getpwuid(os.getuid()).pw_dir)
    return home / ".local/state/dotfiles/machine.json"


def discover_identity() -> MachineIdentity:
    if os.geteuid() == 0:
        raise ValidationError(
            "dot init refuses to run as root", next_step="Run dot init as the login user."
        )
    uid = os.getuid()
    account = pwd.getpwuid(uid)
    username = account.pw_name
    home = account.pw_dir
    id_result = subprocess.run(["id", "-un"], check=False, capture_output=True, text=True)
    if id_result.returncode or id_result.stdout.strip() != username:
        raise ValidationError("id -un does not match the system user directory record")
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValidationError(f"unsupported local account name: {username!r}")
    if not Path(home).is_absolute():
        raise ValidationError(f"directory services returned a non-absolute home: {home!r}")
    machine = platform.machine()
    system = platform.system()
    if system != "Darwin" or machine != "arm64":
        raise ValidationError(
            f"unsupported host: {system} {machine}; expected Apple Silicon macOS",
            next_step="Run dot on an Apple Silicon Mac.",
        )
    return MachineIdentity(username=username, home_directory=home)


def validate_identity(identity: MachineIdentity) -> None:
    if identity.schema_version != 1:
        raise ValidationError(f"unsupported machine identity schema: {identity.schema_version!r}")
    if not isinstance(identity.username, str) or not USERNAME_PATTERN.fullmatch(identity.username):
        raise ValidationError(f"invalid username: {identity.username!r}")
    if (
        not isinstance(identity.home_directory, str)
        or not Path(identity.home_directory).is_absolute()
    ):
        raise ValidationError(f"invalid home directory: {identity.home_directory!r}")
    if identity.nix_system != "aarch64-darwin":
        raise ValidationError(f"unsupported Nix system: {identity.nix_system!r}")


def _validate_path_security(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise ValidationError(
            f"machine state does not exist: {path}", next_step="Run dot init."
        ) from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValidationError(f"machine state must be a non-symlink regular file: {path}")
    if info.st_uid != os.getuid():
        raise ValidationError(f"machine state is not owned by uid {os.getuid()}: {path}")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise ValidationError(f"machine state must have mode 0600: {path}")
    directory_info = path.parent.lstat()
    if stat.S_ISLNK(directory_info.st_mode) or not stat.S_ISDIR(directory_info.st_mode):
        raise ValidationError(f"machine state directory must be a real directory: {path.parent}")
    if directory_info.st_uid != os.getuid() or stat.S_IMODE(directory_info.st_mode) != 0o700:
        raise ValidationError(
            f"machine state directory must be user-owned with mode 0700: {path.parent}"
        )


def read_identity(path: Path | None = None) -> MachineIdentity:
    state_path = path or default_state_path()
    _validate_path_security(state_path)
    try:
        value = load_json(state_path)
        identity = MachineIdentity.from_dict(value)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValidationError(f"invalid machine state: {state_path}: {error}") from error
    validate_identity(identity)
    return identity


def write_identity(identity: MachineIdentity, path: Path | None = None) -> bool:
    validate_identity(identity)
    state_path = path or default_state_path(identity)
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_info = state_path.parent.lstat()
    if directory_info.st_uid != os.getuid() or stat.S_IMODE(directory_info.st_mode) != 0o700:
        raise ValidationError(f"unsafe machine state directory: {state_path.parent}")
    if state_path.exists() or state_path.is_symlink():
        existing = read_identity(state_path)
        if existing == identity:
            return False
        raise ValidationError(
            f"machine identity differs from existing state: {state_path}",
            next_step="Do not replace machine.json in place; review the account migration first.",
        )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".machine.", dir=state_path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(canonical_json(identity.to_dict()))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, state_path)
        except FileExistsError as error:
            raise ValidationError(
                f"machine state appeared during initialization: {state_path}"
            ) from error
        temporary.unlink()
        directory_fd = os.open(state_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return True
