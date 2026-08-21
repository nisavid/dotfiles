"""Admission of complete plan-action projections before checkpointing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from ._json_schema import validate_document
from .canonical import (
    canonical_json_bytes,
    canonical_json_sha256,
    strict_load_json_bytes,
)
from .model import (
    Diagnostic,
    FrozenJsonObject,
    PlanNode,
    ValidatedPlan,
    freeze_json,
    thaw_json,
)
from .secrets import contains_literal_credential

MAX_PLAN_ACTION_SET_BYTES = 16 * 1024 * 1024
_SCHEMA_NAME = "plan-action-set-v1.schema.json"
_SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "schemas"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class PlanActionSetTrust:
    """Independently validated plan and expected complete projection digest."""

    validated_plan: ValidatedPlan
    expected_action_set_digest: str

    def __post_init__(self) -> None:
        if type(self.validated_plan) is not ValidatedPlan:
            raise TypeError("plan-action-set trust requires one validated plan")
        if (
            type(self.expected_action_set_digest) is not str
            or _DIGEST.fullmatch(self.expected_action_set_digest) is None
        ):
            raise ValueError("expected plan-action-set digest is invalid")


@dataclass(frozen=True, slots=True)
class AdmittedPlanActionSet:
    """One immutable projection admitted against all currently provable bindings.

    Admission does not make the plan executable. Expected post-state, physical
    target, capture, and prepared-action authority require later production
    seams before any checkpoint or adapter mutation is allowed.
    """

    document: FrozenJsonObject
    canonical_bytes: bytes
    action_set_digest: str

    def __post_init__(self) -> None:
        if type(self.document) is not FrozenJsonObject:
            raise TypeError("admitted plan-action set must be frozen JSON")
        if type(self.canonical_bytes) is not bytes:
            raise TypeError("admitted plan-action set bytes must be immutable")
        if self.canonical_bytes != canonical_json_bytes(self.document):
            raise ValueError("admitted plan-action set bytes must be canonical")
        if (
            type(self.action_set_digest) is not str
            or _DIGEST.fullmatch(self.action_set_digest) is None
            or self.document.get("action_set_digest") != self.action_set_digest
        ):
            raise ValueError("admitted plan-action-set digest is invalid")


@dataclass(frozen=True, slots=True)
class PlanActionSetRejection:
    """A closed, secret-free refusal to admit one plan-action projection."""

    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self) -> None:
        if not self.diagnostics or any(
            type(diagnostic) is not Diagnostic for diagnostic in self.diagnostics
        ):
            raise ValueError("plan-action-set rejection requires typed diagnostics")


PlanActionSetResult: TypeAlias = AdmittedPlanActionSet | PlanActionSetRejection


def admit_plan_action_set(
    raw_document: bytes,
    trust: PlanActionSetTrust,
) -> PlanActionSetResult:
    """Strictly admit one complete projection without granting execution authority."""

    if type(trust) is not PlanActionSetTrust:
        raise TypeError("plan-action-set admission requires typed trust")
    if (
        type(raw_document) is not bytes
        or len(raw_document) > MAX_PLAN_ACTION_SET_BYTES
    ):
        return _rejection(
            "PLAN_ACTION_SET_BYTES_INVALID",
            "The plan-action set is not one bounded raw byte stream.",
        )
    try:
        document = strict_load_json_bytes(raw_document)
        canonical_bytes = canonical_json_bytes(document)
    except (RecursionError, UnicodeError, ValueError, TypeError):
        return _rejection(
            "PLAN_ACTION_SET_JSON_INVALID",
            "The plan-action set is not unambiguous strict UTF-8 JSON.",
        )
    if len(canonical_bytes) > MAX_PLAN_ACTION_SET_BYTES:
        return _rejection(
            "PLAN_ACTION_SET_JSON_INVALID",
            "The plan-action set exceeds its canonical byte bound.",
        )
    if not isinstance(document, FrozenJsonObject):
        return _rejection(
            "PLAN_ACTION_SET_SCHEMA_INVALID",
            "The plan-action set does not satisfy the checked-in closed schema.",
        )
    mutable_document = thaw_json(document)
    if type(mutable_document) is not dict or not validate_document(
        mutable_document,
        schema_directory=_SCHEMA_DIRECTORY,
        root_schema_name=_SCHEMA_NAME,
        allowed_schema_names=(_SCHEMA_NAME,),
    ):
        return _rejection(
            "PLAN_ACTION_SET_SCHEMA_INVALID",
            "The plan-action set does not satisfy the checked-in closed schema.",
        )
    if contains_literal_credential(mutable_document):
        return _rejection(
            "PLAN_ACTION_SET_LITERAL_SECRET",
            "The plan-action set contains credential-shaped literal material.",
        )
    diagnostics = _semantic_diagnostics(document, trust)
    if diagnostics:
        return PlanActionSetRejection(diagnostics)
    action_set_digest = document.get("action_set_digest")
    assert isinstance(action_set_digest, str)
    return AdmittedPlanActionSet(
        document=document,
        canonical_bytes=canonical_bytes,
        action_set_digest=action_set_digest,
    )


def _semantic_diagnostics(
    document: FrozenJsonObject,
    trust: PlanActionSetTrust,
) -> tuple[Diagnostic, ...]:
    plan = trust.validated_plan
    preimage = plan.preimage
    expected_top = {
        "candidate_identity": preimage.get("candidate_identity"),
        "implementation_manifest_digest": preimage.get(
            "implementation_manifest_digest"
        ),
        "plan_digest": plan.digest,
    }
    diagnostics: list[Diagnostic] = []
    if any(document.get(field) != value for field, value in expected_top.items()):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_SET_BINDING_MISMATCH",
                "The plan-action set does not match the validated plan authority.",
            )
        )

    actions = document.get("actions")
    assert isinstance(actions, tuple)
    typed_actions: list[FrozenJsonObject] = []
    mutation_nodes = tuple(node for node in plan.nodes if node.kind == "mutation")
    coordinates: list[tuple[int, str]] = []
    physical_targets: set[bytes] = set()
    for index, evidence in enumerate(actions):
        assert isinstance(evidence, FrozenJsonObject)
        typed_actions.append(evidence)
        payload = evidence.get("action_payload")
        assert isinstance(payload, FrozenJsonObject)
        identity = payload.get("action_identity")
        ordinal = payload.get("ordinal")
        if type(identity) is str and type(ordinal) is int:
            coordinates.append((ordinal, identity))

        if evidence.get("action_digest") != canonical_json_sha256(payload):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_DIGEST_INVALID",
                    "A plan action does not match its complete canonical digest.",
                )
            )
        if identity != _action_identity(payload):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_IDENTITY_INVALID",
                    "A plan action does not match its canonical execution coordinates.",
                )
            )
        desired_state = payload.get("desired_state")
        if payload.get("desired_state_digest") != canonical_json_sha256(desired_state):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_DESIRED_STATE_INVALID",
                    "A plan action desired state does not match its canonical digest.",
                )
            )
        node = mutation_nodes[index] if index < len(mutation_nodes) else None
        if node is None or not _matches_validated_plan(payload, node.definition, node):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
                    "A plan action is not the exact projection of its validated mutation.",
                )
            )
        if not _preconditions_match(payload, node.definition if node else None):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_PRECONDITION_INVALID",
                    "A plan action precondition does not repeat its proven authority.",
                )
            )
        target_diagnostics, target_keys = _target_diagnostics(payload)
        diagnostics.extend(target_diagnostics)
        for target_key in target_keys:
            if target_key in physical_targets:
                diagnostics.append(
                    _diagnostic(
                        "PLAN_ACTION_PHYSICAL_TARGET_DUPLICATE",
                        "One mutable physical target is claimed by more than one action.",
                    )
                )
            physical_targets.add(target_key)
        if not _secret_references_match(payload):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_SECRET_REFERENCE_INVALID",
                    "A provider does not consume exactly the declared secret references.",
                )
            )
        if not _verification_dependencies_match(payload):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_VERIFICATION_DEPENDENCY_INVALID",
                    "A verification dependency does not match its exact Claude write target.",
                )
            )

    expected_coordinates = tuple(
        (node.ordinal, node.identity) for node in mutation_nodes
    )
    if tuple(coordinates) != expected_coordinates or len(actions) != len(mutation_nodes):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_SET_MEMBERSHIP_INVALID",
                "The plan-action set is not the ordered all-and-only mutation projection.",
            )
        )
    canonical_actions = tuple(
        sorted(
            typed_actions,
            key=_action_sort_key,
        )
    )
    expected_set_digest = canonical_json_sha256(
        {
            "schema_version": document.get("schema_version"),
            "candidate_identity": document.get("candidate_identity"),
            "implementation_manifest_digest": document.get(
                "implementation_manifest_digest"
            ),
            "plan_digest": document.get("plan_digest"),
            "actions": canonical_actions,
        }
    )
    if (
        document.get("action_set_digest") != expected_set_digest
        or expected_set_digest != trust.expected_action_set_digest
    ):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_SET_DIGEST_INVALID",
                "The complete projection does not match its trusted canonical digest.",
            )
        )
    return tuple(sorted(set(diagnostics), key=_diagnostic_sort_key))


def _matches_validated_plan(
    payload: FrozenJsonObject,
    definition: FrozenJsonObject,
    node: PlanNode,
) -> bool:
    direct_fields = (
        "candidate_identity",
        "implementation_manifest_digest",
        "catalog_digest",
        "lock_digest",
        "capability_identity",
        "capability_digest",
        "manager_version_evidence_digest",
        "adapter_identity",
        "adapter_version",
        "harness",
        "route_identity",
        "route_digest",
        "equipment_identities",
        "controlled_equipment_identities",
        "activation_group",
        "surface_scope",
        "operation",
        "operation_disposition",
        "desired_state",
        "desired_state_digest",
        "secret_references",
    )
    route = definition.get("route_record")
    return (
        payload.get("action_identity") == node.identity
        and payload.get("ordinal") == node.ordinal
        and payload.get("plan_digest") is not None
        and all(payload.get(field) == definition.get(field) for field in direct_fields)
        and isinstance(route, FrozenJsonObject)
        and payload.get("provider") == route.get("provider")
    )


def _preconditions_match(
    payload: FrozenJsonObject,
    definition: FrozenJsonObject | None,
) -> bool:
    preconditions = payload.get("preconditions")
    if not isinstance(preconditions, FrozenJsonObject) or definition is None:
        return False
    route = definition.get("route_record")
    expected = {
        "candidate_identity": payload.get("candidate_identity"),
        "implementation_manifest_digest": payload.get(
            "implementation_manifest_digest"
        ),
        "catalog_digest": payload.get("catalog_digest"),
        "lock_digest": payload.get("lock_digest"),
        "plan_digest": payload.get("plan_digest"),
        "route_digest": payload.get("route_digest"),
        "capability_digest": payload.get("capability_digest"),
        "manager_version_evidence_digest": payload.get(
            "manager_version_evidence_digest"
        ),
        "adapter_identity": payload.get("adapter_identity"),
        "adapter_version": payload.get("adapter_version"),
        "control_owner": (
            route.get("control_owner") if isinstance(route, FrozenJsonObject) else None
        ),
        "activation_group": payload.get("activation_group"),
        "surface_scope": payload.get("surface_scope"),
        "prepared_checkpoint_required": True,
        "compare_before_mutate": True,
    }
    return preconditions == freeze_json(expected)


def _target_diagnostics(
    payload: FrozenJsonObject,
) -> tuple[list[Diagnostic], tuple[bytes, ...]]:
    targets = payload.get("write_targets")
    surface_scope = payload.get("surface_scope")
    assert isinstance(targets, tuple)
    assert isinstance(surface_scope, tuple)
    diagnostics: list[Diagnostic] = []
    target_keys: list[bytes] = []
    target_identities: list[str] = []
    target_surfaces: list[str] = []
    for target in targets:
        assert isinstance(target, FrozenJsonObject)
        target_payload = {
            key: value for key, value in target.items() if key != "target_identity"
        }
        if target.get("target_identity") != (
            "target:" + canonical_json_sha256(target_payload)
        ):
            diagnostics.append(
                _diagnostic(
                    "PLAN_ACTION_TARGET_IDENTITY_INVALID",
                    "A physical write target does not match its canonical identity.",
                )
            )
        target_surfaces.append(str(target.get("write_surface_identity")))
        target_identities.append(str(target.get("target_identity")))
        target_keys.append(
            canonical_json_bytes(
                {
                    "surface_kind": target.get("surface_kind"),
                    "locator": target.get("locator"),
                }
            )
        )
    if target_identities != sorted(set(target_identities)):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_TARGET_ORDER_INVALID",
                "Physical write targets are not in unique canonical identity order.",
            )
        )
    if tuple(sorted(target_surfaces)) != tuple(surface_scope):
        diagnostics.append(
            _diagnostic(
                "PLAN_ACTION_TARGET_SCOPE_INVALID",
                "Physical write targets do not cover the exact logical surface scope.",
            )
        )
    return diagnostics, tuple(target_keys)


def _secret_references_match(payload: FrozenJsonObject) -> bool:
    provider = payload.get("provider")
    declared = payload.get("secret_references")
    if not isinstance(provider, FrozenJsonObject) or not isinstance(declared, tuple):
        return False
    consumed: set[tuple[str, str]] = set()
    arguments = provider.get("arguments")
    if isinstance(arguments, tuple):
        for argument in arguments:
            if not isinstance(argument, FrozenJsonObject):
                continue
            environment = argument.get("secret_reference")
            profile = argument.get("secret_profile_reference")
            if type(environment) is str:
                consumed.add(("environment_variable", environment))
            if type(profile) is str:
                consumed.add(("secret_profile", profile))
    declared_set = {
        (str(reference.get("kind")), str(reference.get("name")))
        for reference in declared
        if isinstance(reference, FrozenJsonObject)
    }
    declared_order = tuple(
        canonical_json_bytes(reference)
        for reference in declared
        if isinstance(reference, FrozenJsonObject)
    )
    return (
        consumed == declared_set
        and len(declared_set) == len(declared)
        and declared_order == tuple(sorted(set(declared_order)))
    )


def _verification_dependencies_match(payload: FrozenJsonObject) -> bool:
    dependencies = payload.get("verification_dependencies")
    targets = payload.get("write_targets")
    if not isinstance(dependencies, tuple) or not isinstance(targets, tuple):
        return False
    target_by_surface: dict[str, FrozenJsonObject] = {}
    for target in targets:
        if not isinstance(target, FrozenJsonObject):
            return False
        surface = target.get("write_surface_identity")
        if type(surface) is not str or surface in target_by_surface:
            return False
        target_by_surface[surface] = target
    claimed_surfaces: set[str] = set()
    canonical_dependencies: list[bytes] = []
    for dependency in dependencies:
        if not isinstance(dependency, FrozenJsonObject):
            return False
        surface = dependency.get("write_surface_identity")
        if type(surface) is not str or surface in claimed_surfaces:
            return False
        claimed_surfaces.add(surface)
        canonical_dependencies.append(canonical_json_bytes(dependency))
        target = target_by_surface.get(surface)
        target_locator = (
            target.get("locator") if isinstance(target, FrozenJsonObject) else None
        )
        dependency_locator = dependency.get("target_locator")
        if (
            not isinstance(target, FrozenJsonObject)
            or target.get("surface_kind") != "claude_skill_entry"
            or target.get("equipment_identity")
            != dependency.get("equipment_identity")
            or not isinstance(target_locator, FrozenJsonObject)
            or not isinstance(dependency_locator, FrozenJsonObject)
        ):
            return False
        write_path = target_locator.get("path")
        dependency_path = dependency_locator.get("path")
        if (
            type(write_path) is not str
            or type(dependency_path) is not str
            or write_path.removeprefix("~/.claude/skills/")
            != dependency_path.removeprefix("~/.agents/skills/")
        ):
            return False
    return canonical_dependencies == sorted(set(canonical_dependencies))


def _action_identity(payload: FrozenJsonObject) -> str:
    return "action:" + canonical_json_sha256(
        {
            "plan_digest": payload.get("plan_digest"),
            "ordinal": payload.get("ordinal"),
            "route_id": payload.get("route_identity"),
            "operation": payload.get("operation"),
            "desired_state_digest": payload.get("desired_state_digest"),
        }
    )


def _action_sort_key(evidence: FrozenJsonObject) -> tuple[int, str]:
    payload = evidence.get("action_payload")
    assert isinstance(payload, FrozenJsonObject)
    ordinal = payload.get("ordinal")
    identity = payload.get("action_identity")
    assert type(ordinal) is int and type(identity) is str
    return ordinal, identity


def _diagnostic_sort_key(diagnostic: Diagnostic) -> tuple[str, str]:
    return diagnostic.code, diagnostic.message


def _diagnostic(code: str, message: str) -> Diagnostic:
    return Diagnostic(code, message, evidence_source="plan-action-set")


def _rejection(code: str, message: str) -> PlanActionSetRejection:
    return PlanActionSetRejection((_diagnostic(code, message),))
