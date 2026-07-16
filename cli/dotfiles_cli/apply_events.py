from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .models import ActivationPlan, ConflictResult, ConflictStatus, ResourceAction, ResourceDecision


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


STATUS_TO_VERB: dict[ConflictStatus, ChangeVerb] = {
    ConflictStatus.ABSENT: ChangeVerb.CREATE,
    ConflictStatus.ADOPTABLE_EMPTY: ChangeVerb.ADOPT,
    ConflictStatus.MIGRATABLE: ChangeVerb.MIGRATE,
    ConflictStatus.REPLACEABLE_MANAGED: ChangeVerb.UPDATE,
    ConflictStatus.RETIRABLE_MANAGED: ChangeVerb.RETIRE,
    ConflictStatus.OVERWRITABLE_CONFLICT: ChangeVerb.CONFLICT,
    ConflictStatus.CONFLICT: ChangeVerb.BLOCKED,
    ConflictStatus.CURRENTLY_MANAGED: ChangeVerb.OK,
    ConflictStatus.RETIRED_ABSENT: ChangeVerb.OK,
}

QUIET_CHANGE_VERBS = {ChangeVerb.OK}


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


def verb_for_result(result: ConflictResult, action: ResourceAction | None = None) -> ChangeVerb:
    if action is not None:
        if action.decision == ResourceDecision.SKIP:
            if result.status == ConflictStatus.OVERWRITABLE_CONFLICT:
                return ChangeVerb.SKIP
            return ChangeVerb.BLOCKED
        if action.decision == ResourceDecision.OVERWRITE:
            return ChangeVerb.UPDATE
        if action.decision == ResourceDecision.RETIRE:
            return ChangeVerb.RETIRE
        if action.decision in {ResourceDecision.APPLY, ResourceDecision.RESTORE_BACKUP}:
            return STATUS_TO_VERB.get(result.status, ChangeVerb.UPDATE)
    return STATUS_TO_VERB.get(result.status, ChangeVerb.BLOCKED)


def build_changes_plan(
    *,
    domains: list,
    plans: dict[str, tuple[list[ConflictResult], ActivationPlan | None]],
    verbose: bool = False,
) -> list[ChangeEntry]:
    from .present import humanize_reason, parse_preflight_conflicts

    entries: list[ChangeEntry] = []
    for domain_preflight in domains:
        domain = domain_preflight.domain
        if domain_preflight.error is not None:
            for conflict in parse_preflight_conflicts(domain_preflight.error.message):
                entries.append(
                    ChangeEntry(
                        domain=domain,
                        verb=ChangeVerb.BLOCKED,
                        target=conflict.target,
                        reason=conflict.reason,
                    )
                )
            continue
        results, plan = plans.get(domain, ([], None))
        actions_by_id: dict[str, ResourceAction] = {}
        if plan is not None and plan.actions is not None:
            actions_by_id = {action.resource.id: action for action in plan.actions}
        for result in results:
            action = actions_by_id.get(result.resource.id)
            verb = verb_for_result(result, action)
            if not verbose and verb in QUIET_CHANGE_VERBS:
                continue
            entries.append(
                ChangeEntry(
                    domain=domain,
                    verb=verb,
                    target=result.resource.target,
                    reason=humanize_reason(result.reason),
                    resource_id=result.resource.id,
                )
            )
    return entries


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
