from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import __version__
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
    select_previous_system_generation,
    system_manifest_path,
)
from .compiler import (
    SkillSource,
    compile_platform,
    discover_local_skills,
    validate_external_locks,
    validate_skill,
    validate_static_contracts,
)
from .doctor import diagnose_manifest, diagnostics_healthy
from .errors import ConflictError, DotfilesError, ValidationError
from .machine import (
    default_state_path,
    discover_identity,
    read_identity,
    validate_identity,
    write_identity,
)
from .manifest import assert_identity, read_manifest
from .models import (
    PLATFORMS,
    ActivationPlan,
    ConflictStatus,
    DeploymentManifest,
    Diagnostic,
    DiagnosticStatus,
    MachineIdentity,
    ResourceDecision,
)
from .nix import (
    SubprocessRunner,
    archive_repository,
    build_domain,
    evaluate_system,
    find_repository,
    read_agent_config,
    reject_concurrent_apply,
)
from .present import (
    Style,
    apply_check_has_conflicts,
    build_apply_check_report,
    format_conflict_prompt,
    format_rollback_prompt,
    render_activation_results_text,
    render_apply_check_json,
    render_apply_check_text,
    render_apply_preflight_text,
    render_doctor_json,
    render_doctor_text,
    render_error_text,
    render_init_text,
    render_rollback_cancelled_text,
    render_rollback_result_text,
    render_validate_text,
    stderr_enabled,
)
from .state import backup_root, read_receipt

TEST_IDENTITY = MachineIdentity("testuser", "/Users/testuser")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dot", description="Validate and deploy shared macOS dotfiles"
    )
    parser.add_argument("-v", "--version", action="version", version=f"dot {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="discover and persist this machine's identity")
    subparsers.add_parser("validate", help="validate Nix and Agent canonical configuration")
    apply_parser = subparsers.add_parser(
        "apply", help="build, preflight, and activate configuration"
    )
    apply_parser.add_argument("--check", action="store_true", help="stop after build and preflight")
    apply_parser.add_argument(
        "--verbose", action="store_true", help="show every resource during preflight output"
    )
    apply_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="emit machine-readable preflight JSON"
    )
    apply_parser.add_argument("--platform", choices=PLATFORMS)
    doctor_parser = subparsers.add_parser("doctor", help="diagnose active managed resources")
    doctor_parser.add_argument("--json", action="store_true", dest="json_output")
    doctor_parser.add_argument(
        "--verbose", action="store_true", help="show healthy managed resources"
    )
    doctor_parser.add_argument("--platform", choices=PLATFORMS)
    subparsers.add_parser("rollback", help="activate the previous distinct system generation")

    return parser


def _internal_parser() -> argparse.ArgumentParser:
    internal = argparse.ArgumentParser(prog="dot internal-compile", add_help=False)
    internal.set_defaults(command="internal-compile")
    internal.add_argument("--repository", type=Path, required=True)
    internal.add_argument("--platform", choices=PLATFORMS, required=True)
    internal.add_argument("--identity-json", required=True)
    internal.add_argument("--artifact-root", required=True)
    internal.add_argument("--output", type=Path, required=True)
    internal.add_argument("--skill", action="append", default=[])
    internal.add_argument("--skill-spec", action="append", default=[])
    return internal


def _identity_if_available() -> MachineIdentity:
    path = default_state_path()
    if not path.exists() and not path.is_symlink():
        return TEST_IDENTITY
    return read_identity(path)


def _cmd_init(runner: SubprocessRunner) -> int:
    repository = find_repository(Path.cwd())
    identity = discover_identity()
    changed = write_identity(identity)
    try:
        evaluate_system(runner, repository, identity)
    except DotfilesError as error:
        error.modified_state = changed
        raise
    print(render_init_text(identity=identity, changed=changed, style=Style()))
    return 0


def _cmd_validate(runner: SubprocessRunner) -> int:
    repository = find_repository(Path.cwd())
    repository = archive_repository(runner, repository)
    identity = _identity_if_available()
    validate_identity(identity)
    validate_static_contracts(identity)
    local_skills = discover_local_skills(repository / "ai-agent/skills")
    evaluate_system(runner, repository, identity)
    agent_config = read_agent_config(runner, repository)
    external_skills = {
        f"external:{key}": _skill_from_spec(json.dumps(value))
        for key, value in agent_config.get("externalSkills", {}).items()
    }
    for skill in external_skills.values():
        validate_skill(skill)
    validate_external_locks(
        repository,
        {skill.source_id for skill in external_skills.values() if skill.source_id},
    )
    skill_affects: list[tuple[str, list[str]]] = []
    for canonical_id in sorted(external_skills):
        affected = [
            platform
            for platform in PLATFORMS
            if canonical_id in agent_config.get("profiles", {}).get(platform, [])
        ]
        skill_affects.append((canonical_id, affected))
    with tempfile.TemporaryDirectory(prefix="dot-validate-") as temporary:
        root = Path(temporary)
        for platform in PLATFORMS:
            selected = []
            for canonical_id in agent_config.get("profiles", {}).get(platform, []):
                skill = local_skills.get(canonical_id) or external_skills.get(canonical_id)
                if skill is None:
                    raise ValidationError(
                        f"{platform} profile references unknown skill: {canonical_id}"
                    )
                selected.append(skill)
            compile_platform(
                repository=repository,
                platform=platform,
                identity=identity,
                output_root=root / platform,
                artifact_root=f"/nix/store/validation-{platform}",
                skills=selected,
            )
    print(
        render_validate_text(
            identity=identity,
            local_skill_count=len(local_skills),
            external_skill_count=len(external_skills),
            skill_affects=skill_affects,
            style=Style(),
        )
    )
    return 0


def _manifest_for_built(domain: str, store: Path):
    path = (
        system_manifest_path(store)
        if domain == "system"
        else store / "share/dotfiles/manifest.json"
    )
    return read_manifest(path)


def _platform_plan(
    runner: SubprocessRunner,
    repository: Path,
    identity: MachineIdentity,
    platform: str,
):
    store = build_domain(runner, repository, identity, platform)
    desired = _manifest_for_built(platform, store)
    assert_identity(identity, desired)
    _, old_store, active = current_platform(identity, platform)
    others = other_active_manifests(identity, platform)
    receipt = read_receipt(identity, platform)
    active = effective_active_manifest(active, receipt)
    results = preflight_platform(desired, active, others, resource_level=True)
    plan = ActivationPlan(
        platform=platform,
        identity=identity,
        profile_path=str(profile_path(identity, platform)),
        new_store_path=str(store),
        desired_manifest=desired,
        old_store_path=str(old_store) if old_store else None,
        active_manifest=active,
        old_receipt=receipt,
    )
    return store, desired, results, plan


def _system_preflight(identity: MachineIdentity, desired, others: list):
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


def _resolve_platform_actions(
    plans: dict, *, interactive: bool, style: Style | None = None
) -> bool:
    style = style or Style()
    mode: str | None = None
    any_skipped = False
    for platform in PLATFORMS:
        if platform not in plans:
            continue
        results, plan = plans[platform]
        overwrite_ids: set[str] = set()
        for result in results:
            if result.status != ConflictStatus.OVERWRITABLE_CONFLICT:
                continue
            choice = mode
            if choice is None and interactive:
                skill_id = result.resource.id.rsplit(".skill.", 1)[-1]
                inventory = next(
                    (item for item in plan.desired_manifest.skills if item.target_id == skill_id),
                    None,
                )
                print(
                    format_conflict_prompt(
                        target=result.resource.target,
                        home=plan.identity.home,
                        existing_kind=_existing_kind(Path(result.resource.target)),
                        desired=inventory.canonical_id if inventory else skill_id,
                        backup_hint=str(backup_root(plan.identity)),
                        style=style,
                    )
                )
                while True:
                    try:
                        value = (
                            input("Choice [o/s/a/k]: ")
                            .strip()
                            .lower()
                        )
                    except (EOFError, KeyboardInterrupt) as error:
                        raise ConflictError(
                            "interactive conflict resolution interrupted; no state was modified"
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


def _cmd_apply(args: argparse.Namespace, runner: SubprocessRunner) -> int:
    if args.json_output and not args.check:
        raise ValidationError("`--json` requires `--check`")
    repository = find_repository(Path.cwd())
    reject_concurrent_apply(runner)
    repository = archive_repository(runner, repository)
    identity = read_identity()
    style = Style()
    if args.platform:
        store, _, results, plan = _platform_plan(runner, repository, identity, args.platform)
        plans = {args.platform: (results, plan)}
        domains = build_apply_check_report(
            identity=identity,
            stores={args.platform: store},
            manifests={args.platform: plan.desired_manifest},
            plans=plans,
            preflight_errors={},
        )
        if args.check:
            if args.json_output:
                print(render_apply_check_json(domains, identity=identity))
            else:
                print(render_apply_check_text(domains, identity=identity, verbose=args.verbose, style=style))
            return 3 if apply_check_has_conflicts(domains) else 0
        print(
            render_apply_preflight_text(
                domains, identity=identity, verbose=args.verbose, style=style
            )
        )
        partial = _resolve_platform_actions(plans, interactive=sys.stdin.isatty(), style=style)
        outcome = activate_platform(runner, plans[args.platform][1])
        print(render_activation_results_text([outcome], [], style=style))
        doctor = _cmd_doctor(
            argparse.Namespace(platform=args.platform, json_output=False, verbose=False)
        )
        return 3 if partial else doctor

    stores = {
        domain: build_domain(runner, repository, identity, domain)
        for domain in ("system", *PLATFORMS)
    }
    manifests = {domain: _manifest_for_built(domain, store) for domain, store in stores.items()}
    plans = {}
    preflight_errors: dict[str, ConflictError] = {}
    system_others = [manifests[platform] for platform in PLATFORMS]
    try:
        _, _, system_results = _system_preflight(
            identity, manifests["system"], system_others
        )
        plans["system"] = (system_results, None)
    except ConflictError as error:
        preflight_errors["system"] = error
    for platform in PLATFORMS:
        _, old_store, active = current_platform(identity, platform)
        receipt = read_receipt(identity, platform)
        active = effective_active_manifest(active, receipt)
        others = [manifest for domain, manifest in manifests.items() if domain != platform]
        try:
            results = preflight_platform(manifests[platform], active, others, resource_level=True)
        except ConflictError as error:
            results = []
            preflight_errors[platform] = error
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
    domains = build_apply_check_report(
        identity=identity,
        stores=stores,
        manifests=manifests,
        plans=plans,
        preflight_errors=preflight_errors,
    )
    if args.check:
        if args.json_output:
            print(render_apply_check_json(domains, identity=identity))
        else:
            print(render_apply_check_text(domains, identity=identity, verbose=args.verbose, style=style))
        return 3 if apply_check_has_conflicts(domains) else 0
    print(render_apply_preflight_text(domains, identity=identity, verbose=args.verbose, style=style))
    partial = _resolve_platform_actions(plans, interactive=sys.stdin.isatty(), style=style)
    outcomes = []
    failures: list[tuple[str, DotfilesError]] = []
    if "system" not in preflight_errors:
        try:
            outcomes.append(activate_system_store(runner, stores["system"], identity))
        except DotfilesError as error:
            failures.append(("system", error))
    for platform in PLATFORMS:
        if platform in preflight_errors:
            continue
        try:
            outcomes.append(activate_platform(runner, plans[platform][1]))
        except DotfilesError as error:
            failures.append((platform, error))
    activation_report = render_activation_results_text(
        outcomes,
        [(domain, error.message) for domain, error in failures],
        style=style,
    )
    if activation_report:
        print(activation_report)
    doctor_failed = False
    updated_platforms = {outcome.domain for outcome in outcomes if outcome.domain in PLATFORMS}
    for platform in PLATFORMS:
        if platform in updated_platforms:
            doctor_failed = (
                _cmd_doctor(
                    argparse.Namespace(platform=platform, json_output=False, verbose=False)
                )
                != 0
                or doctor_failed
            )
    if failures:
        raise failures[0][1]
    if partial or preflight_errors:
        return 3
    if doctor_failed:
        return 6
    return 0


def _not_deployed(domain: str, staged: bool = False) -> Diagnostic:
    status = DiagnosticStatus.STAGED_NOT_DEPLOYED if staged else DiagnosticStatus.NOT_DEPLOYED
    return Diagnostic(
        domain,
        status,
        "profile exists without a healthy managed entry" if staged else "no active manifest",
    )


def _cmd_doctor(args: argparse.Namespace) -> int:
    identity = read_identity()
    diagnostics: list[Diagnostic] = []
    domains = [args.platform] if args.platform else ["system", *PLATFORMS]
    for domain in domains:
        if domain == "system":
            try:
                path = system_manifest_path(current_system_store())
                if not path.is_file():
                    diagnostics.append(_not_deployed("system"))
                    continue
                diagnostics.extend(diagnose_manifest(identity, read_manifest(path)))
            except OSError:
                diagnostics.append(_not_deployed("system"))
        else:
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
    if args.json_output:
        print(render_doctor_json(diagnostics))
    else:
        print(
            render_doctor_text(
                diagnostics,
                identity=identity,
                verbose=args.verbose,
                style=Style(),
            )
        )
    return 0 if diagnostics_healthy(diagnostics) else 6


def _cmd_rollback(runner: SubprocessRunner) -> int:
    style = Style()
    identity = read_identity()
    current = current_system_store()
    number, target = select_previous_system_generation(current)
    manifest = read_manifest(system_manifest_path(target))
    assert_identity(identity, manifest)
    _system_preflight(identity, manifest, other_active_manifests(identity, "system"))
    answer = input(
        format_rollback_prompt(
            current=current,
            target=target,
            generation=number,
            style=style,
        )
    )
    if answer.strip().lower() not in {"y", "yes"}:
        print(render_rollback_cancelled_text(style=style))
        return 3
    result = activate_system_store(runner, target, identity)
    print(render_rollback_result_text(result, style=style))
    return 0


def _skill_from_spec(value: str) -> SkillSource:
    spec = json.loads(value)
    return SkillSource(
        canonical_id=spec["canonicalId"],
        target_id=spec["targetId"],
        path=Path(spec["path"]),
        source_kind=spec["sourceKind"],
        source_path=spec["sourcePath"],
        source_id=spec.get("sourceId"),
        nar_hash=spec.get("narHash"),
        rev=spec.get("rev"),
    )


def _cmd_internal_compile(args: argparse.Namespace) -> int:
    identity = MachineIdentity.from_dict(json.loads(args.identity_json))
    validate_identity(identity)
    available = discover_local_skills(args.repository / "ai-agent/skills")
    selected: list[SkillSource] = []
    for canonical_id in args.skill:
        try:
            selected.append(available[canonical_id])
        except KeyError as error:
            raise ValidationError(
                f"profile references unknown local skill: {canonical_id}"
            ) from error
    selected.extend(_skill_from_spec(value) for value in args.skill_spec)
    compile_platform(
        repository=args.repository,
        platform=args.platform,
        identity=identity,
        output_root=args.output,
        artifact_root=args.artifact_root,
        skills=selected,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] == "internal-compile":
        args = _internal_parser().parse_args(values[1:])
    else:
        args = _parser().parse_args(values)
    runner = SubprocessRunner()
    try:
        if args.command == "init":
            return _cmd_init(runner)
        if args.command == "validate":
            return _cmd_validate(runner)
        if args.command == "apply":
            return _cmd_apply(args, runner)
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "rollback":
            return _cmd_rollback(runner)
        if args.command == "internal-compile":
            return _cmd_internal_compile(args)
        raise AssertionError(args.command)
    except DotfilesError as error:
        print(render_error_text(error, style=Style(enabled=stderr_enabled())), file=sys.stderr)
        return error.exit_code
