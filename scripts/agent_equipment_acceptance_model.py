#!/usr/bin/env python3
"""Disposable executable fixtures for the agent-equipment acceptance contract.

This module models controller semantics against an isolated fake state store. It
does not inspect or mutate a real harness, user home, or native manager.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any, Mapping


JsonValue = Any
DesiredState = Mapping[str, JsonValue]


@dataclass(frozen=True)
class ApplyResult:
    status: str
    mutated_surfaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpdateProposal:
    desired_state: dict[str, JsonValue]


@dataclass(frozen=True)
class ProviderSwitchResult:
    trace: tuple[str, ...]
    active_components: tuple[str, ...]


@dataclass(frozen=True)
class ImportedObservation:
    surface: str
    value: JsonValue
    digest: str


@dataclass(frozen=True)
class AdoptionProposal:
    surface: str
    value: JsonValue
    control_owner: str


class ConcurrentChangeError(RuntimeError):
    """The observed pre-state no longer matches the current fake runtime."""


class InjectedFailure(RuntimeError):
    """A deterministic acceptance-fixture fault fired."""


class BindingMismatchError(RuntimeError):
    """A durable checkpoint does not bind the supplied retry plan."""


class PlanValidationError(RuntimeError):
    """The complete mutation plan is invalid."""


class DuplicateProviderError(RuntimeError):
    """Observed provider overlap is not the exact declared route set."""


class ArtifactVerificationError(RuntimeError):
    """Immutable artifact bytes did not match the reviewed digest."""


@dataclass(frozen=True)
class StatusResult:
    status: str


@dataclass(frozen=True)
class NativeRollingProposal:
    baseline: dict[str, JsonValue]


@dataclass(frozen=True)
class RetirementProposal:
    status: str
    plan: MutationPlan | None = None


@dataclass(frozen=True)
class NonautomatedReport:
    items: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class Mutation:
    step_id: str
    surface: str
    before: JsonValue
    after: JsonValue
    route: str
    operation: str


@dataclass(frozen=True)
class MutationPlan:
    actions: tuple[Mutation, ...]
    candidate_digest: str
    catalog_digest: str
    lock_digest: str
    plan_digest: str
    capability_digest: str


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    trace: tuple[str, ...]


MISSING = {"$state": "missing"}
BINDING_FIELDS = (
    "candidate_digest",
    "catalog_digest",
    "lock_digest",
    "plan_digest",
    "capability_digest",
    "route_digest",
    "operation_digest",
    "pre_state_digest",
    "expected_post_state_digest",
    "surface",
)
MUTATING_OPERATIONS = frozenset(
    {"install", "configure", "enable", "disable", "remove", "restore"}
)


class FakeAdapter:
    """In-memory harness/manager boundary used only by acceptance fixtures."""

    def __init__(self) -> None:
        self.state: dict[str, JsonValue] = {}
        self.calls: list[tuple[str, str]] = []

    def set(self, surface: str, value: JsonValue) -> None:
        self.calls.append(("set", surface))
        self.state[surface] = deepcopy(value)

    def remove(self, surface: str) -> None:
        self.calls.append(("remove", surface))
        self.state.pop(surface, None)

    def digest(self) -> str:
        return canonical_digest(self.state)


def canonical_digest(value: JsonValue) -> str:
    payload = canonical_bytes(value)
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def canonical_bytes(value: JsonValue) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def bytes_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def deep_copy(value: JsonValue) -> JsonValue:
    return deepcopy(value)


def migration_initial_state() -> dict[str, JsonValue]:
    return {
        "00/projector": {"mode": "blanket"},
        "01/matt-link": {"link_text": "../../.agents/skills/create-auth"},
        "02/matt-plugin-installed": False,
        "03/matt-plugin-enabled": False,
        "04/context7-mcp": {"provider": "legacy"},
        "05/component-selection": {"deferred": True},
        "06/coverage-verification": {"status": "old"},
    }


def migration_desired_state() -> dict[str, JsonValue]:
    return {
        "00/projector": {"mode": "catalog"},
        "01/matt-link": MISSING,
        "02/matt-plugin-installed": True,
        "03/matt-plugin-enabled": True,
        "04/context7-mcp": {"provider": "selected"},
        "05/component-selection": {"deferred": False},
        "06/coverage-verification": {"status": "passed", "duplicates": []},
    }


def assert_secret_free(
    artifact: JsonValue,
    *,
    forbidden_values: set[str],
) -> None:
    encoded = canonical_bytes(artifact)
    for value in forbidden_values:
        if value.encode("utf-8") in encoded:
            raise ValueError("secret value present in artifact")


def resolve_provider_routes(
    selected: tuple[str, ...],
    observed: tuple[str, ...],
    *,
    allow_overlap: tuple[str, ...] | None,
) -> tuple[str, ...]:
    selected_set = set(selected)
    observed_set = set(observed)
    if observed_set != selected_set:
        raise DuplicateProviderError("observed provider set differs from selection")
    if len(selected_set) > 1 and set(allow_overlap or ()) != selected_set:
        raise DuplicateProviderError("provider overlap lacks an exact exception")
    return selected


def complete_desired_state() -> dict[str, JsonValue]:
    """Return a representative skill/plugin/MCP desired-state slice."""

    return {
        "standalone/skill:research": {
            "kind": "skill",
            "revision": "sha256:standalone-research-v1",
        },
        "claude/projection:research": {
            "kind": "projection",
            "target": "standalone/skill:research",
        },
        "claude/plugin:mattpocock": {
            "kind": "plugin",
            "installed": True,
            "enabled": True,
            "activation_group": "activation:mattpocock/claude",
        },
        "claude/component:mattpocock/engineering-skills": {
            "kind": "plugin_component",
            "enabled": True,
        },
        "claude/mcp:context7": {
            "kind": "mcp",
            "transport": "stdio",
            "secret_ref": "CONTEXT7_API_KEY",
        },
    }


class AcceptanceFixture:
    """Public scenario seam for isolated convergence and recovery fixtures."""

    def __init__(self, sandbox: Path) -> None:
        self.sandbox = Path(sandbox)
        self.sandbox.mkdir(parents=True, exist_ok=True)
        self.adapter = FakeAdapter()
        self.checkpoint_directory = self.sandbox / "checkpoints"
        self.checkpoint_directory.mkdir(exist_ok=True)
        self.standalone_root = self.sandbox / "standalone"
        self.last_trace: tuple[str, ...] = ()
        self._adopted: dict[str, str] = {}

    def apply(self, desired_state: DesiredState) -> ApplyResult:
        mutated_surfaces = []
        for surface, desired in desired_state.items():
            if self.adapter.state.get(surface) != desired:
                self.adapter.set(surface, desired)
                mutated_surfaces.append(surface)
        return ApplyResult(
            status="completed" if mutated_surfaces else "no_op",
            mutated_surfaces=tuple(mutated_surfaces),
        )

    def checkpoint_bytes(self) -> bytes:
        """Return the durable fixture journal as a comparison-friendly blob."""

        return b"".join(
            path.read_bytes()
            for path in sorted(self.checkpoint_directory.glob("*.json"))
        )

    def checkpoints(self) -> dict[str, dict[str, JsonValue]]:
        return {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.checkpoint_directory.glob("*.json"))
        }

    def plan(self, desired_state: DesiredState) -> MutationPlan:
        actions = []
        for surface in sorted(desired_state):
            before = deepcopy(self.adapter.state.get(surface, MISSING))
            after = deepcopy(desired_state[surface])
            if before == after:
                continue
            actions.append(
                Mutation(
                    step_id=f"step-{len(actions):03d}",
                    surface=surface,
                    before=before,
                    after=after,
                    route=f"route:fixture/{surface}",
                    operation="configure",
                )
            )
        plan_material = [
            {
                "step_id": action.step_id,
                "surface": action.surface,
                "before": action.before,
                "after": action.after,
                "route": action.route,
                "operation": action.operation,
            }
            for action in actions
        ]
        return MutationPlan(
            actions=tuple(actions),
            candidate_digest="sha256:fixture-candidate-v1",
            catalog_digest="sha256:fixture-catalog-v1",
            lock_digest="sha256:fixture-lock-v1",
            plan_digest=canonical_digest(plan_material),
            capability_digest="sha256:fixture-capabilities-v1",
        )

    def migration_plan(self, desired_state: DesiredState) -> MutationPlan:
        """Return the ordered disposable migration-boundary plan."""

        return self.plan(desired_state)

    def plan_for_operation(
        self,
        operation: str,
        desired_state: DesiredState,
    ) -> MutationPlan:
        if operation not in MUTATING_OPERATIONS:
            raise PlanValidationError(operation)
        plan = self.plan(desired_state)
        actions = tuple(
            Mutation(
                step_id=action.step_id,
                surface=action.surface,
                before=action.before,
                after=action.after,
                route=action.route,
                operation=operation,
            )
            for action in plan.actions
        )
        plan_material = [
            {
                "step_id": action.step_id,
                "surface": action.surface,
                "before": action.before,
                "after": action.after,
                "route": action.route,
                "operation": action.operation,
            }
            for action in actions
        ]
        return MutationPlan(
            actions=actions,
            candidate_digest=plan.candidate_digest,
            catalog_digest=plan.catalog_digest,
            lock_digest=plan.lock_digest,
            plan_digest=canonical_digest(plan_material),
            capability_digest=plan.capability_digest,
        )

    def evidence_bundle(self) -> dict[str, JsonValue]:
        return {
            "fixture": "agent-equipment-acceptance/v1",
            "checkpoints": self.checkpoints(),
            "trace": list(self.last_trace),
        }

    def execute(
        self,
        plan: MutationPlan,
        *,
        fail_at: set[str] | None = None,
        compensate_on_failure: bool = False,
        before_compensation: Any | None = None,
        before_mutation: Any | None = None,
    ) -> ExecutionResult:
        self._validate_plan(plan)
        failures = set(fail_at or ())
        trace = []
        try:
            for action in plan.actions:
                checkpoint = self._checkpoint(plan, action, "prepared")
                existing = self.checkpoints().get(action.step_id)
                if existing is None:
                    self._write_checkpoint(
                        checkpoint,
                        fail="prepared_write",
                        action=action,
                        failures=failures,
                    )
                    trace.append(f"prepared:{action.step_id}")
                else:
                    self._validate_checkpoint_binding(existing, checkpoint)
                    checkpoint = existing
                if before_mutation is not None:
                    before_mutation(action)
                current = deepcopy(self.adapter.state.get(action.surface, MISSING))
                if current == action.after:
                    trace.append(f"audit:{action.step_id}:post_state")
                    self._advance_phase(checkpoint, "completed")
                    self._write_checkpoint(
                        checkpoint,
                        fail="completion_write",
                        action=action,
                        failures=failures,
                    )
                    trace.append(f"completed:{action.step_id}")
                    continue
                if current != action.before:
                    raise ConcurrentChangeError(action.surface)
                if existing is not None:
                    trace.append(f"audit:{action.step_id}:pre_state")
                self._raise_fault("before_mutation", action, failures)
                self._apply_value(action.surface, action.after)
                self._raise_fault("after_mutation", action, failures)
                self._advance_phase(checkpoint, "completed")
                self._write_checkpoint(
                    checkpoint,
                    fail="completion_write",
                    action=action,
                    failures=failures,
                )
                trace.append(f"completed:{action.step_id}")
        except (ConcurrentChangeError, InjectedFailure):
            if compensate_on_failure:
                self._compensate(
                    plan,
                    failures,
                    trace,
                    before_compensation=before_compensation,
                )
            self.last_trace = tuple(trace)
            raise
        result = ExecutionResult(status="completed", trace=tuple(trace))
        self.last_trace = result.trace
        return result

    @staticmethod
    def _validate_plan(plan: MutationPlan) -> None:
        step_ids = [action.step_id for action in plan.actions]
        if (
            len(step_ids) != len(set(step_ids))
            or any(
                not isinstance(action.operation, str)
                or action.operation not in MUTATING_OPERATIONS
                for action in plan.actions
            )
            or any(not action.surface or not action.route for action in plan.actions)
        ):
            raise PlanValidationError("complete plan validation failed")

    @staticmethod
    def _raise_fault(
        point: str,
        action: Mutation,
        failures: set[str],
    ) -> None:
        fault = f"{point}:{action.step_id}"
        if fault in failures:
            raise InjectedFailure(fault)

    def _checkpoint(
        self,
        plan: MutationPlan,
        action: Mutation,
        phase: str,
    ) -> dict[str, JsonValue]:
        return {
            "step_id": action.step_id,
            "phase": phase,
            "phase_history": [phase],
            "candidate_digest": plan.candidate_digest,
            "catalog_digest": plan.catalog_digest,
            "lock_digest": plan.lock_digest,
            "plan_digest": plan.plan_digest,
            "capability_digest": plan.capability_digest,
            "route_digest": canonical_digest(action.route),
            "operation_digest": canonical_digest(action.operation),
            "pre_state_digest": canonical_digest(action.before),
            "expected_post_state_digest": canonical_digest(action.after),
            "pre_state": action.before,
            "expected_post_state": action.after,
            "surface": action.surface,
        }

    @staticmethod
    def _advance_phase(checkpoint: dict[str, JsonValue], phase: str) -> None:
        checkpoint["phase"] = phase
        checkpoint.setdefault("phase_history", []).append(phase)

    @staticmethod
    def _validate_checkpoint_binding(
        actual: Mapping[str, JsonValue],
        expected: Mapping[str, JsonValue],
    ) -> None:
        if any(actual.get(field) != expected.get(field) for field in BINDING_FIELDS):
            raise BindingMismatchError(str(expected.get("step_id")))

    def _apply_value(self, surface: str, value: JsonValue) -> None:
        if value == MISSING:
            self.adapter.remove(surface)
        else:
            self.adapter.set(surface, value)

    def _compensate(
        self,
        plan: MutationPlan,
        failures: set[str],
        trace: list[str],
        *,
        before_compensation: Any | None = None,
    ) -> None:
        checkpoints = self.checkpoints()
        for action in reversed(plan.actions):
            checkpoint = checkpoints.get(action.step_id)
            if checkpoint is None:
                continue
            if before_compensation is not None:
                before_compensation(action)
            current = deepcopy(self.adapter.state.get(action.surface, MISSING))
            if current not in (action.after, action.before):
                self._advance_phase(checkpoint, "compensation_blocked")
                self._write_checkpoint(
                    checkpoint,
                    fail="compensation_blocked_write",
                    action=action,
                    failures=failures,
                )
                raise ConcurrentChangeError(action.surface)
            if current != action.after:
                continue
            self._advance_phase(checkpoint, "compensating")
            self._write_checkpoint(
                checkpoint,
                fail="compensating_write",
                action=action,
                failures=failures,
            )
            trace.append(f"compensating:{action.step_id}")
            self._raise_fault("before_compensation_mutation", action, failures)
            self._apply_value(action.surface, action.before)
            self._advance_phase(checkpoint, "compensated")
            self._write_checkpoint(
                checkpoint,
                fail="compensated_write",
                action=action,
                failures=failures,
            )
            trace.append(f"compensated:{action.step_id}")

    def recover_compensation(self, plan: MutationPlan) -> ExecutionResult:
        """Audit and finish a durable compensation without replaying forward work."""

        trace = []
        actions = {action.step_id: action for action in plan.actions}
        for step_id, checkpoint in sorted(self.checkpoints().items(), reverse=True):
            if checkpoint["phase"] != "compensating":
                continue
            action = actions[step_id]
            current = deepcopy(self.adapter.state.get(action.surface, MISSING))
            if current == action.after:
                trace.append(f"audit:{step_id}:post_state")
                self._apply_value(action.surface, action.before)
            elif current == action.before:
                trace.append(f"audit:{step_id}:pre_state")
            else:
                self._advance_phase(checkpoint, "compensation_blocked")
                self._write_checkpoint(
                    checkpoint,
                    fail="compensation_blocked_write",
                    action=action,
                    failures=set(),
                )
                raise ConcurrentChangeError(action.surface)
            self._advance_phase(checkpoint, "compensated")
            self._write_checkpoint(
                checkpoint,
                fail="compensated_write",
                action=action,
                failures=set(),
            )
            trace.append(f"compensated:{step_id}")
        result = ExecutionResult(status="recovered", trace=tuple(trace))
        self.last_trace = result.trace
        return result

    def _write_checkpoint(
        self,
        checkpoint: Mapping[str, JsonValue],
        *,
        fail: str,
        action: Mutation,
        failures: set[str],
    ) -> None:
        fault = f"{fail}:{action.step_id}"
        if fault in failures:
            raise InjectedFailure(fault)
        target = self.checkpoint_directory / f"{action.step_id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(checkpoint, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(target)

    def propose_update(
        self,
        desired_state: DesiredState,
        surface: str,
        replacement: JsonValue,
    ) -> UpdateProposal:
        proposed = deepcopy(dict(desired_state))
        proposed[surface] = deepcopy(replacement)
        return UpdateProposal(desired_state=proposed)

    def apply_immutable_update(
        self,
        surface: str,
        *,
        revision: str,
        artifact: bytes,
        expected_digest: str,
    ) -> ApplyResult:
        if bytes_digest(artifact) != expected_digest:
            raise ArtifactVerificationError(surface)
        self.adapter.set(
            surface,
            {"revision": revision, "content": bytes(artifact)},
        )
        return ApplyResult(status="completed", mutated_surfaces=(surface,))

    def switch_provider(
        self,
        *,
        winner_surface: str,
        winner_value: JsonValue,
        component_controls: Mapping[str, bool],
        losing_projections: tuple[str, ...],
        catalog_owned: set[str],
    ) -> ProviderSwitchResult:
        trace = []
        self.adapter.set(winner_surface, winner_value)
        trace.append(f"set:{winner_surface}")
        for component, enabled in sorted(component_controls.items()):
            self.adapter.set(f"component-control/{component}", enabled)
            trace.append(
                f"control:{component}={'enabled' if enabled else 'disabled'}"
            )
        if self.adapter.state[winner_surface] != winner_value:
            raise RuntimeError("winner provider did not verify")
        trace.append(f"verify:{winner_surface}")
        for projection in losing_projections:
            if projection in catalog_owned:
                self.adapter.remove(projection)
                trace.append(f"remove:{projection}")
            else:
                trace.append(f"report_unmanaged:{projection}")
        return ProviderSwitchResult(
            trace=tuple(trace),
            active_components=tuple(
                component
                for component, enabled in sorted(component_controls.items())
                if enabled
            ),
        )

    def import_unmanaged(self, surface: str) -> ImportedObservation:
        value = deepcopy(self.adapter.state[surface])
        return ImportedObservation(
            surface=surface,
            value=value,
            digest=canonical_digest(value),
        )

    def adopt(self, observation: ImportedObservation) -> AdoptionProposal:
        current = self.adapter.state.get(observation.surface)
        if canonical_digest(current) != observation.digest:
            raise ConcurrentChangeError(observation.surface)
        return AdoptionProposal(
            surface=observation.surface,
            value=deepcopy(observation.value),
            control_owner="reconciler_owned",
        )

    def register_adoption(self, observation: ImportedObservation) -> None:
        self.adopt(observation)
        self._adopted[observation.surface] = observation.digest

    def propose_retirement(self, surface: str) -> RetirementProposal:
        current = deepcopy(self.adapter.state.get(surface, MISSING))
        if self._adopted.get(surface) != canonical_digest(current):
            return RetirementProposal(status="report_only")
        return RetirementProposal(
            status="proposed",
            plan=self.plan({surface: MISSING}),
        )

    def audit(self, desired_state: DesiredState) -> StatusResult:
        drift = any(
            self.adapter.state.get(surface, MISSING) != desired
            for surface, desired in desired_state.items()
        )
        return StatusResult(status="drift" if drift else "converged")

    def report_nonautomated(
        self,
        items: tuple[Mapping[str, str], ...],
    ) -> NonautomatedReport:
        copied = tuple(dict(item) for item in items)
        if any(
            item.get("disposition") not in {"operator_action", "unavailable"}
            or not item.get("verification")
            for item in copied
        ):
            raise ValueError("nonautomated report entries need disposition and evidence")
        return NonautomatedReport(items=copied)

    def audit_native_rolling(
        self,
        surface: str,
        baseline: Mapping[str, JsonValue],
    ) -> StatusResult:
        observed = self.adapter.state[surface]["observed_version"]
        return StatusResult(
            status=(
                "converged"
                if observed == baseline["observed_version"]
                else "drift"
            )
        )

    def apply_native_rolling(
        self,
        surface: str,
        baseline: Mapping[str, JsonValue],
    ) -> StatusResult:
        audit = self.audit_native_rolling(surface, baseline)
        return StatusResult(
            status="no_op" if audit.status == "converged" else "drift_reported"
        )

    def propose_native_rolling_update(
        self,
        surface: str,
        baseline: Mapping[str, JsonValue],
    ) -> NativeRollingProposal:
        del baseline
        return NativeRollingProposal(
            baseline={
                "observed_version": self.adapter.state[surface]["observed_version"],
                "reviewed": False,
            }
        )

    def capture_standalone(self, path: Path) -> dict[str, JsonValue]:
        path = Path(path)
        self._assert_standalone_path(path)
        self._assert_no_symlink_parent(path)
        return self._capture_node(path)

    def restore_standalone(
        self,
        path: Path,
        snapshot: Mapping[str, JsonValue],
    ) -> None:
        path = Path(path)
        self._assert_standalone_path(path)
        self._assert_no_symlink_parent(path)
        self._remove_node(path)
        self._restore_node(path, snapshot)

    def _assert_standalone_path(self, path: Path) -> None:
        try:
            path.absolute().relative_to(self.standalone_root.absolute())
        except ValueError as error:
            raise ValueError("standalone path escaped fixture root") from error

    def _assert_no_symlink_parent(self, path: Path) -> None:
        relative = path.absolute().relative_to(self.standalone_root.absolute())
        current = self.standalone_root
        for part in relative.parts[:-1]:
            current /= part
            if current.is_symlink():
                raise ConcurrentChangeError(str(current))

    def _capture_node(self, path: Path) -> dict[str, JsonValue]:
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            link_text = os.readlink(path)
            resolved = (path.parent / link_text).resolve(strict=False)
            return {
                "kind": "symlink",
                "mode": mode,
                "link_text": link_text,
                "resolved_target": str(resolved),
                "broken": not path.exists(),
            }
        if stat.S_ISREG(metadata.st_mode):
            content = path.read_bytes()
            return {
                "kind": "regular_file",
                "mode": mode,
                "content_base64": base64.b64encode(content).decode("ascii"),
                "content_digest": canonical_digest(
                    {"content_base64": base64.b64encode(content).decode("ascii")}
                ),
            }
        if stat.S_ISDIR(metadata.st_mode):
            children = {
                child.name: self._capture_node(child)
                for child in sorted(path.iterdir(), key=lambda item: item.name)
            }
            return {
                "kind": "directory",
                "mode": mode,
                "children": children,
                "tree_digest": canonical_digest(children),
            }
        raise ValueError(f"unsupported standalone path type: {path}")

    @staticmethod
    def _remove_node(path: Path) -> None:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()

    def _restore_node(
        self,
        path: Path,
        snapshot: Mapping[str, JsonValue],
    ) -> None:
        kind = snapshot["kind"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "regular_file":
            path.write_bytes(base64.b64decode(snapshot["content_base64"]))
            os.chmod(path, snapshot["mode"])
            return
        if kind == "symlink":
            os.symlink(snapshot["link_text"], path)
            return
        if kind == "directory":
            path.mkdir()
            for name, child in snapshot["children"].items():
                self._restore_node(path / name, child)
            os.chmod(path, snapshot["mode"])
            return
        raise ValueError(f"unsupported snapshot kind: {kind}")
