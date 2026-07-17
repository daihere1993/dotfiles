from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .models import (
    ActivationPlan,
    ConflictResult,
    ConflictStatus,
    DeploymentManifest,
    Resource,
    ResourceDecision,
)


class ResourceDelta(StrEnum):
    CREATE = "create"
    CONTENT_UPDATE = "content_update"
    METADATA_UPDATE = "metadata_update"
    RETIRE = "retire"
    UNCHANGED = "unchanged"


class DomainAction(StrEnum):
    NOOP = "noop"
    INSTALL = "install"
    RECONCILE = "reconcile"
    SWITCH_CONTENT = "switch_content"
    SWITCH_METADATA = "switch_metadata"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PlannedResource:
    resource: Resource
    delta: ResourceDelta
    safety: ConflictResult


@dataclass(frozen=True)
class DomainPlan:
    domain: str
    action: DomainAction
    desired_store: Path
    active_store: Path | None
    desired_manifest: DeploymentManifest
    active_manifest: DeploymentManifest | None
    resources: tuple[PlannedResource, ...]
    reason: str

    @property
    def changes_state(self) -> bool:
        return self.action not in {DomainAction.NOOP, DomainAction.BLOCKED}


@dataclass(frozen=True)
class DeploymentPlan:
    domains: tuple[DomainPlan, ...]

    def for_domain(self, domain: str) -> DomainPlan:
        return next(item for item in self.domains if item.domain == domain)

    @property
    def changes_state(self) -> bool:
        return any(domain.changes_state for domain in self.domains)


def _content_identity(resource: Resource) -> tuple:
    # Home Manager links contain generation-specific Store paths. Their target and
    # content digest are the stable resource identity; Agent link targets are stable
    # profile-relative entry points and therefore remain part of the identity.
    stable_link = None if resource.owner == "home-manager" else resource.link_target
    return (
        resource.id,
        resource.owner,
        resource.kind,
        resource.target,
        resource.managed,
        stable_link,
        resource.sha256,
        resource.directory_sha256,
        resource.optional,
    )


def _metadata_identity(resource: Resource) -> tuple:
    return resource.sources


def _resource_deltas(
    desired: DeploymentManifest,
    active: DeploymentManifest | None,
) -> dict[str, ResourceDelta]:
    desired_by_id = {resource.id: resource for resource in desired.resources if resource.managed}
    active_by_id = (
        {resource.id: resource for resource in active.resources if resource.managed}
        if active
        else {}
    )
    deltas: dict[str, ResourceDelta] = {}
    for resource_id in sorted(set(desired_by_id) | set(active_by_id)):
        desired_resource = desired_by_id.get(resource_id)
        active_resource = active_by_id.get(resource_id)
        if desired_resource is None:
            deltas[resource_id] = ResourceDelta.RETIRE
        elif active_resource is None:
            deltas[resource_id] = ResourceDelta.CREATE
        elif _content_identity(desired_resource) != _content_identity(active_resource):
            deltas[resource_id] = ResourceDelta.CONTENT_UPDATE
        elif _metadata_identity(desired_resource) != _metadata_identity(active_resource):
            deltas[resource_id] = ResourceDelta.METADATA_UPDATE
        else:
            deltas[resource_id] = ResourceDelta.UNCHANGED
    return deltas


def _skills_metadata(manifest: DeploymentManifest | None) -> tuple[tuple, ...]:
    if manifest is None:
        return ()
    return tuple(
        (
            skill.canonical_id,
            skill.target_id,
            skill.bundle_path,
            skill.directory_sha256,
            skill.source_kind,
            skill.source_path,
            skill.source_id,
            skill.nar_hash,
            skill.rev,
        )
        for skill in manifest.skills
    )


def _same_store(left: Path | None, right: Path) -> bool:
    if left is None:
        return False
    return left.resolve(strict=False) == right.resolve(strict=False)


def plan_domain(
    domain: str,
    *,
    desired_store: Path,
    desired: DeploymentManifest,
    active_store: Path | None,
    active: DeploymentManifest | None,
    safety: list[ConflictResult],
    blocked: bool = False,
) -> DomainPlan:
    deltas = _resource_deltas(desired, active)
    safety_by_id = {result.resource.id: result for result in safety}
    resources = tuple(
        PlannedResource(result.resource, deltas[result.resource.id], result)
        for result in safety
    )
    hard_conflict = blocked or any(
        result.status == ConflictStatus.CONFLICT for result in safety
    )
    if hard_conflict:
        action = DomainAction.BLOCKED
        reason = "domain has unresolved conflicts"
    elif active is None or active_store is None:
        action = DomainAction.INSTALL
        reason = "domain is not deployed"
    else:
        content_changed = any(
            delta in {
                ResourceDelta.CREATE,
                ResourceDelta.CONTENT_UPDATE,
                ResourceDelta.RETIRE,
            }
            for delta in deltas.values()
        )
        metadata_changed = any(
            delta == ResourceDelta.METADATA_UPDATE for delta in deltas.values()
        ) or _skills_metadata(desired) != _skills_metadata(active)
        needs_reconcile = any(
            result.status
            in {
                ConflictStatus.ABSENT,
                ConflictStatus.ADOPTABLE_EMPTY,
                ConflictStatus.MIGRATABLE,
                ConflictStatus.OVERWRITABLE_CONFLICT,
                ConflictStatus.RETIRABLE_MANAGED,
            }
            for result in safety_by_id.values()
        )
        if domain == "system" and not _same_store(active_store, desired_store):
            action = DomainAction.SWITCH_CONTENT
            reason = "system closure changed"
        elif content_changed:
            action = DomainAction.SWITCH_CONTENT
            reason = "managed resource content changed"
        elif metadata_changed:
            action = DomainAction.SWITCH_METADATA
            reason = "manifest metadata changed"
        elif needs_reconcile:
            action = DomainAction.RECONCILE
            reason = "managed entries need repair"
        else:
            action = DomainAction.NOOP
            reason = "desired state is semantically unchanged"
    return DomainPlan(
        domain,
        action,
        desired_store,
        active_store,
        desired,
        active,
        resources,
        reason,
    )


def build_deployment_plan(domains: list[DomainPlan]) -> DeploymentPlan:
    return DeploymentPlan(tuple(domains))


def build_plan_changes(
    deployment: DeploymentPlan,
    activation_plans: dict[str, tuple[list[ConflictResult], ActivationPlan | None]],
    *,
    verbose: bool = False,
):
    from .apply_events import ChangeEntry, ChangeVerb

    entries: list[ChangeEntry] = []
    for domain in deployment.domains:
        _, activation = activation_plans.get(domain.domain, ([], None))
        actions = {
            action.resource.id: action
            for action in (activation.actions or ())
        } if activation is not None else {}
        for planned in domain.resources:
            result = planned.safety
            action = actions.get(planned.resource.id)
            if result.status == ConflictStatus.CONFLICT:
                verb = ChangeVerb.BLOCKED
                reason = "not managed by dotfiles"
            elif action is not None and action.decision == ResourceDecision.SKIP:
                verb = ChangeVerb.SKIP
                reason = "will be left unchanged"
            elif action is not None and action.decision == ResourceDecision.OVERWRITE:
                verb = ChangeVerb.UPDATE
                reason = "user-owned resource will be backed up and replaced"
            elif result.status == ConflictStatus.OVERWRITABLE_CONFLICT:
                verb = ChangeVerb.CONFLICT
                reason = "user-owned skill requires a decision"
            elif result.status == ConflictStatus.MIGRATABLE:
                verb = ChangeVerb.MIGRATE
                reason = "will migrate to ~/.ssh/config.local"
            elif result.status == ConflictStatus.ADOPTABLE_EMPTY:
                verb = ChangeVerb.ADOPT
                reason = "empty file will be adopted"
            elif planned.delta == ResourceDelta.RETIRE:
                verb = ChangeVerb.RETIRE
                reason = "retired managed resource will be removed"
            elif planned.delta == ResourceDelta.CREATE:
                verb = ChangeVerb.CREATE
                reason = "will be created"
            elif planned.delta == ResourceDelta.CONTENT_UPDATE:
                verb = ChangeVerb.UPDATE
                reason = "managed content changed"
            elif result.status == ConflictStatus.ABSENT:
                verb = ChangeVerb.CREATE
                reason = "missing managed entry will be restored"
            else:
                verb = ChangeVerb.OK
                reason = (
                    "metadata changed; content unchanged"
                    if planned.delta == ResourceDelta.METADATA_UPDATE
                    else "unchanged; carried forward"
                )
            if verbose or verb != ChangeVerb.OK:
                entries.append(
                    ChangeEntry(
                        domain.domain,
                        verb,
                        planned.resource.target,
                        reason,
                        planned.resource.id,
                    )
                )
    return entries


def serialize_domain_actions(deployment: DeploymentPlan) -> list[dict[str, str]]:
    return [
        {
            "domain": domain.domain,
            "action": domain.action.value,
            "reason": domain.reason,
        }
        for domain in deployment.domains
    ]
