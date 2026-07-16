from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Protocol, TextIO

from .apply_events import (
    ActivationMilestone,
    ApplyEvent,
    ApplyPhase,
    ChangeEntry,
    ChangeVerb,
)
from .models import Diagnostic, DomainResult, MachineIdentity, PLATFORMS
from .present import (
    Style,
    _section_title,
    humanize_diagnostic_reason,
    render_apply_check_json,
    render_changes_plan,
    shorten_store_path,
    shorten_user_path,
)


class ApplyReporter(Protocol):
    def emit(self, event: ApplyEvent) -> None: ...


@dataclass
class CollectingReporter:
    events: list[ApplyEvent] = field(default_factory=list)

    def emit(self, event: ApplyEvent) -> None:
        self.events.append(event)


@dataclass
class CompositeReporter:
    reporters: list[ApplyReporter]

    def emit(self, event: ApplyEvent) -> None:
        for reporter in self.reporters:
            reporter.emit(event)


@dataclass
class JsonEventReporter:
    stream: TextIO = field(default_factory=lambda: sys.stdout)

    def emit(self, event: ApplyEvent) -> None:
        print(json.dumps(event.to_dict(), ensure_ascii=False), file=self.stream, flush=True)


MILESTONE_LABELS = {
    ActivationMilestone.MIGRATE_SSH: "migrating SSH config",
    ActivationMilestone.BACKUP_OVERWRITES: "backing up conflicting resources",
    ActivationMilestone.SWITCH_PROFILE: "switching profile",
    ActivationMilestone.RUN_ACTIVATE_SCRIPT: "running activate script",
    ActivationMilestone.INSTALL_SYMLINKS: "installing symlinks",
    ActivationMilestone.VERIFY_RESOURCES: "verifying resources",
    ActivationMilestone.VERIFY_CURRENT_SYSTEM: "verifying current system",
    ActivationMilestone.WRITE_RECEIPT: "writing activation receipt",
    ActivationMilestone.DOMAIN_COMPLETE: "complete",
    ActivationMilestone.DOMAIN_SKIPPED: "skipped (no changes)",
}


@dataclass
class TextApplyReporter:
    identity: MachineIdentity
    verbose: bool = False
    style: Style | None = None
    stream: TextIO = field(default_factory=lambda: sys.stdout)
    _sections_started: set[ApplyPhase] = field(default_factory=set, init=False)
    _build_lines: dict[str, str] = field(default_factory=dict, init=False)
    _apply_steps: dict[str, list[str]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.style is None:
            self.style = Style()

    def emit(self, event: ApplyEvent) -> None:
        handler = getattr(self, f"_on_{event.kind}", None)
        if handler is not None:
            handler(event)
        elif self.verbose:
            self._write(f"  [{event.phase.value}] {event.kind}")

    def _write(self, text: str) -> None:
        print(text, file=self.stream, flush=True)

    def _ensure_section(self, phase: ApplyPhase, title: str) -> None:
        if phase in self._sections_started:
            return
        self._sections_started.add(phase)
        if self._sections_started and phase != ApplyPhase.PLAN:
            self._write("")
        self._write(_section_title(self.style, title))

    def _on_plan_header(self, event: ApplyEvent) -> None:
        self._ensure_section(ApplyPhase.PLAN, "Plan")
        scope = event.payload["scope"]
        self._write(f"  machine   {self.identity.username} @ {self.identity.nix_system}")
        self._write(f"  scope     {scope}")

    def _on_domain_build_started(self, event: ApplyEvent) -> None:
        self._ensure_section(ApplyPhase.BUILD, "Build")
        domain = event.payload["domain"]
        self._build_lines[domain] = f"  {self.style.cyan('●')} {domain:<7} building…"
        self._write(self._build_lines[domain])

    def _on_domain_build_substep(self, event: ApplyEvent) -> None:
        if not self.verbose:
            return
        domain = event.payload["domain"]
        label = event.payload.get("label", "")
        self._write(f"  {self.style.dim(f'[{domain}] {label}')}")

    def _on_domain_build_completed(self, event: ApplyEvent) -> None:
        domain = event.payload["domain"]
        store = event.payload["store"]
        resource_count = event.payload.get("resourceCount", 0)
        duration_s = event.payload.get("durationMs", 0) / 1000
        label = shorten_store_path(store)
        line = (
            f"  {self.style.green('✓')} {domain:<7} {self.style.dim(label)}  "
            f"({resource_count} resources)  {duration_s:.1f}s"
        )
        self._build_lines[domain] = line
        self._write(line)

    def _on_domain_build_failed(self, event: ApplyEvent) -> None:
        domain = event.payload["domain"]
        message = event.payload.get("message", "build failed")
        self._write(f"  {self.style.red('✗')} {domain:<7} {message}")

    def _on_domain_preflight_completed(self, event: ApplyEvent) -> None:
        self._ensure_section(ApplyPhase.PREFLIGHT, "Preflight")
        domain = event.payload["domain"]
        status = event.payload["status"]
        attention = event.payload.get("attentionCount", 0)
        if status == "blocked":
            self._write(f"  {self.style.red('✗')} {domain:<7} blocked")
        elif attention:
            self._write(
                f"  {self.style.yellow('~')} {domain:<7} "
                f"{attention} resource(s) need attention"
            )
        else:
            self._write(f"  {self.style.green('✓')} {domain:<7} no conflicts")

    def _on_changes_rendered(self, event: ApplyEvent) -> None:
        self._ensure_section(ApplyPhase.CHANGES, "Changes")
        entries = [
            ChangeEntry(
                domain=item["domain"],
                verb=ChangeVerb(item["verb"]),
                target=item["target"],
                reason=item["reason"],
                resource_id=item.get("resource_id"),
            )
            for item in event.payload.get("entries", [])
        ]
        domain_order = event.payload.get("domainOrder", ["system", *PLATFORMS])
        body = render_changes_plan(
            entries,
            identity=self.identity,
            domain_order=domain_order,
            verbose=self.verbose,
            style=self.style,
        )
        section = _section_title(self.style, "Changes")
        if body.startswith(section):
            body = body[len(section) + 1 :]
        if body:
            self._write(body)
        summary = event.payload.get("summary")
        if summary:
            self._write("")
            self._write(summary)

    def _on_conflict_prompt(self, event: ApplyEvent) -> None:
        self._ensure_section(ApplyPhase.RESOLVE, "Resolve")
        self._write(event.payload["prompt"])

    def _on_conflict_resolved(self, event: ApplyEvent) -> None:
        target = shorten_user_path(event.payload["target"], self.identity.home)
        decision = event.payload["decision"]
        self._write(f"  {self.style.dim('→')} {target}: {decision}")

    def _on_confirm_prompt(self, event: ApplyEvent) -> None:
        self._ensure_section(ApplyPhase.CONFIRM, "Confirm")
        self._write(event.payload.get("prompt", "Apply? [y/N] "))

    def _on_confirm_cancelled(self, event: ApplyEvent) -> None:
        self._write(self.style.yellow("Apply cancelled."))

    def _on_activation_step(self, event: ApplyEvent) -> None:
        self._ensure_section(ApplyPhase.APPLY, "Apply")
        domain = event.payload["domain"]
        milestone = ActivationMilestone(event.payload["milestone"])
        if milestone == ActivationMilestone.DOMAIN_SKIPPED:
            self._write(f"  {domain}")
            self._write(f"    {self.style.dim('○')} skipped (no changes)")
            return
        if milestone == ActivationMilestone.DOMAIN_COMPLETE:
            message = event.payload.get("message", "activated")
            self._write(f"    {self.style.green('✓')} {message}")
            return
        label = MILESTONE_LABELS.get(milestone, milestone.value)
        steps = self._apply_steps.setdefault(domain, [])
        if not steps:
            self._write(f"  {domain}")
        self._write(f"    {self.style.cyan('●')} {label}…")

    def _on_activation_failed(self, event: ApplyEvent) -> None:
        domain = event.payload["domain"]
        message = event.payload.get("message", "activation failed")
        rolled_back = event.payload.get("rolledBack")
        suffix = " (rolled back)" if rolled_back else ""
        self._write(f"  {self.style.red('✗')} {domain:<7} {message}{suffix}")

    def _on_verify_completed(self, event: ApplyEvent) -> None:
        self._ensure_section(ApplyPhase.VERIFY, "Verification")
        domain = event.payload["domain"]
        healthy = event.payload.get("healthy", True)
        marker = self.style.green("✓") if healthy else self.style.red("✗")
        label = "passed" if healthy else "problems found"
        self._write(f"  {marker} {domain:<7} doctor {label}")

    def _on_result(self, event: ApplyEvent) -> None:
        self._ensure_section(ApplyPhase.RESULT, "Result")
        for line in event.payload.get("lines", []):
            self._write(line)
        exit_code = event.payload.get("exitCode", 0)
        duration_s = event.payload.get("durationMs", 0) / 1000
        if duration_s:
            self._write("")
            self._write(f"  Total time: {duration_s:.1f}s")
        result_line = event.payload.get("resultLine")
        if result_line:
            self._write("")
            self._write(result_line)
        next_step = event.payload.get("nextStep")
        if next_step:
            self._write("")
            self._write(_section_title(self.style, "Next step"))
            self._write(f"  {next_step}")
        if exit_code == 0:
            color = self.style.green
        elif exit_code == 6:
            color = self.style.red
        else:
            color = self.style.yellow
        self._write("")
        self._write(color(f"Result: {event.payload.get('resultMessage', 'complete')} (exit {exit_code})"))

    def _on_check_json(self, event: ApplyEvent) -> None:
        domains = event.payload["domains"]
        changes = event.payload.get("changes", [])
        self._write(
            render_apply_check_json(
                domains,
                identity=self.identity,
                changes=changes,
            )
        )


def build_reporter(
    *,
    identity: MachineIdentity,
    verbose: bool,
    json_output: bool,
    json_events: bool,
    check: bool,
) -> ApplyReporter:
    reporters: list[ApplyReporter] = []
    if json_events:
        reporters.append(JsonEventReporter())
    if not json_output and not json_events:
        reporters.append(
            TextApplyReporter(identity=identity, verbose=verbose, style=Style())
        )
    elif json_events and verbose:
        reporters.append(
            TextApplyReporter(identity=identity, verbose=verbose, style=Style(), stream=sys.stderr)
        )
    if not reporters:
        reporters.append(CollectingReporter())
    if len(reporters) == 1:
        return reporters[0]
    return CompositeReporter(reporters)


def format_duration_ms(duration_ms: int) -> str:
    return f"{duration_ms / 1000:.1f}s"


def build_result_lines(
    *,
    outcomes: list[DomainResult],
    failures: list[tuple[str, str]],
    skipped_domains: list[str],
    style: Style,
) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for outcome in outcomes:
        seen.add(outcome.domain)
        if outcome.status == "PARTIAL_UPDATED":
            marker = style.yellow("~")
            label = "updated with warnings"
        elif outcome.status == "UPDATED":
            marker = style.green("✓")
            label = "updated"
        else:
            marker = style.yellow("!")
            label = outcome.status.lower()
        lines.append(f"  {marker} {outcome.domain:<7} {label}")
    for domain, message in failures:
        seen.add(domain)
        lines.append(f"  {style.red('✗')} {domain:<7} failed")
    for domain in skipped_domains:
        if domain not in seen:
            lines.append(f"  {style.dim('○')} {domain:<7} unchanged")
    return lines


def build_verify_summary(diagnostics: list[Diagnostic], style: Style) -> tuple[bool, str | None]:
    from .present import DIAGNOSTIC_UNHEALTHY

    unhealthy = [item for item in diagnostics if item.status in DIAGNOSTIC_UNHEALTHY]
    if not unhealthy:
        return True, None
    domains = sorted({item.domain for item in unhealthy})
    if len(domains) == 1:
        return False, f"dot doctor --platform {domains[0]}"
    return False, "dot doctor"
