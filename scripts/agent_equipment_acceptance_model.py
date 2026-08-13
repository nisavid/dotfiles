#!/usr/bin/env python3
"""Disposable executable fixtures for the agent-equipment acceptance contract.

This module models controller semantics against an isolated fake state store. It
does not inspect or mutate a real harness, user home, or native manager.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any, Mapping


JsonValue = Any
DesiredState = Mapping[str, JsonValue]
UpdateValidator = Any


def _unique_json_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    document: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON object member")
        document[key] = value
    return document


@dataclass(frozen=True)
class ApplyResult:
    status: str
    mutated_surfaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpdateProposal:
    catalog: dict[str, JsonValue]
    lock: dict[str, JsonValue]


@dataclass(frozen=True)
class ProviderSwitchResult:
    trace: tuple[str, ...]
    active_components: tuple[str, ...]


@dataclass(frozen=True)
class ImportedObservation:
    observation_identity: str
    surface: str
    value: JsonValue
    digest: str
    catalog_digest: str
    inventory_digest: str


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


class HistoricalCheckpointError(RuntimeError):
    """A terminal compensated checkpoint cannot authorize forward replay."""


class CompensationBlockedError(RuntimeError):
    """A durable rollback requires operator disposition before recovery."""


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
class RetirementProposal:
    status: str
    plan: MutationPlan | None = None


@dataclass(frozen=True)
class NonautomatedReport:
    items: tuple[dict[str, str], ...]


@dataclass(frozen=True, order=True)
class CapabilityBinding:
    capability_identity: str
    capability_digest: str
    manager_version_evidence_digest: str


@dataclass(frozen=True)
class Mutation:
    step_id: str
    surface: str
    before: JsonValue
    after: JsonValue
    route: str
    operation: str
    capability_binding: CapabilityBinding
    compensation: str = "restore_captured_pre_state"


@dataclass(frozen=True)
class MutationPlan:
    actions: tuple[Mutation, ...]
    run_identity: str
    execution_domain_identity: str
    candidate_digest: str
    implementation_manifest_digest: str
    catalog_digest: str
    lock_digest: str
    plan_digest: str
    capability_bindings: tuple[CapabilityBinding, ...]
    capability_set_digest: str
    captured_state_identity: str
    captured_state_digest: str


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    trace: tuple[str, ...]


class _MissingState:
    """Internal absence sentinel that cannot collide with valid JSON data."""

    __slots__ = ()

    def __deepcopy__(self, memo: dict[int, object]) -> _MissingState:
        del memo
        return self

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _MissingState()
BINDING_FIELDS = (
    "step_id",
    "action_identity",
    "ordinal",
    "run_identity",
    "execution_domain_identity",
    "candidate_digest",
    "implementation_manifest_digest",
    "catalog_digest",
    "lock_digest",
    "plan_digest",
    "capability_set_digest",
    "captured_state_identity",
    "captured_state_digest",
    "route_capability_binding",
    "route_digest",
    "operation_digest",
    "compensation_operation",
    "pre_state_digest",
    "expected_post_state_digest",
    "pre_state",
    "expected_post_state",
    "surface",
)
CHECKPOINT_FIELDS = frozenset(
    (*BINDING_FIELDS, "phase", "phase_history", "invocation_state")
)
CHECKPOINT_PHASE_HISTORIES = frozenset(
    {
        ("prepared",),
        ("prepared", "completed"),
        ("prepared", "compensating"),
        ("prepared", "completed", "compensating"),
        ("prepared", "compensating", "compensated"),
        ("prepared", "completed", "compensating", "compensated"),
        ("prepared", "compensation_blocked"),
        ("prepared", "completed", "compensation_blocked"),
        ("prepared", "compensating", "compensation_blocked"),
        ("prepared", "completed", "compensating", "compensation_blocked"),
    }
)
MUTATING_OPERATIONS = frozenset(
    {
        "install",
        "configure",
        "enable",
        "disable",
        "remove",
        "restore",
        "suppress_native_update",
    }
)
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and DIGEST_PATTERN.fullmatch(value) is not None


def _is_prefixed_identity(value: object, prefix: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(prefix)
        and len(value) > len(prefix)
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
    if not _is_json_value(value):
        raise ValueError("value is outside the closed JSON domain")
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def bytes_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def deep_copy(value: JsonValue) -> JsonValue:
    return deepcopy(value)


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, int):
        return not isinstance(value, bool)
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in value.items()
        )
    return False


def _is_state_value(value: object) -> bool:
    return value is MISSING or _is_json_value(value)


def state_payload(value: object) -> dict[str, JsonValue]:
    """Serialize internal absence or a present JSON value without collision."""

    if value is MISSING:
        return {"presence": "absent"}
    if not _is_json_value(value):
        raise ValueError("state value is outside the closed state domain")
    return {"presence": "present", "value": value}


def states_equal(left: object, right: object) -> bool:
    """Compare closed state values without Python bool/int coercion."""

    try:
        return canonical_bytes(state_payload(left)) == canonical_bytes(
            state_payload(right)
        )
    except ValueError:
        return False


def json_values_equal(left: object, right: object) -> bool:
    """Compare two closed JSON values with canonical type-exact semantics."""

    try:
        return canonical_bytes(left) == canonical_bytes(right)
    except ValueError:
        return False


def imported_observation_identity(
    *,
    surface: str,
    digest: str,
    catalog_digest: str,
    inventory_digest: str,
) -> str:
    payload = {
        "surface": surface,
        "digest": digest,
        "catalog_digest": catalog_digest,
        "inventory_digest": inventory_digest,
    }
    return f"imported-observation:{canonical_digest(payload)}"


def capability_binding_payload(binding: CapabilityBinding) -> dict[str, str]:
    return {
        "capability_identity": binding.capability_identity,
        "capability_digest": binding.capability_digest,
        "manager_version_evidence_digest": (
            binding.manager_version_evidence_digest
        ),
    }


def capability_set_digest(bindings: tuple[CapabilityBinding, ...]) -> str:
    """Bind the complete, canonical capability evidence set."""

    return canonical_digest(
        [capability_binding_payload(binding) for binding in sorted(bindings)]
    )


def mutation_payload(action: Mutation) -> dict[str, JsonValue]:
    return {
        "step_id": action.step_id,
        "surface": action.surface,
        "before": state_payload(action.before),
        "after": state_payload(action.after),
        "route": action.route,
        "operation": action.operation,
        "compensation": action.compensation,
        "capability_binding": capability_binding_payload(
            action.capability_binding
        ),
    }


def mutation_identity(action: Mutation) -> str:
    return f"action:{canonical_digest(mutation_payload(action))}"


def plan_actions_digest(actions: tuple[Mutation, ...]) -> str:
    """Return the canonical digest of a complete ordered fake action plan."""

    return canonical_digest(
        [mutation_payload(action) for action in actions]
    )


def migration_initial_state() -> dict[str, JsonValue]:
    return {
        "00/projector": {"mode": "blanket"},
        "01/matt-plugin-installed": False,
        "02/matt-plugin-enabled": False,
        "03/matt-winner-activation": {"status": "unverified"},
        "04/matt-link": {"link_text": "../../.agents/skills/create-auth"},
        "05/context7-mcp": {"provider": "legacy"},
        "06/component-selection": {"deferred": True},
        "07/coverage-verification": {"status": "old"},
    }


def migration_desired_state() -> dict[str, JsonValue]:
    return {
        "00/projector": {"mode": "catalog"},
        "01/matt-plugin-installed": True,
        "02/matt-plugin-enabled": True,
        "03/matt-winner-activation": {
            "status": "verified",
            "activation_group": "activation:mattpocock/claude",
        },
        "04/matt-link": MISSING,
        "05/context7-mcp": {"provider": "selected"},
        "06/component-selection": {"deferred": False},
        "07/coverage-verification": {"status": "passed", "duplicates": []},
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
    overlap = allow_overlap or ()
    if (
        len(selected) != len(selected_set)
        or len(observed) != len(observed_set)
        or len(overlap) != len(set(overlap))
    ):
        raise DuplicateProviderError("provider route sequences must be unique")
    if observed_set != selected_set:
        raise DuplicateProviderError("observed provider set differs from selection")
    if len(selected_set) > 1 and set(overlap) != selected_set:
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
        self._imports: dict[str, ImportedObservation] = {}
        self.candidate_digest = f"sha256:{'0' * 64}"
        self.implementation_manifest_digest = f"sha256:{'9' * 64}"

    def checkpoint_bytes(self) -> bytes:
        """Return the durable fixture journal as a comparison-friendly blob."""

        return b"".join(
            path.read_bytes()
            for path in sorted(self.checkpoint_directory.glob("*.json"))
        )

    def checkpoints(self) -> dict[str, dict[str, JsonValue]]:
        checkpoints: dict[str, dict[str, JsonValue]] = {}
        for path in sorted(self.checkpoint_directory.glob("*.json")):
            try:
                document = json.loads(
                    path.read_text(encoding="utf-8"),
                    object_pairs_hook=_unique_json_object,
                )
            except (OSError, UnicodeError, ValueError) as error:
                raise BindingMismatchError(path.stem) from error
            if not isinstance(document, dict):
                raise BindingMismatchError(path.stem)
            checkpoints[path.stem] = document
        return checkpoints

    def plan(self, desired_state: DesiredState) -> MutationPlan:
        capability_binding = CapabilityBinding(
            capability_identity="capability:fixture/adapter-v1",
            capability_digest=f"sha256:{'3' * 64}",
            manager_version_evidence_digest=f"sha256:{'4' * 64}",
        )
        actions = []
        for surface in sorted(desired_state):
            before = deepcopy(self.adapter.state.get(surface, MISSING))
            after = deepcopy(desired_state[surface])
            if states_equal(before, after):
                continue
            actions.append(
                Mutation(
                    step_id=f"step-{len(actions):03d}",
                    surface=surface,
                    before=before,
                    after=after,
                    route=f"route:fixture/{surface}",
                    operation="configure",
                    capability_binding=capability_binding,
                )
            )
        ordered_actions = tuple(actions)
        capability_bindings = (capability_binding,)
        return MutationPlan(
            actions=ordered_actions,
            run_identity="run:fixture/v1",
            execution_domain_identity="execution-domain:fixture/global-ledger-v1",
            candidate_digest=self.candidate_digest,
            implementation_manifest_digest=self.implementation_manifest_digest,
            catalog_digest=f"sha256:{'1' * 64}",
            lock_digest=f"sha256:{'2' * 64}",
            plan_digest=plan_actions_digest(ordered_actions),
            capability_bindings=capability_bindings,
            capability_set_digest=capability_set_digest(capability_bindings),
            captured_state_identity="captured-state:fixture/v1",
            captured_state_digest=f"sha256:{'5' * 64}",
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
                capability_binding=action.capability_binding,
            )
            for action in plan.actions
        )
        return MutationPlan(
            actions=actions,
            run_identity=plan.run_identity,
            execution_domain_identity=plan.execution_domain_identity,
            candidate_digest=plan.candidate_digest,
            implementation_manifest_digest=plan.implementation_manifest_digest,
            catalog_digest=plan.catalog_digest,
            lock_digest=plan.lock_digest,
            plan_digest=plan_actions_digest(actions),
            capability_bindings=plan.capability_bindings,
            capability_set_digest=plan.capability_set_digest,
            captured_state_identity=plan.captured_state_identity,
            captured_state_digest=plan.captured_state_digest,
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
        existing_checkpoints = self.checkpoints()
        plan_step_ids = {action.step_id for action in plan.actions}
        unknown_step_ids = set(existing_checkpoints) - plan_step_ids
        if unknown_step_ids:
            raise BindingMismatchError(sorted(unknown_step_ids)[0])
        for action in plan.actions:
            existing = existing_checkpoints.get(action.step_id)
            if existing is None:
                continue
            self._validate_checkpoint_binding(
                existing,
                self._checkpoint(plan, action, "prepared"),
            )
            if existing.get("phase") in {
                "compensating",
                "compensated",
                "compensation_blocked",
            }:
                raise HistoricalCheckpointError(action.step_id)
            if (
                existing.get("phase") == "completed"
                and existing.get("invocation_state") != "started"
            ):
                raise BindingMismatchError(action.step_id)
            if existing.get("phase") not in {"prepared", "completed"}:
                raise BindingMismatchError(action.step_id)
        try:
            for action in plan.actions:
                checkpoint = self._checkpoint(plan, action, "prepared")
                existing = existing_checkpoints.get(action.step_id)
                if existing is None:
                    self._write_checkpoint(
                        checkpoint,
                        fail="prepared_write",
                        action=action,
                        failures=failures,
                    )
                    trace.append(f"prepared:{action.step_id}")
                else:
                    checkpoint = existing
                if before_mutation is not None:
                    before_mutation(action)
                current = deepcopy(self.adapter.state.get(action.surface, MISSING))
                if existing is not None and checkpoint.get("phase") == "completed":
                    if not states_equal(current, action.after):
                        raise ConcurrentChangeError(action.surface)
                    trace.append(f"audit:{action.step_id}:post_state")
                    continue
                if (
                    existing is not None
                    and checkpoint.get("invocation_state") == "started"
                    and states_equal(current, action.after)
                ):
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
                if not states_equal(current, action.before):
                    raise ConcurrentChangeError(action.surface)
                if existing is not None:
                    trace.append(f"audit:{action.step_id}:pre_state")
                self._raise_fault("before_mutation", action, failures)
                checkpoint["invocation_state"] = "started"
                self._write_checkpoint(
                    checkpoint,
                    fail="invocation_write",
                    action=action,
                    failures=failures,
                )
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
            try:
                if compensate_on_failure:
                    self._compensate(
                        plan,
                        failures,
                        trace,
                        before_compensation=before_compensation,
                    )
            finally:
                self.last_trace = tuple(trace)
            raise
        result = ExecutionResult(
            status="completed" if plan.actions else "no_op",
            trace=tuple(trace),
        )
        self.last_trace = result.trace
        return result

    def _validate_plan(self, plan: MutationPlan) -> None:
        if (
            not isinstance(plan.actions, tuple)
            or not all(isinstance(action, Mutation) for action in plan.actions)
            or not isinstance(plan.capability_bindings, tuple)
            or not all(
                isinstance(binding, CapabilityBinding)
                for binding in plan.capability_bindings
            )
        ):
            raise PlanValidationError("complete plan validation failed")

        if (
            plan.candidate_digest != self.candidate_digest
            or plan.implementation_manifest_digest
            != self.implementation_manifest_digest
            or not _is_prefixed_identity(plan.run_identity, "run:")
            or not _is_prefixed_identity(
                plan.execution_domain_identity, "execution-domain:"
            )
            or not _is_prefixed_identity(
                plan.captured_state_identity, "captured-state:"
            )
            or any(
                not isinstance(action.step_id, str)
                or not isinstance(action.surface, str)
                or not action.surface
                or not _is_prefixed_identity(action.route, "route:")
                or not isinstance(action.operation, str)
                or not isinstance(action.capability_binding, CapabilityBinding)
                or action.compensation != "restore_captured_pre_state"
                or not _is_state_value(action.before)
                or not _is_state_value(action.after)
                for action in plan.actions
            )
            or any(
                not _is_prefixed_identity(
                    binding.capability_identity, "capability:"
                )
                or not _is_digest(binding.capability_digest)
                or not _is_digest(binding.manager_version_evidence_digest)
                for binding in plan.capability_bindings
            )
        ):
            raise PlanValidationError("complete plan validation failed")

        step_ids = [action.step_id for action in plan.actions]
        surfaces = [action.surface for action in plan.actions]
        capability_bindings = plan.capability_bindings
        plan_bindings = (
            plan.candidate_digest,
            plan.implementation_manifest_digest,
            plan.catalog_digest,
            plan.lock_digest,
            plan.plan_digest,
            plan.capability_set_digest,
            plan.captured_state_digest,
        )
        try:
            expected_plan_digest = plan_actions_digest(plan.actions)
            expected_capability_set_digest = capability_set_digest(
                capability_bindings
            )
        except (TypeError, ValueError):
            raise PlanValidationError("complete plan validation failed") from None
        if (
            any(not _is_digest(binding) for binding in plan_bindings)
            or len(step_ids) != len(set(step_ids))
            or len(surfaces) != len(set(surfaces))
            or step_ids != [f"step-{index:03d}" for index in range(len(step_ids))]
            or plan.plan_digest != expected_plan_digest
            or not capability_bindings
            or capability_bindings != tuple(sorted(capability_bindings))
            or len(capability_bindings) != len(set(capability_bindings))
            or len({binding.capability_identity for binding in capability_bindings})
            != len(capability_bindings)
            or plan.capability_set_digest
            != expected_capability_set_digest
            or any(
                action.capability_binding not in capability_bindings
                for action in plan.actions
            )
            or any(
                states_equal(action.before, action.after)
                for action in plan.actions
            )
            or any(
                not isinstance(action.operation, str)
                or action.operation not in MUTATING_OPERATIONS
                for action in plan.actions
            )
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
            "action_identity": mutation_identity(action),
            "ordinal": int(action.step_id.removeprefix("step-")),
            "run_identity": plan.run_identity,
            "execution_domain_identity": plan.execution_domain_identity,
            "phase": phase,
            "phase_history": [phase],
            "invocation_state": "not_started",
            "candidate_digest": plan.candidate_digest,
            "implementation_manifest_digest": plan.implementation_manifest_digest,
            "catalog_digest": plan.catalog_digest,
            "lock_digest": plan.lock_digest,
            "plan_digest": plan.plan_digest,
            "capability_set_digest": plan.capability_set_digest,
            "captured_state_identity": plan.captured_state_identity,
            "captured_state_digest": plan.captured_state_digest,
            "route_capability_binding": capability_binding_payload(
                action.capability_binding
            ),
            "route_digest": canonical_digest(action.route),
            "operation_digest": canonical_digest(action.operation),
            "compensation_operation": action.compensation,
            "pre_state_digest": canonical_digest(state_payload(action.before)),
            "expected_post_state_digest": canonical_digest(
                state_payload(action.after)
            ),
            "pre_state": state_payload(action.before),
            "expected_post_state": state_payload(action.after),
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
        history = actual.get("phase_history")
        if (
            set(actual) != CHECKPOINT_FIELDS
            or any(
                not json_values_equal(actual.get(field), expected.get(field))
                for field in BINDING_FIELDS
            )
            or not isinstance(history, list)
            or actual.get("invocation_state") not in {"not_started", "started"}
            or (
                actual.get("phase") == "completed"
                and actual.get("invocation_state") != "started"
            )
            or tuple(history) not in CHECKPOINT_PHASE_HISTORIES
            or history[-1] != actual.get("phase")
        ):
            raise BindingMismatchError(str(expected.get("step_id")))

    def _apply_value(self, surface: str, value: JsonValue) -> None:
        if value is MISSING:
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
            phase = checkpoint.get("phase")
            invocation_started = checkpoint.get("invocation_state") == "started"
            if phase == "prepared" and states_equal(current, action.before):
                self._advance_phase(checkpoint, "compensating")
                self._write_checkpoint(
                    checkpoint,
                    fail="compensating_write",
                    action=action,
                    failures=failures,
                )
                trace.append(f"compensating:{action.step_id}")
                self._advance_phase(checkpoint, "compensated")
                self._write_checkpoint(
                    checkpoint,
                    fail="compensated_write",
                    action=action,
                    failures=failures,
                )
                trace.append(f"compensated:{action.step_id}")
                continue
            if (
                phase not in {"prepared", "completed"}
                or not invocation_started
                or not states_equal(
                current, action.after
                )
            ):
                self._advance_phase(checkpoint, "compensation_blocked")
                self._write_checkpoint(
                    checkpoint,
                    fail="compensation_blocked_write",
                    action=action,
                    failures=failures,
                )
                raise ConcurrentChangeError(action.surface)
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

    def compensate(self, plan: MutationPlan) -> ExecutionResult:
        """Explicitly authorize rollback when no durable intent was persisted."""

        return self._recover_compensation(plan, allow_initiation=True)

    def recover_compensation(self, plan: MutationPlan) -> ExecutionResult:
        """Infer and finish rollback only from durable compensation intent."""

        return self._recover_compensation(plan, allow_initiation=False)

    def _recover_compensation(
        self,
        plan: MutationPlan,
        *,
        allow_initiation: bool,
    ) -> ExecutionResult:
        """Audit and finish compensation without replaying forward work."""

        self._validate_plan(plan)
        trace = []
        actions = {action.step_id: action for action in plan.actions}
        checkpoints = self.checkpoints()
        unknown_step_ids = set(checkpoints) - set(actions)
        if unknown_step_ids:
            raise BindingMismatchError(sorted(unknown_step_ids)[0])
        for step_id, checkpoint in sorted(checkpoints.items(), reverse=True):
            action = actions[step_id]
            expected = self._checkpoint(plan, action, "prepared")
            self._validate_checkpoint_binding(checkpoint, expected)
        if any(
            checkpoint["phase"] == "compensation_blocked"
            for checkpoint in checkpoints.values()
        ):
            raise CompensationBlockedError("rollback requires operator disposition")
        if not allow_initiation and not any(
            checkpoint["phase"] in {"compensating", "compensated"}
            for checkpoint in checkpoints.values()
        ):
            raise HistoricalCheckpointError("no durable rollback intent")

        for action in reversed(plan.actions):
            step_id = action.step_id
            checkpoint = checkpoints.get(step_id)
            if checkpoint is None:
                continue
            phase = checkpoint["phase"]
            invocation_started = checkpoint.get("invocation_state") == "started"
            current = deepcopy(self.adapter.state.get(action.surface, MISSING))

            if phase == "compensated":
                if not states_equal(current, action.before):
                    raise ConcurrentChangeError(action.surface)
                trace.append(f"audit:{step_id}:pre_state")
                continue

            if phase not in {"prepared", "completed", "compensating"}:
                raise CompensationBlockedError(step_id)
            if phase == "completed" and (
                not invocation_started
                or not states_equal(current, action.after)
            ):
                self._advance_phase(checkpoint, "compensation_blocked")
                self._write_checkpoint(
                    checkpoint,
                    fail="compensation_blocked_write",
                    action=action,
                    failures=set(),
                )
                raise ConcurrentChangeError(action.surface)

            if phase == "prepared" and not (
                states_equal(current, action.before)
                or (
                    invocation_started
                    and states_equal(current, action.after)
                )
            ):
                self._advance_phase(checkpoint, "compensation_blocked")
                self._write_checkpoint(
                    checkpoint,
                    fail="compensation_blocked_write",
                    action=action,
                    failures=set(),
                )
                raise ConcurrentChangeError(action.surface)

            if phase == "compensating" and not (
                states_equal(current, action.before)
                or (
                    invocation_started
                    and states_equal(current, action.after)
                )
            ):
                self._advance_phase(checkpoint, "compensation_blocked")
                self._write_checkpoint(
                    checkpoint,
                    fail="compensation_blocked_write",
                    action=action,
                    failures=set(),
                )
                raise ConcurrentChangeError(action.surface)

            if phase != "compensating":
                self._advance_phase(checkpoint, "compensating")
                self._write_checkpoint(
                    checkpoint,
                    fail="compensating_write",
                    action=action,
                    failures=set(),
                )
            if states_equal(current, action.after):
                trace.append(f"audit:{step_id}:post_state")
                self._apply_value(action.surface, action.before)
            else:
                trace.append(f"audit:{step_id}:pre_state")
            self._advance_phase(checkpoint, "compensated")
            self._write_checkpoint(
                checkpoint,
                fail="compensated_write",
                action=action,
                failures=set(),
            )
            trace.append(f"compensated:{step_id}")
        if any(
            checkpoint["phase"] != "compensated"
            for checkpoint in self.checkpoints().values()
        ):
            raise CompensationBlockedError("rollback did not reach a terminal state")
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
        catalog: Mapping[str, JsonValue],
        lock: Mapping[str, JsonValue],
        *,
        validate_pair: UpdateValidator,
    ) -> UpdateProposal:
        proposed_catalog = deepcopy(dict(catalog))
        proposed_lock = deepcopy(dict(lock))
        validation_result = validate_pair(proposed_catalog, proposed_lock)
        if (
            proposed_lock.get("catalog_digest") != canonical_digest(proposed_catalog)
            or validation_result.diagnostics
        ):
            raise BindingMismatchError("update catalog/lock digest")
        return UpdateProposal(catalog=proposed_catalog, lock=proposed_lock)

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
            {
                "revision": revision,
                "content_base64": base64.b64encode(artifact).decode("ascii"),
                "content_digest": expected_digest,
            },
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
        if not states_equal(self.adapter.state[winner_surface], winner_value):
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
        digest = canonical_digest(state_payload(value))
        catalog_digest = f"sha256:{'1' * 64}"
        inventory_digest = f"sha256:{'8' * 64}"
        observation = ImportedObservation(
            observation_identity=imported_observation_identity(
                surface=surface,
                digest=digest,
                catalog_digest=catalog_digest,
                inventory_digest=inventory_digest,
            ),
            surface=surface,
            value=value,
            digest=digest,
            catalog_digest=catalog_digest,
            inventory_digest=inventory_digest,
        )
        self._imports[observation.observation_identity] = deepcopy(observation)
        return observation

    def adopt(self, observation: ImportedObservation) -> AdoptionProposal:
        expected_identity = imported_observation_identity(
            surface=observation.surface,
            digest=observation.digest,
            catalog_digest=observation.catalog_digest,
            inventory_digest=observation.inventory_digest,
        )
        registered = self._imports.get(observation.observation_identity)
        if (
            observation.observation_identity != expected_identity
            or registered != observation
        ):
            raise BindingMismatchError(observation.surface)
        current = self.adapter.state.get(observation.surface, MISSING)
        if (
            canonical_digest(state_payload(observation.value)) != observation.digest
            or canonical_digest(state_payload(current)) != observation.digest
        ):
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
        if self._adopted.get(surface) != canonical_digest(state_payload(current)):
            return RetirementProposal(status="report_only")
        return RetirementProposal(
            status="proposed",
            plan=self.plan({surface: MISSING}),
        )

    def audit(self, desired_state: DesiredState) -> StatusResult:
        drift = any(
            not states_equal(self.adapter.state.get(surface, MISSING), desired)
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
        if baseline.get("reviewed") is not True:
            raise BindingMismatchError(surface)
        state = self.adapter.state.get(surface)
        if not isinstance(state, dict) or "observed_version" not in state:
            raise ConcurrentChangeError(surface)
        observed = state["observed_version"]
        return StatusResult(
            status=(
                "converged"
                if json_values_equal(observed, baseline.get("observed_version"))
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
        catalog: Mapping[str, JsonValue],
        lock: Mapping[str, JsonValue],
        *,
        validate_pair: UpdateValidator,
    ) -> UpdateProposal:
        return self.propose_update(
            catalog,
            lock,
            validate_pair=validate_pair,
        )

    def capture_standalone(self, path: Path) -> dict[str, JsonValue]:
        path = self._normalized_standalone_path(path)
        self._assert_no_symlink_parent(path)
        return self._capture_node(path)

    def restore_standalone(
        self,
        path: Path,
        snapshot: Mapping[str, JsonValue],
    ) -> None:
        path = self._normalized_standalone_path(path)
        self._assert_no_symlink_parent(path)
        self._validate_snapshot(path, snapshot)
        self._remove_node(path)
        self._restore_node(path, snapshot)

    def _normalized_standalone_path(self, path: Path) -> Path:
        normalized = Path(os.path.abspath(os.fspath(path)))
        root = Path(os.path.abspath(os.fspath(self.standalone_root)))
        try:
            normalized.relative_to(root)
        except ValueError as error:
            raise ValueError("standalone path escaped fixture root") from error
        return normalized

    def _assert_no_symlink_parent(self, path: Path) -> None:
        root = Path(os.path.abspath(os.fspath(self.standalone_root)))
        if root.is_symlink():
            raise ConcurrentChangeError(str(root))
        relative = path.relative_to(root)
        current = root
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
        path = self._normalized_standalone_path(path)
        self._assert_no_symlink_parent(path)
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

    def _validate_snapshot(
        self,
        path: Path,
        snapshot: Mapping[str, JsonValue],
    ) -> None:
        path = self._normalized_standalone_path(path)
        if not isinstance(snapshot, Mapping):
            raise ValueError("invalid snapshot structure")
        kind = snapshot.get("kind")
        mode = snapshot.get("mode")
        if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
            raise ValueError("invalid snapshot mode")

        if kind == "regular_file":
            if set(snapshot) != {
                "kind",
                "mode",
                "content_base64",
                "content_digest",
            }:
                raise ValueError("invalid snapshot regular-file shape")
            encoded = snapshot.get("content_base64")
            if not isinstance(encoded, str):
                raise ValueError("invalid snapshot content")
            try:
                base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError("invalid snapshot content") from error
            if snapshot.get("content_digest") != canonical_digest(
                {"content_base64": encoded}
            ):
                raise ValueError("invalid snapshot content digest")
            return

        if kind == "symlink":
            if set(snapshot) != {
                "kind",
                "mode",
                "link_text",
                "resolved_target",
                "broken",
            }:
                raise ValueError("invalid snapshot symlink shape")
            link_text = snapshot.get("link_text")
            resolved_target = snapshot.get("resolved_target")
            if (
                not isinstance(link_text, str)
                or not link_text
                or "\x00" in link_text
                or not isinstance(resolved_target, str)
                or not isinstance(snapshot.get("broken"), bool)
                or str((path.parent / link_text).resolve(strict=False))
                != resolved_target
            ):
                raise ValueError("invalid snapshot symlink evidence")
            captured_target_exists = (path.parent / link_text).exists()
            if (not captured_target_exists) != snapshot.get("broken"):
                raise ConcurrentChangeError(str(path))
            return

        if kind == "directory":
            if set(snapshot) != {
                "kind",
                "mode",
                "children",
                "tree_digest",
            }:
                raise ValueError("invalid snapshot directory shape")
            children = snapshot.get("children")
            if not isinstance(children, Mapping):
                raise ValueError("invalid snapshot children")
            if snapshot.get("tree_digest") != canonical_digest(children):
                raise ValueError("invalid snapshot tree digest")
            for name, child in children.items():
                if (
                    not isinstance(name, str)
                    or name in {"", ".", ".."}
                    or "/" in name
                    or "\\" in name
                    or "\x00" in name
                    or not isinstance(child, Mapping)
                ):
                    raise ValueError("invalid snapshot child name")
                self._validate_snapshot(path / name, child)
            return

        raise ValueError("invalid snapshot kind")
