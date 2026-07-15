"""Provider compatibility with explicit blocked candidate state."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from .model import deep_freeze, deep_thaw


class ProviderCompatibilityError(ValueError):
    pass


ROLES = {"llm", "embedding", "reranking"}
PLACEMENTS = {"local", "third-party-hosted", "private-remote"}
PROFILE_KEYS = {
    "id",
    "data_classes",
    "roles",
    "allowed_placements",
    "llm_failover",
}
PROVIDER_KEYS = {
    "id",
    "role",
    "placement",
    "data_classes",
    "transport",
    "tls",
    "credential",
    "readiness",
    "model",
    "contract",
    "state",
    "gates",
    "fallback",
}
ROLE_BINDING_KEYS = {"current", "desired"}
TRANSPORT_KEYS = {"protocol", "api"}
TLS_KEYS = {"server_name", "trust_roots"}
CREDENTIAL_KEYS = {"mode", "locator"}
READINESS_KEYS = {"ready", "version_compatible", "license_ready"}
MODEL_KEYS = {
    "artifact_id",
    "active_artifact_id",
    "revision",
    "active_revision",
    "reasoning_effort",
}
CONTRACT_KEYS = {
    "readiness_probe",
    "timeout_seconds",
    "no_payload_log",
    "api_compatible",
}
PROBE_KEYS = {"kind", "target"}
PROTOCOLS = {"https", "loopback"}
APIS = {
    "anthropic-messages",
    "openai-responses",
    "openai-compatible",
    "cohere-compatible",
}
CREDENTIAL_MODES = {"keychain", "oauth-home"}
SWITCH_KEYS = {
    "provider_id",
    "from_artifact_id",
    "from_revision",
    "to_artifact_id",
    "to_revision",
    "blue_green_rebuild",
    "approved",
}
REQUIRED_CANDIDATE_GATES = {
    "gpt-5.3-codex-spark": {
        "provider_adapter_sends_reasoning_effort",
    },
    "nisavid/MemReranker-4B-OptiQ-4bit": {
        "cohere_adapter_compatibility",
        "private_benchmark",
    },
}


def _closed(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ProviderCompatibilityError(
            f"{label} keys are closed (missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)})"
        )


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderCompatibilityError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True)
class CompatibilityResult:
    provider_id: str
    role: str
    state: str
    compatible: bool
    activatable: bool
    blocked_by: tuple[str, ...]
    fallback_provider_id: str | None
    placement: str
    artifact_id: str
    revision: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "role": self.role,
            "state": self.state,
            "compatible": self.compatible,
            "activatable": self.activatable,
            "blocked_by": list(self.blocked_by),
            "fallback_provider_id": self.fallback_provider_id,
            "placement": self.placement,
            "artifact_id": self.artifact_id,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class CompatibilityReport:
    profile_id: str
    role_bindings: Mapping[str, Mapping[str, str]]
    results: tuple[CompatibilityResult, ...]
    reranking_disposition: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "role_bindings", deep_freeze(self.role_bindings)
        )
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(
            self,
            "reranking_disposition",
            deep_freeze(self.reranking_disposition),
        )

    def result(self, provider_id: str) -> CompatibilityResult:
        for result in self.results:
            if result.provider_id == provider_id:
                return result
        raise ProviderCompatibilityError(
            f"no compatibility result for provider {provider_id}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "role_bindings": deep_thaw(self.role_bindings),
            "results": [result.to_dict() for result in self.results],
            "reranking_disposition": deep_thaw(self.reranking_disposition),
        }


def _validate_provider(provider: Mapping[str, Any]) -> None:
    _closed(provider, PROVIDER_KEYS, "provider")
    provider_id = _nonempty(provider["id"], "provider id")
    if provider["role"] not in ROLES:
        raise ProviderCompatibilityError(
            f"provider {provider_id} has invalid role"
        )
    placement = provider["placement"]
    if placement not in PLACEMENTS:
        raise ProviderCompatibilityError(
            f"provider {provider_id} has invalid placement"
        )
    data_classes = provider["data_classes"]
    if (
        not isinstance(data_classes, list)
        or not data_classes
        or len(data_classes) != len(set(data_classes))
        or any(
            not isinstance(value, str) or not value for value in data_classes
        )
    ):
        raise ProviderCompatibilityError(
            f"provider {provider_id} data classes must be unique"
        )

    transport = provider["transport"]
    if not isinstance(transport, Mapping):
        raise ProviderCompatibilityError(
            f"provider {provider_id} transport must be an object"
        )
    _closed(transport, TRANSPORT_KEYS, "transport")
    if transport["protocol"] not in PROTOCOLS:
        raise ProviderCompatibilityError(
            f"provider {provider_id} transport protocol is incompatible"
        )
    if transport["api"] not in APIS:
        raise ProviderCompatibilityError(
            f"provider {provider_id} transport API is incompatible"
        )

    tls = provider["tls"]
    if placement == "private-remote":
        if not isinstance(tls, Mapping) or set(tls) != TLS_KEYS:
            raise ProviderCompatibilityError(
                "private-remote provider "
                f"{provider_id} requires TLS identity and trust roots"
            )
        _nonempty(tls["server_name"], "TLS server identity")
        roots = tls["trust_roots"]
        if (
            not isinstance(roots, list)
            or not roots
            or any(not isinstance(root, str) or not root for root in roots)
        ):
            raise ProviderCompatibilityError(
                "private-remote provider "
                f"{provider_id} requires TLS identity and trust roots"
            )
        if transport["protocol"] != "https":
            raise ProviderCompatibilityError(
                "private-remote provider "
                f"{provider_id} requires TLS identity over https"
            )
    elif tls is not None:
        if not isinstance(tls, Mapping):
            raise ProviderCompatibilityError(
                f"provider {provider_id} TLS policy must be null or an object"
            )
        _closed(tls, TLS_KEYS, "TLS")

    credential = provider["credential"]
    if placement == "local":
        if credential is not None:
            if not isinstance(credential, Mapping):
                raise ProviderCompatibilityError(
                    f"provider {provider_id} credential must be a locator"
                )
            _closed(credential, CREDENTIAL_KEYS, "credential")
            _validate_credential(credential)
    else:
        if not isinstance(credential, Mapping):
            raise ProviderCompatibilityError(
                f"provider {provider_id} credential must be a locator "
                "without a value"
            )
        _closed(credential, CREDENTIAL_KEYS, "credential")
        _validate_credential(credential)

    readiness = provider["readiness"]
    if not isinstance(readiness, Mapping):
        raise ProviderCompatibilityError(
            f"provider {provider_id} readiness must be an object"
        )
    _closed(readiness, READINESS_KEYS, "readiness")
    if any(not isinstance(readiness[key], bool) for key in READINESS_KEYS):
        raise ProviderCompatibilityError(
            f"provider {provider_id} readiness gates must be boolean"
        )

    model = provider["model"]
    if not isinstance(model, Mapping):
        raise ProviderCompatibilityError(
            f"provider {provider_id} model must be an object"
        )
    _closed(model, MODEL_KEYS, "model")
    for key in MODEL_KEYS - {"reasoning_effort"}:
        _nonempty(model[key], f"model {key}")
    effort = model["reasoning_effort"]
    if provider["role"] == "llm":
        _nonempty(effort, "LLM reasoning effort")
    elif effort is not None:
        raise ProviderCompatibilityError(
            f"provider {provider_id} non-LLM reasoning effort must be null"
        )

    contract = provider["contract"]
    if not isinstance(contract, Mapping):
        raise ProviderCompatibilityError(
            f"provider {provider_id} contract must be an object"
        )
    _closed(contract, CONTRACT_KEYS, "provider contract")
    probe = contract["readiness_probe"]
    if not isinstance(probe, Mapping):
        raise ProviderCompatibilityError(
            f"provider {provider_id} requires a readiness probe"
        )
    _closed(probe, PROBE_KEYS, "readiness probe")
    if probe["kind"] not in {"http", "process"}:
        raise ProviderCompatibilityError(
            f"provider {provider_id} readiness probe kind is invalid"
        )
    _nonempty(probe["target"], "readiness probe target")
    timeout = contract["timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ProviderCompatibilityError(
            f"provider {provider_id} timeout must be from 1 to 300 seconds"
        )
    if contract["no_payload_log"] is not True:
        raise ProviderCompatibilityError(
            f"provider {provider_id} must guarantee no payload logging"
        )
    if contract["api_compatible"] is not True:
        raise ProviderCompatibilityError(
            f"provider {provider_id} API compatibility gate failed"
        )
    if provider["state"] not in {"current", "desired", "fallback"}:
        raise ProviderCompatibilityError(
            f"provider {provider_id} has invalid state"
        )
    gates = provider["gates"]
    if (
        not isinstance(gates, Mapping)
        or any(not isinstance(gate, str) or not gate for gate in gates)
        or any(not isinstance(passed, bool) for passed in gates.values())
    ):
        raise ProviderCompatibilityError(
            f"provider {provider_id} gates must map unique names to booleans"
        )
    artifact_id = provider["model"]["artifact_id"]
    required_gates = REQUIRED_CANDIDATE_GATES.get(artifact_id, set())
    if provider["state"] == "desired" and not required_gates.issubset(gates):
        raise ProviderCompatibilityError(
            f"provider {provider_id} is missing required candidate gates"
        )
    if provider["fallback"] is not None:
        _nonempty(provider["fallback"], "fallback provider id")


def _validate_credential(credential: Mapping[str, Any]) -> None:
    mode = credential["mode"]
    locator = credential["locator"]
    if mode not in CREDENTIAL_MODES:
        raise ProviderCompatibilityError("credential mode is not allowed")
    expected_prefix = f"{mode}:"
    if (
        not isinstance(locator, str)
        or not locator.startswith(expected_prefix)
        or not re.fullmatch(
            rf"{re.escape(expected_prefix)}[a-z0-9][a-z0-9._-]*",
            locator,
        )
    ):
        raise ProviderCompatibilityError("credential locator shape is invalid")


def _switches_by_provider(
    revision_switches: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    switches: dict[str, Mapping[str, Any]] = {}
    for switch in revision_switches:
        if not isinstance(switch, Mapping):
            raise ProviderCompatibilityError(
                "revision switches must be objects"
            )
        _closed(switch, SWITCH_KEYS, "revision switch")
        provider_id = _nonempty(
            switch["provider_id"], "revision switch provider"
        )
        if provider_id in switches:
            raise ProviderCompatibilityError(
                f"duplicate revision switch for {provider_id}"
            )
        for key in (
            "from_artifact_id",
            "from_revision",
            "to_artifact_id",
            "to_revision",
        ):
            _nonempty(switch[key], f"revision switch {key}")
        if not isinstance(switch["blue_green_rebuild"], bool) or not isinstance(
            switch["approved"], bool
        ):
            raise ProviderCompatibilityError(
                "revision switch gates must be boolean"
            )
        switches[provider_id] = switch
    return switches


def _exact_switch(
    switch: Mapping[str, Any] | None,
    *,
    from_artifact_id: str,
    from_revision: str,
    to_artifact_id: str,
    to_revision: str,
    require_blue_green: bool,
) -> bool:
    if switch is None:
        return False
    return bool(
        switch["approved"]
        and (not require_blue_green or switch["blue_green_rebuild"])
        and switch["from_artifact_id"] == from_artifact_id
        and switch["from_revision"] == from_revision
        and switch["to_artifact_id"] == to_artifact_id
        and switch["to_revision"] == to_revision
    )


def validate_provider_compatibility(
    profile: Mapping[str, Any],
    providers: Sequence[Mapping[str, Any]],
    storage_state: Mapping[str, Any],
    *,
    revision_switches: Sequence[Mapping[str, Any]] = (),
) -> CompatibilityReport:
    if not isinstance(profile, Mapping):
        raise ProviderCompatibilityError("profile must be an object")
    _closed(profile, PROFILE_KEYS, "profile")
    profile_id = _nonempty(profile["id"], "profile id")
    data_classes = profile["data_classes"]
    if (
        not isinstance(data_classes, list)
        or not data_classes
        or len(data_classes) != len(set(data_classes))
    ):
        raise ProviderCompatibilityError(
            "profile data_classes must be unique and non-empty"
        )
    roles = profile["roles"]
    if not isinstance(roles, Mapping) or set(roles) != ROLES:
        raise ProviderCompatibilityError(
            "profile must bind llm, embedding, and reranking independently"
        )
    allowed_placements = profile["allowed_placements"]
    if not isinstance(allowed_placements, Mapping) or set(
        allowed_placements
    ) != set(data_classes):
        raise ProviderCompatibilityError(
            "profile allowed_placements must define every data class"
        )
    for data_class, placements in allowed_placements.items():
        if (
            not isinstance(placements, list)
            or not placements
            or any(value not in PLACEMENTS for value in placements)
        ):
            raise ProviderCompatibilityError(
                f"allowed placements for {data_class} are invalid"
            )
    llm_failover = profile["llm_failover"]
    if (
        not isinstance(llm_failover, list)
        or len(llm_failover) != len(set(llm_failover))
        or any(not isinstance(value, str) for value in llm_failover)
    ):
        raise ProviderCompatibilityError(
            "llm_failover must be a unique ordered provider list"
        )

    provider_by_id: dict[str, Mapping[str, Any]] = {}
    for provider in providers:
        if not isinstance(provider, Mapping):
            raise ProviderCompatibilityError("providers must be objects")
        _validate_provider(provider)
        if provider["id"] in provider_by_id:
            raise ProviderCompatibilityError(
                f"duplicate provider id: {provider['id']}"
            )
        provider_by_id[provider["id"]] = provider
    for provider in providers:
        fallback_id = provider["fallback"]
        if fallback_id is None:
            continue
        fallback = provider_by_id.get(fallback_id)
        if (
            provider["role"] != "reranking"
            or fallback is None
            or fallback["role"] != "reranking"
        ):
            raise ProviderCompatibilityError(
                f"reranker fallback for {provider['id']} must reference a "
                "reranking provider"
            )

    selected: list[Mapping[str, Any]] = []
    normalized_bindings: dict[str, dict[str, str]] = {}
    for role in sorted(ROLES):
        binding = roles[role]
        if (
            not isinstance(binding, Mapping)
            or not set(binding).issubset(ROLE_BINDING_KEYS)
            or "current" not in binding
        ):
            raise ProviderCompatibilityError(
                f"role {role} binding must have current and optional "
                "desired provider"
            )
        normalized_bindings[role] = dict(binding)
        for selection, provider_id in binding.items():
            if provider_id not in provider_by_id:
                raise ProviderCompatibilityError(
                    f"role {role} references unknown provider {provider_id}"
                )
            provider = provider_by_id[provider_id]
            if provider["role"] != role:
                raise ProviderCompatibilityError(
                    f"provider {provider_id} cannot serve role {role}"
                )
            if selection == "current" and provider["state"] not in {
                "current",
                "fallback",
            }:
                raise ProviderCompatibilityError(
                    f"current role {role} must reference current provider state"
                )
            if selection == "desired" and provider["state"] != "desired":
                raise ProviderCompatibilityError(
                    f"desired role {role} must reference desired provider state"
                )
            if provider not in selected:
                selected.append(provider)

    for provider_id in llm_failover:
        provider = provider_by_id.get(provider_id)
        if provider is None or provider["role"] != "llm":
            raise ProviderCompatibilityError(
                "llm_failover must reference declared LLM providers"
            )
    for provider in tuple(selected):
        fallback_id = provider["fallback"]
        if fallback_id is not None:
            fallback = provider_by_id[fallback_id]
            if fallback not in selected:
                selected.append(fallback)
    for role in ("llm", "reranking"):
        if "desired" not in normalized_bindings[role]:
            raise ProviderCompatibilityError(
                f"role {role} must represent the desired candidate"
            )

    current_llm = provider_by_id[normalized_bindings["llm"]["current"]]
    if current_llm["model"]["artifact_id"] != "claude-code":
        raise ProviderCompatibilityError(
            "current LLM must remain the live Claude Code provider"
        )
    current_reranker = provider_by_id[
        normalized_bindings["reranking"]["current"]
    ]
    if (
        current_reranker["model"]["artifact_id"]
        != "nisavid/mxbai-rerank-large-v2-mlx-4bit"
    ):
        raise ProviderCompatibilityError(
            "current reranker must remain the live Jina MLX provider"
        )
    desired_llm = provider_by_id[normalized_bindings["llm"]["desired"]]
    if (
        desired_llm["model"]["artifact_id"] != "gpt-5.3-codex-spark"
        or desired_llm["model"]["reasoning_effort"] != "xhigh"
    ):
        raise ProviderCompatibilityError(
            "desired LLM must be GPT-5.3 Codex Spark at xhigh"
        )
    desired_reranker = provider_by_id[
        normalized_bindings["reranking"]["desired"]
    ]
    if (
        desired_reranker["model"]["artifact_id"]
        != "nisavid/MemReranker-4B-OptiQ-4bit"
    ):
        raise ProviderCompatibilityError(
            "desired reranker must be the blocked MemReranker candidate"
        )

    switches = _switches_by_provider(revision_switches)
    selected_ids = {provider["id"] for provider in selected}
    for provider_id, switch in switches.items():
        if provider_id not in selected_ids:
            raise ProviderCompatibilityError(
                f"revision switch references unselected provider {provider_id}"
            )
        model = provider_by_id[provider_id]["model"]
        if (
            model["artifact_id"] == model["active_artifact_id"]
            and model["revision"] == model["active_revision"]
        ):
            raise ProviderCompatibilityError(
                f"revision switch for {provider_id} has no target drift"
            )
    if set(storage_state) != {
        "populated",
        "embedding_artifact_id",
        "embedding_revision",
    }:
        raise ProviderCompatibilityError("storage state keys are closed")
    if not isinstance(storage_state["populated"], bool):
        raise ProviderCompatibilityError("storage populated must be boolean")
    _nonempty(
        storage_state["embedding_artifact_id"], "storage embedding artifact"
    )
    _nonempty(storage_state["embedding_revision"], "storage embedding revision")

    results: list[CompatibilityResult] = []
    for provider in selected:
        provider_id = provider["id"]
        role = provider["role"]
        placement = provider["placement"]
        blocked: list[str] = []
        for data_class in data_classes:
            if data_class not in provider["data_classes"]:
                raise ProviderCompatibilityError(
                    f"provider {provider_id} cannot receive {data_class} data"
                )
            if placement not in allowed_placements[data_class]:
                raise ProviderCompatibilityError(
                    f"provider {provider_id} placement is forbidden for "
                    f"{data_class}"
                )
        for gate in ("ready", "version_compatible", "license_ready"):
            if not provider["readiness"][gate]:
                blocked.append(gate)
        blocked.extend(
            gate for gate, passed in provider["gates"].items() if not passed
        )

        model = provider["model"]
        switch = switches.get(provider_id)
        if (
            model["artifact_id"] != model["active_artifact_id"]
            or model["revision"] != model["active_revision"]
        ):
            from_artifact = model["active_artifact_id"]
            from_revision = model["active_revision"]
            if role == "embedding" and storage_state["populated"]:
                from_artifact = storage_state["embedding_artifact_id"]
                from_revision = storage_state["embedding_revision"]
            if not _exact_switch(
                switch,
                from_artifact_id=from_artifact,
                from_revision=from_revision,
                to_artifact_id=model["artifact_id"],
                to_revision=model["revision"],
                require_blue_green=role == "embedding"
                and storage_state["populated"],
            ):
                blocked.append("revision_switch_not_approved")
        if role == "embedding" and storage_state["populated"]:
            identity_changed = (
                model["artifact_id"] != storage_state["embedding_artifact_id"]
                or model["revision"] != storage_state["embedding_revision"]
            )
            if identity_changed and not _exact_switch(
                switch,
                from_artifact_id=storage_state["embedding_artifact_id"],
                from_revision=storage_state["embedding_revision"],
                to_artifact_id=model["artifact_id"],
                to_revision=model["revision"],
                require_blue_green=True,
            ):
                blocked.append("embedding_identity_immutable")

        blocked_tuple = tuple(dict.fromkeys(blocked))
        if blocked_tuple:
            state = (
                "blocked_candidate"
                if provider["state"] == "desired"
                else "incompatible"
            )
        else:
            state = (
                "current"
                if provider["state"] in {"current", "fallback"}
                else "desired_candidate"
            )
        results.append(
            CompatibilityResult(
                provider_id=provider_id,
                role=role,
                state=state,
                compatible=not blocked_tuple,
                activatable=not blocked_tuple,
                blocked_by=blocked_tuple,
                fallback_provider_id=provider["fallback"],
                placement=placement,
                artifact_id=model["artifact_id"],
                revision=model["revision"],
            )
        )

    result_by_id = {result.provider_id: result for result in results}
    reranking_binding = normalized_bindings["reranking"]
    current_reranker = result_by_id[reranking_binding["current"]]
    desired_id = reranking_binding.get("desired")
    desired_reranker = (
        result_by_id.get(desired_id) if desired_id is not None else None
    )
    if (
        desired_reranker is not None
        and not desired_reranker.activatable
        and desired_reranker.fallback_provider_id
    ):
        fallback = result_by_id.get(desired_reranker.fallback_provider_id)
        if fallback is not None and fallback.activatable:
            reranking_disposition = {
                "state": "fallback",
                "provider_id": fallback.provider_id,
                "visible_degradation": True,
            }
        else:
            reranking_disposition = {
                "state": "disabled",
                "provider_id": None,
                "visible_degradation": True,
            }
    elif current_reranker.activatable:
        reranking_disposition = {
            "state": "current",
            "provider_id": current_reranker.provider_id,
            "visible_degradation": False,
        }
    else:
        reranking_disposition = {
            "state": "disabled",
            "provider_id": None,
            "visible_degradation": True,
        }

    return CompatibilityReport(
        profile_id=profile_id,
        role_bindings=normalized_bindings,
        results=tuple(results),
        reranking_disposition=reranking_disposition,
    )
