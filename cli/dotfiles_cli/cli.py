from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import __version__
from .activation import (
    activate_system_store,
    current_platform,
    current_system_store,
    other_active_manifests,
    preflight_platform,
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
    Diagnostic,
    DiagnosticStatus,
    MachineIdentity,
)
from .nix import (
    SubprocessRunner,
    archive_repository,
    evaluate_system,
    find_repository,
    read_agent_config,
)
from .apply_flow import ApplyOptions, ApplySession
from .apply_reporter import build_reporter
from .present import (
    Style,
    format_rollback_prompt,
    render_doctor_json,
    render_doctor_text,
    render_error_text,
    render_init_text,
    render_rollback_cancelled_text,
    render_rollback_result_text,
    render_validate_text,
    stderr_enabled,
)
from .state import read_receipt

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
    apply_parser.add_argument(
        "--json-events",
        action="store_true",
        help="emit NDJSON apply events to stdout",
    )
    apply_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip final apply confirmation",
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


def _cmd_apply(args: argparse.Namespace, runner: SubprocessRunner) -> int:
    identity = read_identity()
    options = ApplyOptions(
        check=args.check,
        verbose=args.verbose,
        json_output=args.json_output,
        json_events=args.json_events,
        platform=args.platform,
        yes=args.yes,
    )
    reporter = build_reporter(
        identity=identity,
        verbose=args.verbose,
        json_output=args.json_output,
        json_events=args.json_events,
        check=args.check,
    )
    repository = find_repository(Path.cwd())
    return ApplySession(runner, reporter, options).run(repository)


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
    old_store = current_system_store()
    active_path = system_manifest_path(old_store)
    active = read_manifest(active_path) if active_path.is_file() else None
    if active is not None:
        assert_identity(identity, active)
    preflight_platform(manifest, active, other_active_manifests(identity, "system"))
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
