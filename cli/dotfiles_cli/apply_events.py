from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ApplyPhase(StrEnum):
    PLAN = "plan"
    BUILD = "build"
    PREFLIGHT = "preflight"
    CHANGES = "changes"
    RESOLVE = "resolve"
    CONFIRM = "confirm"
    APPLY = "apply"
    VERIFY = "verify"
    RESULT = "result"


class ChangeVerb(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    MIGRATE = "migrate"
    ADOPT = "adopt"
    RETIRE = "retire"
    SKIP = "skip"
    CONFLICT = "conflict"
    OK = "ok"
    BLOCKED = "blocked"


class ActivationMilestone(StrEnum):
    MIGRATE_SSH = "migrate_ssh"
    BACKUP_OVERWRITES = "backup_overwrites"
    SWITCH_PROFILE = "switch_profile"
    RUN_ACTIVATE_SCRIPT = "run_activate_script"
    INSTALL_SYMLINKS = "install_symlinks"
    VERIFY_RESOURCES = "verify_resources"
    VERIFY_CURRENT_SYSTEM = "verify_current_system"
    WRITE_RECEIPT = "write_receipt"
    DOMAIN_COMPLETE = "domain_complete"
    DOMAIN_SKIPPED = "domain_skipped"


@dataclass(frozen=True)
class ChangeEntry:
    domain: str
    verb: ChangeVerb
    target: str
    reason: str
    resource_id: str | None = None


@dataclass(frozen=True)
class ApplyEvent:
    phase: ApplyPhase
    kind: str
    payload: dict[str, Any]
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "kind": self.kind,
            "timestampMs": self.timestamp_ms,
            **self.payload,
        }


def change_count(entries: list[ChangeEntry]) -> int:
    return sum(
        1
        for entry in entries
        if entry.verb
        not in {
            ChangeVerb.OK,
            ChangeVerb.SKIP,
            ChangeVerb.BLOCKED,
            ChangeVerb.CONFLICT,
        }
    )


def domains_with_changes(entries: list[ChangeEntry]) -> set[str]:
    return {
        entry.domain
        for entry in entries
        if entry.verb
        not in {ChangeVerb.OK, ChangeVerb.BLOCKED, ChangeVerb.CONFLICT, ChangeVerb.SKIP}
    }
