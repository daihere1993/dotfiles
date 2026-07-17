from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .activation import (
    activate_platform,
    activate_system_store,
    current_platform,
    current_system_store,
    effective_active_manifest,
    make_resource_actions,
    other_active_manifests,
    preflight_platform,
    profile_path,
    reconcile_platform,
    system_manifest_path,
)
from .apply_events import (
    ActivationMilestone,
    ApplyEvent,
    ApplyPhase,
    ChangeEntry,
    ChangeVerb,
)
from .apply_reporter import ApplyReporter, build_result_lines, build_verify_summary
from .errors import ConflictError, DotfilesError, ValidationError
from .machine import read_identity
from .manifest import assert_identity, read_manifest
from .models import (
    DOMAINS,
    PLATFORMS,
    ActivationPlan,
    ConflictResult,
    ConflictStatus,
    DeploymentManifest,
    Diagnostic,
    DiagnosticStatus,
    DomainResult,
    MachineIdentity,
    ResourceDecision,
)
from .nix import CommandRunner, archive_repository, build_domain, reject_concurrent_apply
from .planning import (
    DeploymentPlan,
    DomainAction,
    build_deployment_plan,
    build_plan_changes,
    plan_domain,
    serialize_domain_actions,
)
from .present import (
    Style,
    apply_check_has_conflicts,
    build_apply_check_report,
    format_conflict_prompt,
    render_changes_summary,
)
from .state import backup_root, read_receipt


@dataclass(frozen=True)
class ApplyOptions:
    check: bool = False
    verbose: bool = False
    json_output: bool = False
    json_events: bool = False
    platform: str | None = None
    yes: bool = False


def _manifest_for_built(domain: str, store: Path) -> DeploymentManifest:
    path = (
        system_manifest_path(store)
        if domain == "system"
        else store / "share/dotfiles/manifest.json"
    )
    return read_manifest(path)


def _system_preflight(
    identity: MachineIdentity, desired: DeploymentManifest, others: list[DeploymentManifest]
) -> tuple[Path | None, DeploymentManifest | None, list[ConflictResult]]:
    try:
        current_link = Path("/run/current-system")
        if not current_link.exists() and not current_link.is_symlink():
            return None, None, preflight_platform(desired, None, others)
        old_store = current_system_store()
        active_path = system_manifest_path(old_store)
        active = read_manifest(active_path) if active_path.is_file() else None
        if active:
            assert_identity(identity, active)
    except OSError:
        old_store, active = None, None
    return old_store, active, preflight_platform(desired, active, others)


def _existing_kind(path: Path) -> str:
    if path.is_symlink():
        return "user-owned symlink"
    if path.is_dir():
        return "user-owned directory"
    return "user-owned file"


def _domain_list(options: ApplyOptions) -> tuple[str, ...]:
    if options.platform:
        return (options.platform,)
    return DOMAINS


def _scope_label(options: ApplyOptions) -> str:
    if options.platform:
        return f"platform apply ({options.platform} only)"
    return "full apply (system → codex → claude → cursor)"


def _serialize_entries(entries: list[ChangeEntry]) -> list[dict]:
    return [
        {
            "domain": entry.domain,
            "verb": entry.verb.value,
            "target": entry.target,
            "reason": entry.reason,
            "resource_id": entry.resource_id,
        }
        for entry in entries
    ]




def _not_deployed(domain: str, staged: bool = False) -> Diagnostic:
    status = DiagnosticStatus.STAGED_NOT_DEPLOYED if staged else DiagnosticStatus.NOT_DEPLOYED
    return Diagnostic(
        domain,
        status,
        "profile exists without a healthy managed entry" if staged else "no active manifest",
    )


def collect_doctor_diagnostics(
    identity: MachineIdentity, *, domain: str
) -> list[Diagnostic]:
    from .doctor import diagnose_manifest

    diagnostics: list[Diagnostic] = []
    if domain == "system":
        try:
            path = system_manifest_path(current_system_store())
            if not path.is_file():
                diagnostics.append(_not_deployed("system"))
                return diagnostics
            diagnostics.extend(diagnose_manifest(identity, read_manifest(path)))
        except OSError:
            diagnostics.append(_not_deployed("system"))
        return diagnostics

    state, _, manifest = current_platform(identity, domain)
    receipt = read_receipt(identity, domain)
    if state.value == "NOT_DEPLOYED":
        diagnostics.append(_not_deployed(domain))
        if domain == "cursor":
            diagnostics.append(
                Diagnostic(
                    "cursor",
                    DiagnosticStatus.UNSUPPORTED_OPTIONAL,
                    "Cursor global rules have no supported filesystem interface",
                )
            )
    elif state.value == "STAGED_NOT_DEPLOYED" and receipt is None:
        diagnostics.append(_not_deployed(domain, staged=True))
        if domain == "cursor":
            diagnostics.append(
                Diagnostic(
                    "cursor",
                    DiagnosticStatus.UNSUPPORTED_OPTIONAL,
                    "Cursor global rules have no supported filesystem interface",
                )
            )
    elif manifest:
        diagnostics.extend(diagnose_manifest(identity, manifest, receipt))
    return diagnostics


def resolve_platform_actions(
    plans: dict,
    *,
    interactive: bool,
    style: Style | None = None,
    reporter: ApplyReporter | None = None,
) -> bool:
    style = style or Style()
    mode: str | None = None
    any_skipped = False
    for platform in PLATFORMS:
        if platform not in plans:
            continue
        results, plan = plans[platform]
        if plan is None:
            continue
        overwrite_ids: set[str] = set()
        for result in results:
            if result.status != ConflictStatus.OVERWRITABLE_CONFLICT:
                continue
            choice = mode
            if choice is None and interactive:
                skill_id = result.resource.id.rsplit(".skill.", 1)[-1]
                inventory = next(
                    (
                        item
                        for item in plan.desired_manifest.skills
                        if item.target_id == skill_id
                    ),
                    None,
                )
                prompt = format_conflict_prompt(
                    target=result.resource.target,
                    home=plan.identity.home,
                    existing_kind=_existing_kind(Path(result.resource.target)),
                    desired=inventory.canonical_id if inventory else skill_id,
                    backup_hint=str(backup_root(plan.identity)),
                    style=style,
                )
                if reporter is not None:
                    reporter.emit(
                        ApplyEvent(
                            phase=ApplyPhase.RESOLVE,
                            kind="conflict_prompt",
                            payload={"prompt": prompt},
                        )
                    )
                else:
                    print(prompt)
                while True:
                    try:
                        value = input("Choice [o/s/a/k]: ").strip().lower()
                    except (EOFError, KeyboardInterrupt) as error:
                        raise ConflictError(
                            "interactive conflict resolution interrupted; "
                            "no state was modified"
                        ) from error
                    if value in {"o", "s", "a", "k"}:
                        break
                    print("Choose o, s, a, or k.")
                if value == "a":
                    mode = "overwrite"
                    choice = "overwrite"
                elif value == "k":
                    mode = "skip"
                    choice = "skip"
                else:
                    choice = "overwrite" if value == "o" else "skip"
            elif choice is None:
                choice = "skip"
            if choice == "overwrite":
                overwrite_ids.add(result.resource.id)
            else:
                any_skipped = True
            if reporter is not None:
                reporter.emit(
                    ApplyEvent(
                        phase=ApplyPhase.RESOLVE,
                        kind="conflict_resolved",
                        payload={
                            "target": result.resource.target,
                            "decision": choice,
                        },
                    )
                )
        actions = make_resource_actions(
            results, plan.desired_manifest, plan.old_receipt, overwrite_ids
        )
        if any(action.decision == ResourceDecision.SKIP for action in actions):
            any_skipped = True
        plans[platform] = (
            results,
            ActivationPlan(
                plan.platform,
                plan.identity,
                plan.profile_path,
                plan.new_store_path,
                plan.desired_manifest,
                plan.old_store_path,
                plan.active_manifest,
                actions,
                plan.old_receipt,
            ),
        )
    return any_skipped


class ApplySession:
    def __init__(
        self,
        runner: CommandRunner,
        reporter: ApplyReporter,
        options: ApplyOptions,
    ) -> None:
        self.runner = runner
        self.reporter = reporter
        self.options = options
        self.style = Style()
        self._started = time.monotonic()

    def _emit(self, phase: ApplyPhase, kind: str, **payload) -> None:
        self.reporter.emit(ApplyEvent(phase=phase, kind=kind, payload=payload))

    def _emit_changes(self, deployment: DeploymentPlan, entries: list[ChangeEntry]) -> None:
        domain_actions = serialize_domain_actions(deployment)
        self._emit(
            ApplyPhase.CHANGES,
            "changes_rendered",
            entries=_serialize_entries(entries),
            domainOrder=list(_domain_list(self.options)),
            domainActions=domain_actions,
            summary=render_changes_summary(
                entries, domain_actions=domain_actions, style=self.style
            ),
        )

    def run(self, repository: Path) -> int:
        if self.options.json_output and not self.options.check:
            raise ValidationError("`--json` requires `--check`")
        if self.options.json_output and self.options.json_events:
            raise ValidationError("`--json` and `--json-events` cannot be used together")

        reject_concurrent_apply(self.runner)
        repository = archive_repository(self.runner, repository)
        identity = read_identity()
        domains_to_build = list(_domain_list(self.options))

        self._emit(
            ApplyPhase.PLAN,
            "plan_header",
            scope=_scope_label(self.options),
            identity=identity.username,
            nixSystem=identity.nix_system,
        )

        stores: dict[str, Path] = {}
        manifests: dict[str, DeploymentManifest] = {}
        for domain in domains_to_build:
            self._emit(ApplyPhase.BUILD, "domain_build_started", domain=domain)
            started = time.monotonic()
            try:
                store = build_domain(
                    self.runner,
                    repository,
                    identity,
                    domain,
                    verbose=self.options.verbose,
                    on_substep=lambda current, label: self._emit(
                        ApplyPhase.BUILD,
                        "domain_build_substep",
                        domain=current,
                        label=label,
                    ),
                )
            except DotfilesError as error:
                self._emit(
                    ApplyPhase.BUILD,
                    "domain_build_failed",
                    domain=domain,
                    message=error.message,
                )
                raise
            manifest = _manifest_for_built(domain, store)
            assert_identity(identity, manifest)
            stores[domain] = store
            manifests[domain] = manifest
            duration_ms = int((time.monotonic() - started) * 1000)
            self._emit(
                ApplyPhase.BUILD,
                "domain_build_completed",
                domain=domain,
                store=str(store),
                resourceCount=len(manifest.resources),
                durationMs=duration_ms,
            )

        plans: dict[str, tuple[list[ConflictResult], ActivationPlan | None]] = {}
        preflight_errors: dict[str, ConflictError] = {}
        planned_domains = []

        if self.options.platform:
            platform = self.options.platform
            _, old_store, active = current_platform(identity, platform)
            receipt = read_receipt(identity, platform)
            active = effective_active_manifest(active, receipt)
            others = other_active_manifests(identity, platform)
            try:
                results = preflight_platform(
                    manifests[platform], active, others, resource_level=True
                )
                self._emit_preflight(platform, results, error=None)
            except ConflictError as error:
                results = []
                preflight_errors[platform] = error
                self._emit_preflight(platform, results, error=error)
            plans[platform] = (
                results,
                ActivationPlan(
                    platform=platform,
                    identity=identity,
                    profile_path=str(profile_path(identity, platform)),
                    new_store_path=str(stores[platform]),
                    desired_manifest=manifests[platform],
                    old_store_path=str(old_store) if old_store else None,
                    active_manifest=active,
                    old_receipt=receipt,
                ),
            )
            planned_domains.append(
                plan_domain(
                    platform,
                    desired_store=stores[platform],
                    desired=manifests[platform],
                    active_store=old_store,
                    active=active,
                    safety=results,
                    blocked=platform in preflight_errors,
                )
            )
        else:
            system_others = [manifests[platform] for platform in PLATFORMS]
            system_old_store = None
            system_active = None
            try:
                system_old_store, system_active, system_results = _system_preflight(
                    identity, manifests["system"], system_others
                )
                self._emit_preflight("system", system_results, error=None)
                plans["system"] = (system_results, None)
            except ConflictError as error:
                preflight_errors["system"] = error
                self._emit_preflight("system", [], error=error)
                plans["system"] = ([], None)
                system_results = []
            planned_domains.append(
                plan_domain(
                    "system",
                    desired_store=stores["system"],
                    desired=manifests["system"],
                    active_store=system_old_store,
                    active=system_active,
                    safety=system_results,
                    blocked="system" in preflight_errors,
                )
            )

            for platform in PLATFORMS:
                _, old_store, active = current_platform(identity, platform)
                receipt = read_receipt(identity, platform)
                active = effective_active_manifest(active, receipt)
                others = [manifest for name, manifest in manifests.items() if name != platform]
                try:
                    results = preflight_platform(
                        manifests[platform], active, others, resource_level=True
                    )
                    self._emit_preflight(platform, results, error=None)
                except ConflictError as error:
                    results = []
                    preflight_errors[platform] = error
                    self._emit_preflight(platform, results, error=error)
                plans[platform] = (
                    results,
                    ActivationPlan(
                        platform=platform,
                        identity=identity,
                        profile_path=str(profile_path(identity, platform)),
                        new_store_path=str(stores[platform]),
                        desired_manifest=manifests[platform],
                        old_store_path=str(old_store) if old_store else None,
                        active_manifest=active,
                        old_receipt=receipt,
                    ),
                )
                planned_domains.append(
                    plan_domain(
                        platform,
                        desired_store=stores[platform],
                        desired=manifests[platform],
                        active_store=old_store,
                        active=active,
                        safety=results,
                        blocked=platform in preflight_errors,
                    )
                )

        deployment = build_deployment_plan(planned_domains)

        domain_report = build_apply_check_report(
            identity=identity,
            stores=stores,
            manifests=manifests,
            plans=plans,
            preflight_errors=preflight_errors,
        )
        entries = build_plan_changes(deployment, plans, verbose=self.options.verbose)

        if self.options.check:
            self._emit_changes(deployment, entries)
            if self.options.json_output:
                from .present import render_apply_check_json

                print(
                    render_apply_check_json(
                        domain_report,
                        identity=identity,
                        changes=entries,
                        domain_actions=serialize_domain_actions(deployment),
                    )
                )
            else:
                exit_code = 3 if apply_check_has_conflicts(domain_report) else 0
                self._emit_result(
                    exit_code=exit_code,
                    result_message=(
                        "conflicts found" if exit_code else "ready to apply"
                    ),
                )
            return 3 if apply_check_has_conflicts(domain_report) else 0

        if any(domain.action == DomainAction.BLOCKED for domain in deployment.domains):
            self._emit_changes(deployment, entries)
            self._emit_result(exit_code=3, result_message="conflicts found")
            return 3

        partial = resolve_platform_actions(
            plans, interactive=sys.stdin.isatty(), style=self.style, reporter=self.reporter
        )
        entries = build_plan_changes(deployment, plans, verbose=self.options.verbose)
        self._emit_changes(deployment, entries)

        if any(entry.verb in {ChangeVerb.BLOCKED, ChangeVerb.CONFLICT} for entry in entries):
            self._emit_result(exit_code=3, result_message="conflicts remain")
            return 3

        if not deployment.changes_state and not partial:
            self._emit_result(exit_code=0, result_message="no changes needed")
            return 0

        if not self.options.yes and not sys.stdin.isatty():
            raise ValidationError(
                "non-interactive apply requires `--yes`",
                next_step=(
                    "Run `dot apply --check` to inspect the plan or retry with "
                    "`dot apply --yes`."
                ),
            )

        if not self._confirm_apply():
            self._emit(ApplyPhase.CONFIRM, "confirm_cancelled")
            self._emit_result(exit_code=3, result_message="apply cancelled")
            return 3

        return self._activate_all(
            identity=identity,
            stores=stores,
            plans=plans,
            preflight_errors=preflight_errors,
            partial=partial,
            deployment=deployment,
        )

    def _emit_preflight(
        self,
        domain: str,
        results: list[ConflictResult],
        *,
        error: ConflictError | None,
    ) -> None:
        if error is not None:
            status = "blocked"
            attention = 0
        else:
            attention = sum(
                1
                for result in results
                if result.status
                in {ConflictStatus.CONFLICT, ConflictStatus.OVERWRITABLE_CONFLICT}
            )
            status = "attention" if attention else "ok"
        self._emit(
            ApplyPhase.PREFLIGHT,
            "domain_preflight_completed",
            domain=domain,
            status=status,
            attentionCount=attention,
        )

    def _confirm_apply(self) -> bool:
        if self.options.yes or self.options.check:
            return True
        if not sys.stdin.isatty():
            return False
        self._emit(ApplyPhase.CONFIRM, "confirm_prompt", prompt="Apply? [y/N] ")
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in {"y", "yes"}

    def _activation_callback(self, domain: str, milestone: ActivationMilestone) -> None:
        if milestone == ActivationMilestone.DOMAIN_COMPLETE:
            return
        self._emit(
            ApplyPhase.APPLY,
            "activation_step",
            domain=domain,
            milestone=milestone.value,
        )

    def _emit_activation_complete(self, outcome: DomainResult) -> None:
        from .present import _humanize_activation_message

        self._emit(
            ApplyPhase.APPLY,
            "activation_step",
            domain=outcome.domain,
            milestone=ActivationMilestone.DOMAIN_COMPLETE.value,
            message=_humanize_activation_message(outcome.message),
        )

    def _activate_all(
        self,
        *,
        identity: MachineIdentity,
        stores: dict[str, Path],
        plans: dict,
        preflight_errors: dict[str, ConflictError],
        partial: bool,
        deployment: DeploymentPlan,
    ) -> int:
        outcomes: list[DomainResult] = []
        failures: list[tuple[str, DotfilesError]] = []
        skipped_domains: list[str] = []
        activation_order = list(_domain_list(self.options))

        for domain in activation_order:
            domain_plan = deployment.for_domain(domain)
            if not domain_plan.changes_state:
                if domain not in preflight_errors:
                    skipped_domains.append(domain)
                    self._activation_callback(domain, ActivationMilestone.DOMAIN_SKIPPED)
                continue
            try:
                if domain == "system":
                    outcome = activate_system_store(
                        self.runner,
                        stores["system"],
                        identity,
                        on_milestone=self._activation_callback,
                    )
                else:
                    _, plan = plans[domain]
                    assert plan is not None
                    if domain_plan.action == DomainAction.RECONCILE:
                        outcome = reconcile_platform(
                            self.runner,
                            plan,
                            on_milestone=self._activation_callback,
                        )
                    else:
                        outcome = activate_platform(
                            self.runner,
                            plan,
                            on_milestone=self._activation_callback,
                        )
                outcomes.append(outcome)
                self._emit_activation_complete(outcome)
            except DotfilesError as error:
                rolled_back = "ROLLED_BACK" in error.message
                self._emit(
                    ApplyPhase.APPLY,
                    "activation_failed",
                    domain=domain,
                    message=error.message,
                    rolledBack=rolled_back,
                )
                failures.append((domain, error))

        doctor_failed = False
        next_step: str | None = None
        updated_domains = {outcome.domain for outcome in outcomes}
        for domain in updated_domains:
            diagnostics = collect_doctor_diagnostics(identity, domain=domain)
            from .doctor import diagnostics_healthy

            healthy = diagnostics_healthy(diagnostics)
            self._emit(
                ApplyPhase.VERIFY,
                "verify_completed",
                domain=domain,
                healthy=healthy,
            )
            if not healthy:
                doctor_failed = True
                _, suggestion = build_verify_summary(diagnostics, self.style)
                next_step = suggestion

        if failures:
            raise failures[0][1]

        exit_code = 3 if partial or preflight_errors else 0
        if doctor_failed:
            exit_code = 6

        result_message = "applied successfully"
        if partial or preflight_errors:
            result_message = "applied with warnings"
        elif doctor_failed:
            result_message = "applied but verification failed"

        self._emit_result(
            exit_code=exit_code,
            result_message=result_message,
            outcomes=outcomes,
            failures=[(domain, error.message) for domain, error in failures],
            skipped_domains=skipped_domains,
            next_step=next_step,
        )
        return exit_code

    def _emit_result(
        self,
        *,
        exit_code: int,
        result_message: str,
        outcomes: list[DomainResult] | None = None,
        failures: list[tuple[str, str]] | None = None,
        skipped_domains: list[str] | None = None,
        next_step: str | None = None,
    ) -> None:
        duration_ms = int((time.monotonic() - self._started) * 1000)
        lines = build_result_lines(
            outcomes=outcomes or [],
            failures=failures or [],
            skipped_domains=skipped_domains or [],
            style=self.style,
        )
        self._emit(
            ApplyPhase.RESULT,
            "result",
            exitCode=exit_code,
            durationMs=duration_ms,
            resultMessage=result_message,
            lines=lines,
            nextStep=next_step,
        )
