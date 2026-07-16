from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

PLATFORMS = ("codex", "claude", "cursor")
DOMAINS = ("system", *PLATFORMS)
ResourceKind = Literal["file-link", "directory-link", "local-prerequisite"]


class DiagnosticStatus(StrEnum):
    HEALTHY = "HEALTHY"
    NOT_DEPLOYED = "NOT_DEPLOYED"
    STAGED_NOT_DEPLOYED = "STAGED_NOT_DEPLOYED"
    MISSING = "MISSING"
    DRIFTED = "DRIFTED"
    LOCAL_PRESENT = "LOCAL_PRESENT"
    LOCAL_ABSENT_OPTIONAL = "LOCAL_ABSENT_OPTIONAL"
    LOCAL_UNSAFE_PERMISSIONS = "LOCAL_UNSAFE_PERMISSIONS"
    UNSUPPORTED_OPTIONAL = "UNSUPPORTED_OPTIONAL"
    SKIPPED_CONFLICT = "SKIPPED_CONFLICT"
    BACKUP_MISSING = "BACKUP_MISSING"


class ConflictStatus(StrEnum):
    ABSENT = "ABSENT"
    ADOPTABLE_EMPTY = "ADOPTABLE_EMPTY"
    MIGRATABLE = "MIGRATABLE"
    CURRENTLY_MANAGED = "CURRENTLY_MANAGED"
    REPLACEABLE_MANAGED = "REPLACEABLE_MANAGED"
    RETIRED_ABSENT = "RETIRED_ABSENT"
    RETIRABLE_MANAGED = "RETIRABLE_MANAGED"
    OVERWRITABLE_CONFLICT = "OVERWRITABLE_CONFLICT"
    CONFLICT = "CONFLICT"


class DeploymentState(StrEnum):
    DEPLOYED = "DEPLOYED"
    PARTIALLY_DEPLOYED = "PARTIALLY_DEPLOYED"
    STAGED_NOT_DEPLOYED = "STAGED_NOT_DEPLOYED"
    NOT_DEPLOYED = "NOT_DEPLOYED"


class ResourceDecision(StrEnum):
    APPLY = "APPLY"
    OVERWRITE = "OVERWRITE"
    SKIP = "SKIP"
    RETIRE = "RETIRE"
    RESTORE_BACKUP = "RESTORE_BACKUP"


class ReceiptResourceState(StrEnum):
    DEPLOYED = "DEPLOYED"
    SKIPPED_CONFLICT = "SKIPPED_CONFLICT"


@dataclass(frozen=True)
class MachineIdentity:
    username: str
    home_directory: str
    nix_system: str = "aarch64-darwin"
    schema_version: int = 1

    @property
    def home(self) -> Path:
        return Path(self.home_directory)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "username": self.username,
            "homeDirectory": self.home_directory,
            "nixSystem": self.nix_system,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MachineIdentity:
        return cls(
            schema_version=value.get("schemaVersion"),
            username=value.get("username"),
            home_directory=value.get("homeDirectory"),
            nix_system=value.get("nixSystem"),
        )


@dataclass(frozen=True)
class Resource:
    id: str
    owner: str
    kind: ResourceKind
    target: str
    sources: tuple[str, ...] = ()
    managed: bool = True
    link_target: str | None = None
    store_path: str | None = None
    sha256: str | None = None
    directory_sha256: str | None = None
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "owner": self.owner,
            "kind": self.kind,
            "target": self.target,
            "sources": list(self.sources),
        }
        mappings = {
            "managed": self.managed,
            "linkTarget": self.link_target,
            "storePath": self.store_path,
            "sha256": self.sha256,
            "directorySha256": self.directory_sha256,
            "optional": self.optional,
        }
        for key, value in mappings.items():
            if value is None:
                continue
            if (key == "managed" and value is True) or (key == "optional" and value is False):
                continue
            result[key] = value
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Resource:
        return cls(
            id=value["id"],
            owner=value["owner"],
            kind=value["kind"],
            target=value["target"],
            sources=tuple(value.get("sources", [])),
            managed=value.get("managed", True),
            link_target=value.get("linkTarget"),
            store_path=value.get("storePath"),
            sha256=value.get("sha256"),
            directory_sha256=value.get("directorySha256"),
            optional=value.get("optional", False),
        )


@dataclass(frozen=True)
class SkillInventoryEntry:
    canonical_id: str
    target_id: str
    bundle_path: str
    directory_sha256: str
    source_kind: Literal["local", "external"]
    source_path: str
    source_id: str | None = None
    nar_hash: str | None = None
    rev: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "canonicalId": self.canonical_id,
            "targetId": self.target_id,
            "bundlePath": self.bundle_path,
            "directorySha256": self.directory_sha256,
            "sourceKind": self.source_kind,
            "sourcePath": self.source_path,
        }
        for key, value in (
            ("sourceId", self.source_id),
            ("narHash", self.nar_hash),
            ("rev", self.rev),
        ):
            if value is not None:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SkillInventoryEntry:
        return cls(
            canonical_id=value["canonicalId"],
            target_id=value["targetId"],
            bundle_path=value["bundlePath"],
            directory_sha256=value["directorySha256"],
            source_kind=value["sourceKind"],
            source_path=value["sourcePath"],
            source_id=value.get("sourceId"),
            nar_hash=value.get("narHash"),
            rev=value.get("rev"),
        )


@dataclass(frozen=True)
class DeploymentManifest:
    identity: MachineIdentity
    deployment_domain: str
    resources: tuple[Resource, ...]
    skills: tuple[SkillInventoryEntry, ...] = ()
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "username": self.identity.username,
            "homeDirectory": self.identity.home_directory,
            "nixSystem": self.identity.nix_system,
            "deploymentDomain": self.deployment_domain,
            "resources": [resource.to_dict() for resource in self.resources],
            "skills": [skill.to_dict() for skill in self.skills],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DeploymentManifest:
        identity = MachineIdentity(
            schema_version=value["schemaVersion"],
            username=value["username"],
            home_directory=value["homeDirectory"],
            nix_system=value["nixSystem"],
        )
        return cls(
            schema_version=value["schemaVersion"],
            identity=identity,
            deployment_domain=value["deploymentDomain"],
            resources=tuple(Resource.from_dict(item) for item in value.get("resources", [])),
            skills=tuple(SkillInventoryEntry.from_dict(item) for item in value.get("skills", [])),
        )


@dataclass(frozen=True)
class Diagnostic:
    domain: str
    status: DiagnosticStatus
    reason: str
    resource_id: str | None = None
    target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return {key: item for key, item in value.items() if item is not None}


@dataclass(frozen=True)
class ConflictResult:
    status: ConflictStatus
    resource: Resource
    reason: str


@dataclass(frozen=True)
class ResourceAction:
    resource: Resource
    decision: ResourceDecision
    conflict_status: ConflictStatus
    reason: str
    backup_ref: str | None = None


@dataclass(frozen=True)
class ReceiptResource:
    id: str
    target: str
    state: ReceiptResourceState
    backup_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"id": self.id, "target": self.target, "state": self.state.value}
        if self.backup_ref is not None:
            result["backupRef"] = self.backup_ref
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ReceiptResource:
        return cls(
            id=value["id"],
            target=value["target"],
            state=ReceiptResourceState(value["state"]),
            backup_ref=value.get("backupRef"),
        )


@dataclass(frozen=True)
class ActivationReceipt:
    platform: str
    identity: MachineIdentity
    bundle_store_path: str
    resources: tuple[ReceiptResource, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "platform": self.platform,
            "username": self.identity.username,
            "homeDirectory": self.identity.home_directory,
            "nixSystem": self.identity.nix_system,
            "bundleStorePath": self.bundle_store_path,
            "resources": [resource.to_dict() for resource in self.resources],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ActivationReceipt:
        return cls(
            schema_version=value["schemaVersion"],
            platform=value["platform"],
            identity=MachineIdentity(value["username"], value["homeDirectory"], value["nixSystem"]),
            bundle_store_path=value["bundleStorePath"],
            resources=tuple(ReceiptResource.from_dict(item) for item in value["resources"]),
        )


@dataclass(frozen=True)
class ActivationPlan:
    platform: str
    identity: MachineIdentity
    profile_path: str
    new_store_path: str
    desired_manifest: DeploymentManifest
    old_store_path: str | None = None
    active_manifest: DeploymentManifest | None = None
    actions: tuple[ResourceAction, ...] | None = None
    old_receipt: ActivationReceipt | None = None
    schema_version: int = 2


@dataclass(frozen=True)
class DomainResult:
    domain: str
    status: str
    message: str
