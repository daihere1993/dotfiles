from __future__ import annotations


class DotfilesError(Exception):
    """Expected failure with a stable CLI exit code."""

    exit_code = 2

    def __init__(
        self,
        message: str,
        *,
        next_step: str | None = None,
        modified_state: bool | None = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.next_step = next_step
        self.modified_state = modified_state


class ValidationError(DotfilesError):
    exit_code = 2


class ConflictError(DotfilesError):
    exit_code = 3


class BuildError(DotfilesError):
    exit_code = 4


class ActivationError(DotfilesError):
    exit_code = 5

    def __init__(
        self,
        message: str,
        *,
        next_step: str | None = None,
        modified_state: bool | None = None,
    ) -> None:
        super().__init__(message, next_step=next_step, modified_state=modified_state)


class DoctorError(DotfilesError):
    exit_code = 6
