from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .apply_events import ChangeEntry, ChangeVerb, change_count, domains_with_changes
from .errors import ConflictError, DotfilesError
from .models import (
    ConflictResult,
    ConflictStatus,
    DeploymentManifest,
    Diagnostic,
    DiagnosticStatus,
    DomainResult,
    MachineIdentity,
    PLATFORMS,
)

ATTENTION_STATUSES = {ConflictStatus.CONFLICT, ConflictStatus.OVERWRITABLE_CONFLICT}
UPDATE_STATUSES = {
    ConflictStatus.ABSENT,
    ConflictStatus.ADOPTABLE_EMPTY,
    ConflictStatus.MIGRATABLE,
    ConflictStatus.REPLACEABLE_MANAGED,
}
QUIET_OK_STATUSES = {
    ConflictStatus.CURRENTLY_MANAGED,
    ConflictStatus.RETIRED_ABSENT,
    ConflictStatus.RETIRABLE_MANAGED,
}

REASON_LABELS = {
    "existing target cannot be proven to belong to the active or desired generation": (
        "not managed by dotfiles"
    ),
    "existing user-owned skill can be backed up and overwritten": "user-owned skill (can overwrite)",
    "target matches desired manifest": "already up to date",
    "target matches the active generation": "will update to new generation",
    "desired target is absent": "will be created",
    "empty user-owned rules file can be safely adopted": "empty file will be adopted",
    "existing SSH config will migrate to config.local": "will migrate to ~/.ssh/config.local",
    "retired target is already absent": "retired target already absent",
    "retired target matches the active generation": "retired target will be removed",
}

STATUS_LABELS = {
    ConflictStatus.ABSENT: "create",
    ConflictStatus.ADOPTABLE_EMPTY: "adopt",
    ConflictStatus.MIGRATABLE: "migrate",
    ConflictStatus.CURRENTLY_MANAGED: "ok",
    ConflictStatus.REPLACEABLE_MANAGED: "update",
    ConflictStatus.RETIRED_ABSENT: "retired",
    ConflictStatus.RETIRABLE_MANAGED: "retire",
    ConflictStatus.OVERWRITABLE_CONFLICT: "conflict",
    ConflictStatus.CONFLICT: "blocked",
}

DIAGNOSTIC_UNHEALTHY = {
    DiagnosticStatus.MISSING,
    DiagnosticStatus.DRIFTED,
    DiagnosticStatus.LOCAL_UNSAFE_PERMISSIONS,
    DiagnosticStatus.SKIPPED_CONFLICT,
    DiagnosticStatus.BACKUP_MISSING,
}
DIAGNOSTIC_INFO = {
    DiagnosticStatus.UNSUPPORTED_OPTIONAL,
    DiagnosticStatus.NOT_DEPLOYED,
    DiagnosticStatus.STAGED_NOT_DEPLOYED,
    DiagnosticStatus.LOCAL_ABSENT_OPTIONAL,
    DiagnosticStatus.LOCAL_PRESENT,
}

DIAGNOSTIC_REASON_LABELS = {
    "managed target matches the active manifest": "matches active manifest",
    "managed target is missing": "target is missing",
    "managed target differs from the active manifest": "differs from active manifest",
    "resource was skipped because a user-owned target conflicts": "skipped due to user-owned conflict",
    "managed resource backup is missing or incomplete": "backup is missing or incomplete",
    "optional local file is absent": "optional local file is absent",
    "optional local file is present and safe": "optional local file is present",
    "local file must be a user-owned regular file and not group/other writable": (
        "local file has unsafe permissions"
    ),
    "no active manifest": "not deployed yet",
    "profile exists without a healthy managed entry": "profile exists but is not healthy",
    "Cursor global rules have no supported filesystem interface": (
        "global rules not supported via filesystem"
    ),
}


@dataclass(frozen=True)
class ParsedConflict:
    target: str
    reason: str


@dataclass(frozen=True)
class DomainPreflight:
    domain: str
    store: Path
    resource_count: int
    results: tuple[ConflictResult, ...]
    error: ConflictError | None = None


class Style:
    def __init__(self, *, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self.enabled = enabled

    def _wrap(self, text: str, code: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self._wrap(text, "1")

    def dim(self, text: str) -> str:
        return self._wrap(text, "2")

    def green(self, text: str) -> str:
        return self._wrap(text, "32")

    def yellow(self, text: str) -> str:
        return self._wrap(text, "33")

    def red(self, text: str) -> str:
        return self._wrap(text, "31")

    def cyan(self, text: str) -> str:
        return self._wrap(text, "36")


def shorten_user_path(path: str | Path, home: Path) -> str:
    candidate = Path(path)
    try:
        relative = candidate.relative_to(home)
        if str(relative) == ".":
            return "~"
        return f"~/{relative}"
    except ValueError:
        return str(candidate)


def shorten_store_path(store: str | Path, *, max_len: int = 40) -> str:
    name = Path(store).name
    label = name.split("-", 1)[1] if "-" in name else name
    if len(label) <= max_len:
        return label
    return f"{label[: max_len - 1]}…"


def humanize_reason(reason: str) -> str:
    return REASON_LABELS.get(reason, reason)


def resource_status_label(status: ConflictStatus) -> str:
    return STATUS_LABELS[status]


def parse_preflight_conflicts(message: str) -> list[ParsedConflict]:
    conflicts: list[ParsedConflict] = []
    for line in message.strip().splitlines():
        if ": " not in line or line.startswith("platform preflight"):
            continue
        target, reason = line.split(": ", 1)
        conflicts.append(ParsedConflict(target=target, reason=humanize_reason(reason)))
    return conflicts


def _domain_blocked(domain: DomainPreflight) -> bool:
    if domain.error is not None:
        return True
    return any(result.status in ATTENTION_STATUSES for result in domain.results)


def _domain_update_count(domain: DomainPreflight) -> int:
    return sum(1 for result in domain.results if result.status in UPDATE_STATUSES)


def _ready_domains(domains: list[DomainPreflight]) -> list[str]:
    return [domain.domain for domain in domains if not _domain_blocked(domain)]


def _blocked_domains(domains: list[DomainPreflight]) -> list[str]:
    return [domain.domain for domain in domains if _domain_blocked(domain)]


def _section_title(style: Style, title: str) -> str:
    underline = "─" * max(8, 52 - len(title))
    return style.bold(f"{title}\n{underline}")


def _status_color(style: Style, status: ConflictStatus) -> str:
    label = resource_status_label(status)
    if status in ATTENTION_STATUSES:
        return style.yellow(label) if status == ConflictStatus.OVERWRITABLE_CONFLICT else style.red(label)
    if status in UPDATE_STATUSES:
        return style.cyan(label)
    if status == ConflictStatus.CURRENTLY_MANAGED:
        return style.green(label)
    return style.dim(label)


def format_conflict_prompt(
    *,
    target: str,
    home: Path,
    existing_kind: str,
    desired: str,
    backup_hint: str,
    style: Style | None = None,
) -> str:
    style = style or Style()
    lines = [
        "",
        style.bold(f"Conflict  {shorten_user_path(target, home)}"),
        f"  Existing  {existing_kind}",
        f"  Desired   {desired}",
        f"  Backup    {backup_hint}",
        "",
        "  [o] Overwrite   [s] Skip   [a] Overwrite all   [k] Skip all",
        "",
    ]
    return "\n".join(lines)


def build_apply_check_report(
    *,
    identity: MachineIdentity,
    stores: dict[str, Path],
    manifests: dict[str, DeploymentManifest],
    plans: dict[str, tuple[list[ConflictResult], object]],
    preflight_errors: dict[str, ConflictError],
) -> list[DomainPreflight]:
    domain_order = [domain for domain in ("system", *PLATFORMS) if domain in stores]
    domains: list[DomainPreflight] = []
    for domain in domain_order:
        results, _plan = plans.get(domain, ([], None))
        domains.append(
            DomainPreflight(
                domain=domain,
                store=stores[domain],
                resource_count=len(manifests[domain].resources),
                results=tuple(results),
                error=preflight_errors.get(domain),
            )
        )
    return domains


def apply_check_has_conflicts(domains: list[DomainPreflight]) -> bool:
    return bool(_blocked_domains(domains))


def render_apply_check_text(
    domains: list[DomainPreflight],
    *,
    identity: MachineIdentity,
    verbose: bool = False,
    style: Style | None = None,
) -> str:
    style = style or Style()
    home = identity.home
    lines: list[str] = []

    lines.append(_section_title(style, "Build"))
    for domain in domains:
        store_label = shorten_store_path(domain.store)
        lines.append(
            f"  {domain.domain:<7} {style.dim(store_label)}  ({domain.resource_count} resources)"
        )

    blocked_lines: list[str] = []
    for domain in domains:
        if domain.error is not None:
            blocked_lines.append(style.bold(f"  {domain.domain}"))
            for conflict in parse_preflight_conflicts(domain.error.message):
                blocked_lines.append(
                    f"    {style.red('✗')} {shorten_user_path(conflict.target, home)}"
                )
                blocked_lines.append(f"      {style.dim(conflict.reason)}")
            continue
        attention = [result for result in domain.results if result.status in ATTENTION_STATUSES]
        if not attention:
            continue
        blocked_lines.append(style.bold(f"  {domain.domain}"))
        for result in attention:
            marker = style.yellow("!") if result.status == ConflictStatus.OVERWRITABLE_CONFLICT else style.red("✗")
            blocked_lines.append(
                f"    {marker} {shorten_user_path(result.resource.target, home)}"
            )
            blocked_lines.append(f"      {style.dim(humanize_reason(result.reason))}")

    if blocked_lines:
        lines.append("")
        lines.append(_section_title(style, "Blocked"))
        lines.extend(blocked_lines)

    ready = _ready_domains(domains)
    if ready:
        lines.append("")
        lines.append(_section_title(style, "Ready"))
        update_total = sum(_domain_update_count(domain) for domain in domains if domain.domain in ready)
        ready_label = ", ".join(ready)
        if update_total:
            lines.append(
                f"  {style.green('✓')} {ready_label} — {update_total} resource(s) will update on apply"
            )
        else:
            lines.append(f"  {style.green('✓')} {ready_label} — no changes needed")

    if verbose:
        lines.append("")
        lines.append(_section_title(style, "Resources"))
        for domain in domains:
            if domain.error is not None or not domain.results:
                continue
            lines.append(style.bold(f"  {domain.domain}"))
            for result in domain.results:
                label = _status_color(style, result.status)
                target = shorten_user_path(result.resource.target, home)
                lines.append(f"    {label:<16} {target}")
                lines.append(f"      {style.dim(humanize_reason(result.reason))}")

    blocked = _blocked_domains(domains)
    lines.append("")
    if blocked:
        lines.append(_section_title(style, "Next step"))
        lines.append("  Back up or migrate the conflicting paths, then run:")
        lines.append(f"  {style.cyan('dot apply')}")
        lines.append("")
        lines.append(style.red(f"Result: conflicts found (exit 3)"))
    else:
        lines.append(style.green("Result: ready to apply (exit 0)"))
    if not verbose and any(domain.results for domain in domains):
        lines.append(style.dim("Run with --verbose to see every resource."))

    return "\n".join(lines)


def _change_verb_color(style: Style, verb: ChangeVerb) -> str:
    label = verb.value
    if verb in {ChangeVerb.BLOCKED, ChangeVerb.CONFLICT}:
        return style.red(label)
    if verb in {ChangeVerb.SKIP, ChangeVerb.CONFLICT}:
        return style.yellow(label)
    if verb == ChangeVerb.OK:
        return style.dim(label)
    if verb in {ChangeVerb.CREATE, ChangeVerb.UPDATE, ChangeVerb.MIGRATE, ChangeVerb.ADOPT}:
        return style.cyan(label)
    return label


def render_changes_plan(
    entries: list[ChangeEntry],
    *,
    identity: MachineIdentity,
    domain_order: list[str] | None = None,
    verbose: bool = False,
    style: Style | None = None,
) -> str:
    style = style or Style()
    home = identity.home
    order = domain_order or [domain for domain in ("system", *PLATFORMS)]
    by_domain: dict[str, list[ChangeEntry]] = {domain: [] for domain in order}
    for entry in entries:
        by_domain.setdefault(entry.domain, []).append(entry)

    lines: list[str] = [_section_title(style, "Changes")]
    any_visible = False
    for domain in order:
        domain_entries = by_domain.get(domain, [])
        visible = [
            entry
            for entry in domain_entries
            if verbose or entry.verb not in {ChangeVerb.OK}
        ]
        if not visible:
            if domain in {entry.domain for entry in entries} or not domain_entries:
                has_changes = any(
                    entry.verb not in {ChangeVerb.OK, ChangeVerb.BLOCKED, ChangeVerb.CONFLICT}
                    for entry in domain_entries
                )
                if not domain_entries or not has_changes:
                    lines.append(f"  {domain:<7} {style.dim('no changes')}")
            continue
        any_visible = True
        lines.append(style.bold(f"  {domain}"))
        for entry in visible:
            verb = _change_verb_color(style, entry.verb)
            target = shorten_user_path(entry.target, home)
            lines.append(f"    {verb:<10} {target}")
            if entry.reason and entry.verb not in {ChangeVerb.OK}:
                lines.append(f"             {style.dim(entry.reason)}")

    if not any_visible and not lines[-1].endswith("no changes"):
        lines.append(f"  {style.dim('no changes needed')}")
    return "\n".join(lines)


def render_changes_summary(
    entries: list[ChangeEntry],
    *,
    style: Style | None = None,
) -> str:
    style = style or Style()
    count = change_count(entries)
    domains = domains_with_changes(entries)
    blocked = any(entry.verb == ChangeVerb.BLOCKED for entry in entries)
    conflicts = any(entry.verb == ChangeVerb.CONFLICT for entry in entries)
    if blocked:
        return style.red("Blocked domains must be resolved before apply.")
    if conflicts:
        return style.yellow("Resolve conflicts above before apply.")
    if count:
        domain_count = len(domains)
        noun = "resource" if count == 1 else "resources"
        domain_noun = "domain" if domain_count == 1 else "domains"
        return (
            f"{count} {noun} will change across {domain_count} {domain_noun}"
        )
    return style.green("no changes needed")


def render_apply_check_json(
    domains: list[DomainPreflight],
    *,
    identity: MachineIdentity,
    changes: list[ChangeEntry] | None = None,
) -> str:
    home = identity.home
    blocked: dict[str, object] = {}
    resources: dict[str, list[dict[str, str]]] = {}
    builds = {
        domain.domain: {
            "store": str(domain.store),
            "storeLabel": shorten_store_path(domain.store),
            "resourceCount": domain.resource_count,
        }
        for domain in domains
    }

    for domain in domains:
        if domain.error is not None:
            blocked[domain.domain] = {
                "kind": "domain",
                "conflicts": [
                    {
                        "target": shorten_user_path(item.target, home),
                        "reason": item.reason,
                    }
                    for item in parse_preflight_conflicts(domain.error.message)
                ],
            }
            continue
        entries = [
            {
                "target": shorten_user_path(result.resource.target, home),
                "status": resource_status_label(result.status),
                "reason": humanize_reason(result.reason),
            }
            for result in domain.results
        ]
        if entries:
            resources[domain.domain] = entries
        attention = [result for result in domain.results if result.status in ATTENTION_STATUSES]
        if attention:
            blocked[domain.domain] = {
                "kind": "resource",
                "conflicts": [
                    {
                        "target": shorten_user_path(result.resource.target, home),
                        "status": resource_status_label(result.status),
                        "reason": humanize_reason(result.reason),
                    }
                    for result in attention
                ],
            }

    change_entries = changes or []
    payload = {
        "schemaVersion": 2,
        "summary": {
            "ready": _ready_domains(domains),
            "blocked": _blocked_domains(domains),
            "changeCount": change_count(change_entries),
            "exitCode": 3 if apply_check_has_conflicts(domains) else 0,
        },
        "builds": builds,
        "blocked": blocked,
        "resources": resources,
        "phases": {
            "build": [
                {
                    "domain": domain.domain,
                    "store": str(domain.store),
                    "storeLabel": shorten_store_path(domain.store),
                    "resourceCount": domain.resource_count,
                }
                for domain in domains
            ],
            "changes": [
                {
                    "domain": entry.domain,
                    "verb": entry.verb.value,
                    "target": shorten_user_path(entry.target, home),
                    "reason": entry.reason,
                    "resourceId": entry.resource_id,
                }
                for entry in change_entries
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def render_apply_preflight_text(
    domains: list[DomainPreflight],
    *,
    identity: MachineIdentity,
    verbose: bool = False,
    style: Style | None = None,
) -> str:
    """Compact preflight output used before interactive apply."""
    style = style or Style()
    home = identity.home
    lines: list[str] = [_section_title(style, "Build")]
    for domain in domains:
        store_label = shorten_store_path(domain.store)
        lines.append(
            f"  {domain.domain:<7} {style.dim(store_label)}  ({domain.resource_count} resources)"
        )

    attention_found = False
    for domain in domains:
        if domain.error is not None:
            attention_found = True
            lines.append("")
            lines.append(style.red(f"{domain.domain}: blocked"))
            for conflict in parse_preflight_conflicts(domain.error.message):
                lines.append(f"  {style.red('✗')} {shorten_user_path(conflict.target, home)}")
                lines.append(f"    {style.dim(conflict.reason)}")
            continue
        attention = [result for result in domain.results if result.status in ATTENTION_STATUSES]
        if not attention and not verbose:
            continue
        if attention:
            attention_found = True
            lines.append("")
            lines.append(style.yellow(f"{domain.domain}: attention needed"))
            for result in attention:
                marker = "!" if result.status == ConflictStatus.OVERWRITABLE_CONFLICT else "✗"
                lines.append(
                    f"  {style.yellow(marker)} {shorten_user_path(result.resource.target, home)}"
                )
                lines.append(f"    {style.dim(humanize_reason(result.reason))}")
        elif verbose:
            lines.append("")
            lines.append(style.bold(f"{domain.domain}"))
            for result in domain.results:
                label = _status_color(style, result.status)
                lines.append(
                    f"  {label:<16} {shorten_user_path(result.resource.target, home)}"
                )

    if not attention_found and not verbose:
        ready = _ready_domains(domains)
        if ready:
            lines.append("")
            lines.append(
                style.green(f"Ready: {', '.join(ready)}")
            )
    return "\n".join(lines)


def humanize_diagnostic_reason(reason: str) -> str:
    return DIAGNOSTIC_REASON_LABELS.get(reason, reason)


def _humanize_activation_message(message: str) -> str:
    if not message.startswith("activated "):
        return message
    rest = message.removeprefix("activated ")
    if ";" not in rest:
        return f"activated {shorten_store_path(rest.strip())}"
    store, detail = rest.split(";", 1)
    return f"activated {shorten_store_path(store.strip())};{detail}"


def render_init_text(*, identity: MachineIdentity, changed: bool, style: Style | None = None) -> str:
    style = style or Style()
    action = "initialized" if changed else "already initialized"
    lines = [
        _section_title(style, "Identity"),
        f"  {style.green('✓')} {action}",
        f"  user    {identity.username}",
        f"  home    {shorten_user_path(identity.home_directory, identity.home)}",
        f"  system  {identity.nix_system}",
        "",
        style.green("Result: ready (exit 0)"),
    ]
    return "\n".join(lines)


def render_validate_text(
    *,
    identity: MachineIdentity,
    local_skill_count: int,
    external_skill_count: int,
    skill_affects: list[tuple[str, list[str]]],
    style: Style | None = None,
) -> str:
    style = style or Style()
    lines = [
        _section_title(style, "Identity"),
        f"  user    {identity.username}",
        f"  home    {shorten_user_path(identity.home_directory, identity.home)}",
        f"  system  {identity.nix_system}",
        "",
        _section_title(style, "Skills"),
    ]
    if skill_affects:
        for canonical_id, affected in skill_affects:
            platforms = ", ".join(affected) if affected else style.dim("no platform")
            lines.append(f"  {canonical_id} → {platforms}")
    else:
        lines.append(f"  {style.dim('no external skills configured')}")
    lines.extend(
        [
            "",
            _section_title(style, "Checks"),
            f"  {style.green('✓')} static contracts",
            f"  {style.green('✓')} nix system evaluation",
            f"  {style.green('✓')} compiled {', '.join(PLATFORMS)} bundles",
            f"  {style.green('✓')} validated {local_skill_count} local and "
            f"{external_skill_count} external skill(s)",
            "",
            _section_title(style, "Notes"),
            f"  {style.yellow('!')} Cursor global rules are not supported via filesystem",
            "",
            style.green("Result: validation passed (exit 0)"),
        ]
    )
    return "\n".join(lines)


def render_activation_results_text(
    outcomes: list[DomainResult],
    failures: list[tuple[str, str]],
    *,
    style: Style | None = None,
) -> str:
    style = style or Style()
    if not outcomes and not failures:
        return ""
    lines = [_section_title(style, "Activated")]
    for outcome in outcomes:
        marker = style.green("✓")
        if outcome.status == "PARTIAL_UPDATED":
            marker = style.yellow("~")
        elif outcome.status != "UPDATED":
            marker = style.yellow("!")
        lines.append(
            f"  {marker} {outcome.domain:<7} {_humanize_activation_message(outcome.message)}"
        )
    for domain, message in failures:
        lines.append(f"  {style.red('✗')} {domain:<7} {message}")
    return "\n".join(lines)


def render_doctor_text(
    diagnostics: list[Diagnostic],
    *,
    identity: MachineIdentity,
    verbose: bool = False,
    style: Style | None = None,
) -> str:
    style = style or Style()
    home = identity.home
    issues = [item for item in diagnostics if item.status in DIAGNOSTIC_UNHEALTHY]
    info = [item for item in diagnostics if item.status in DIAGNOSTIC_INFO]
    healthy = [item for item in diagnostics if item.status == DiagnosticStatus.HEALTHY]

    lines: list[str] = []
    if issues:
        lines.append(_section_title(style, "Issues"))
        current_domain: str | None = None
        for diagnostic in issues:
            if diagnostic.domain != current_domain:
                current_domain = diagnostic.domain
                lines.append(style.bold(f"  {diagnostic.domain}"))
            target = (
                shorten_user_path(diagnostic.target, home)
                if diagnostic.target
                else style.dim("domain")
            )
            lines.append(f"    {style.red('✗')} {target}")
            lines.append(f"      {style.dim(humanize_diagnostic_reason(diagnostic.reason))}")

    if info:
        if lines:
            lines.append("")
        lines.append(_section_title(style, "Info"))
        current_domain = None
        for diagnostic in info:
            if diagnostic.domain != current_domain:
                current_domain = diagnostic.domain
                lines.append(style.bold(f"  {diagnostic.domain}"))
            target = (
                shorten_user_path(diagnostic.target, home)
                if diagnostic.target
                else style.dim("capability")
            )
            lines.append(f"    {style.yellow('!')} {target}")
            lines.append(f"      {style.dim(humanize_diagnostic_reason(diagnostic.reason))}")

    if verbose and healthy:
        if lines:
            lines.append("")
        lines.append(_section_title(style, "Healthy"))
        current_domain = None
        for diagnostic in healthy:
            if diagnostic.domain != current_domain:
                current_domain = diagnostic.domain
                lines.append(style.bold(f"  {diagnostic.domain}"))
            target = shorten_user_path(diagnostic.target, home) if diagnostic.target else "domain"
            lines.append(f"    {style.green('✓')} {target}")

    healthy_count = len(healthy)
    info_count = len(info)
    issue_count = len(issues)
    lines.append("")
    lines.append(_section_title(style, "Summary"))
    lines.append(
        f"  {healthy_count} healthy, {info_count} informational, {issue_count} unhealthy"
    )
    lines.append("")
    if issue_count:
        lines.append(style.red("Result: problems found (exit 6)"))
    else:
        lines.append(style.green("Result: healthy (exit 0)"))
    if not verbose and healthy_count:
        lines.append(style.dim("Run with --verbose to see healthy resources."))
    return "\n".join(lines)


def render_doctor_json(diagnostics: list[Diagnostic]) -> str:
    from .doctor import diagnostics_healthy

    healthy_count = sum(item.status == DiagnosticStatus.HEALTHY for item in diagnostics)
    info_count = sum(item.status in DIAGNOSTIC_INFO for item in diagnostics)
    issue_count = sum(item.status in DIAGNOSTIC_UNHEALTHY for item in diagnostics)
    payload = {
        "schemaVersion": 1,
        "summary": {
            "healthy": healthy_count,
            "informational": info_count,
            "unhealthy": issue_count,
            "exitCode": 0 if diagnostics_healthy(diagnostics) else 6,
        },
        "diagnostics": [item.to_dict() for item in diagnostics],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def format_rollback_prompt(
    *,
    current: Path,
    target: Path,
    generation: int,
    style: Style | None = None,
) -> str:
    style = style or Style()
    return "\n".join(
        [
            _section_title(style, "Rollback"),
            f"  current  {style.dim(shorten_store_path(current))}",
            f"  target   {shorten_store_path(target)} (generation {generation})",
            "",
            "Confirm rollback? [y/N] ",
        ]
    )


def render_rollback_cancelled_text(*, style: Style | None = None) -> str:
    style = style or Style()
    return style.yellow("Result: rollback cancelled (exit 3)")


def render_rollback_result_text(result: DomainResult, *, style: Style | None = None) -> str:
    style = style or Style()
    lines = [
        _section_title(style, "Activated"),
        f"  {style.green('✓')} {result.domain:<7} {_humanize_activation_message(result.message)}",
        "",
        style.green("Result: rollback complete (exit 0)"),
    ]
    return "\n".join(lines)


def render_error_text(error: DotfilesError, *, style: Style | None = None) -> str:
    style = style or Style(enabled=stderr_enabled())
    lines = [_section_title(style, "Error"), f"  {error.message}"]
    if error.modified_state is True:
        modification = "yes; the operation reports the changed state above"
    elif error.modified_state is False:
        modification = "no runtime or machine state was modified"
    else:
        modification = "possibly; run dot doctor before retrying"
    lines.extend(["", _section_title(style, "Modified state"), f"  {modification}"])
    if error.next_step:
        lines.extend(["", _section_title(style, "Next step"), f"  {error.next_step}"])
    return "\n".join(lines)


def stderr_enabled() -> bool:
    return sys.stderr.isatty() and not os.environ.get("NO_COLOR")
