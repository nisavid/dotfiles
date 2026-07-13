"""Deterministic, disclosure-safe retrieval benchmark evaluation."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import re
from typing import Any, Iterable, Mapping, Sequence

from .model import deep_freeze


SCHEMA_VERSION = 1
CASE_KEYS = {
    "schema_version",
    "case_id",
    "query",
    "relevance",
    "must_recall",
    "must_not_return",
}
DIMENSION_KEYS = {
    "latency_ms_p95",
    "direct_cost_usd",
    "peak_memory_mb",
    "model_footprint_mb",
    "provider_available",
    "compatible",
    "license_ready",
}
LOWER_IS_BETTER = (
    "latency_ms_p95",
    "direct_cost_usd",
    "peak_memory_mb",
    "model_footprint_mb",
)
HIGHER_IS_BETTER = ("recall_at_20", "ndcg_at_10")


class BenchmarkError(ValueError):
    """The artifact or evaluation input violates the benchmark contract."""


@dataclass(frozen=True)
class BenchmarkDataset:
    schema_version: int
    cases: tuple[Mapping[str, Any], ...]
    dataset_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != SCHEMA_VERSION
        ):
            raise BenchmarkError(
                f"dataset schema_version must be integer {SCHEMA_VERSION}"
            )
        validated = [
            _validate_case(case, index)
            for index, case in enumerate(self.cases, 1)
        ]
        if not validated:
            raise BenchmarkError(
                "benchmark dataset must contain at least one case"
            )
        case_ids = [case["case_id"] for case in validated]
        if len(set(case_ids)) != len(case_ids):
            raise BenchmarkError("duplicate case_id in benchmark dataset")
        actual_digest = hashlib.sha256(_canonical_bytes(validated)).hexdigest()
        if self.dataset_digest != actual_digest:
            message = (
                "dataset digest mismatch: expected "
                f"{self.dataset_digest}, got {actual_digest}"
            )
            raise BenchmarkError(message)
        object.__setattr__(
            self, "cases", tuple(deep_freeze(case) for case in validated)
        )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{label} must be a non-empty string")
    return value


def _validate_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise BenchmarkError(f"{label} must be a list of non-empty strings")
    if len(set(value)) != len(value):
        raise BenchmarkError(f"{label} must not contain duplicates")
    return list(value)


def _validate_case(raw: Any, line_number: int) -> dict[str, Any]:
    label = f"benchmark line {line_number}"
    if not isinstance(raw, dict):
        raise BenchmarkError(f"{label} must be an object")
    if set(raw) != CASE_KEYS:
        raise BenchmarkError(
            f"{label} keys must be exactly {sorted(CASE_KEYS)}"
        )
    if (
        type(raw["schema_version"]) is not int
        or raw["schema_version"] != SCHEMA_VERSION
    ):
        raise BenchmarkError(
            f"{label} schema_version must be integer {SCHEMA_VERSION}"
        )
    case_id = _require_nonempty_string(raw["case_id"], f"{label} case_id")
    query = _require_nonempty_string(raw["query"], f"{label} query")
    relevance = raw["relevance"]
    if not isinstance(relevance, dict) or not relevance:
        raise BenchmarkError(f"{label} relevance must be a non-empty object")
    normalized_relevance: dict[str, int] = {}
    for document_id, grade in relevance.items():
        _require_nonempty_string(document_id, f"{label} relevance document ID")
        if type(grade) is not int or not 1 <= grade <= 3:
            raise BenchmarkError(
                f"{label} relevance grades must be integers from 1 to 3"
            )
        normalized_relevance[document_id] = grade
    must_recall = _validate_string_list(
        raw["must_recall"], f"{label} must_recall"
    )
    must_not_return = _validate_string_list(
        raw["must_not_return"], f"{label} must_not_return"
    )
    if not set(must_recall).issubset(normalized_relevance):
        raise BenchmarkError(
            f"{label} must_recall documents require positive relevance "
            "judgments"
        )
    if set(must_not_return) & set(normalized_relevance):
        raise BenchmarkError(
            f"{label} must_not_return documents cannot be relevant"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "query": query,
        "relevance": normalized_relevance,
        "must_recall": must_recall,
        "must_not_return": must_not_return,
    }


def load_cases(path: str | Path, *, expected_digest: str) -> BenchmarkDataset:
    """Load and digest canonical benchmark cases from a JSON Lines artifact."""
    if not isinstance(expected_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_digest
    ):
        raise BenchmarkError(
            "expected dataset digest must be a lowercase SHA-256 digest"
        )
    artifact = Path(path)
    cases: list[dict[str, Any]] = []
    try:
        lines = artifact.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise BenchmarkError(
            f"cannot read benchmark dataset: {error}"
        ) from error
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise BenchmarkError(
                f"benchmark line {line_number} is not valid JSON: {error.msg}"
            ) from error
        cases.append(_validate_case(raw, line_number))
    if not cases:
        raise BenchmarkError("benchmark dataset must contain at least one case")
    case_ids = [case["case_id"] for case in cases]
    if len(set(case_ids)) != len(case_ids):
        raise BenchmarkError("duplicate case_id in benchmark dataset")
    dataset_digest = hashlib.sha256(_canonical_bytes(cases)).hexdigest()
    if dataset_digest != expected_digest:
        message = (
            "dataset digest mismatch: expected "
            f"{expected_digest}, got {dataset_digest}"
        )
        raise BenchmarkError(message)
    return BenchmarkDataset(SCHEMA_VERSION, tuple(cases), dataset_digest)


def _validate_dimensions(raw: Any) -> dict[str, float | bool]:
    if not isinstance(raw, Mapping) or set(raw) != DIMENSION_KEYS:
        raise BenchmarkError(
            f"dimensions keys must be exactly {sorted(DIMENSION_KEYS)}"
        )
    dimensions: dict[str, float | bool] = {}
    for key in LOWER_IS_BETTER:
        value = raw[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise BenchmarkError(
                f"dimension {key} must be a finite non-negative number"
            )
        dimensions[key] = float(value)
    for key in ("provider_available", "compatible", "license_ready"):
        if type(raw[key]) is not bool:
            raise BenchmarkError(f"dimension {key} must be boolean")
        dimensions[key] = raw[key]
    return dimensions


def _validate_candidate(dataset: BenchmarkDataset, raw: Any) -> dict[str, Any]:
    required = {
        "candidate_id",
        "deployment_envelope",
        "retrievals",
        "dimensions",
        "policy_passed",
    }
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise BenchmarkError(
            f"candidate keys must be exactly {sorted(required)}"
        )
    candidate_id = _require_nonempty_string(raw["candidate_id"], "candidate_id")
    envelope = _require_nonempty_string(
        raw["deployment_envelope"], "deployment_envelope"
    )
    if type(raw["policy_passed"]) is not bool:
        raise BenchmarkError("policy_passed must be boolean")
    retrievals = raw["retrievals"]
    expected_case_ids = {case["case_id"] for case in dataset.cases}
    if (
        not isinstance(retrievals, Mapping)
        or set(retrievals) != expected_case_ids
    ):
        raise BenchmarkError(
            "retrievals must contain exactly the benchmark case IDs"
        )
    normalized_retrievals: dict[str, list[str]] = {}
    for case_id in sorted(expected_case_ids):
        normalized_retrievals[case_id] = _validate_string_list(
            retrievals[case_id], f"retrievals.{case_id}"
        )
    return {
        "candidate_id": candidate_id,
        "deployment_envelope": envelope,
        "retrievals": normalized_retrievals,
        "dimensions": _validate_dimensions(raw["dimensions"]),
        "policy_passed": raw["policy_passed"],
    }


def _recall(
    relevance: Mapping[str, int], retrieved: Sequence[str], limit: int
) -> float:
    return len(set(retrieved[:limit]) & set(relevance)) / len(relevance)


def _ndcg(
    relevance: Mapping[str, int], retrieved: Sequence[str], limit: int
) -> float:
    dcg = sum(
        (2.0 ** relevance.get(document_id, 0) - 1.0) / math.log2(rank + 1.0)
        for rank, document_id in enumerate(retrieved[:limit], 1)
    )
    ideal = sum(
        (2.0**grade - 1.0) / math.log2(rank + 1.0)
        for rank, grade in enumerate(
            sorted(relevance.values(), reverse=True)[:limit], 1
        )
    )
    return dcg / ideal


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _empirical_interval(
    values: Sequence[float], confidence: float
) -> list[float]:
    ordered = sorted(values)
    alpha = (1.0 - confidence) / 2.0
    lower_index = max(0, math.floor(alpha * len(ordered)))
    upper_index = min(
        len(ordered) - 1, math.ceil((1.0 - alpha) * len(ordered)) - 1
    )
    return [ordered[lower_index], ordered[upper_index]]


def _bootstrap_intervals(
    per_case: Mapping[str, Sequence[float]],
    *,
    seed: int,
    samples: int,
    confidence: float,
) -> dict[str, list[float]]:
    if type(seed) is not int:
        raise BenchmarkError("bootstrap seed must be an integer")
    if type(samples) is not int or samples <= 0:
        raise BenchmarkError("bootstrap samples must be a positive integer")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 < confidence < 1.0
    ):
        raise BenchmarkError("bootstrap confidence must be between 0 and 1")
    generator = random.Random(seed)
    case_count = len(next(iter(per_case.values())))
    sampled: dict[str, list[float]] = {metric: [] for metric in per_case}
    for _ in range(samples):
        indices = [generator.randrange(case_count) for _ in range(case_count)]
        for metric, values in per_case.items():
            sampled[metric].append(_mean([values[index] for index in indices]))
    return {
        metric: _empirical_interval(values, float(confidence))
        for metric, values in sampled.items()
    }


def evaluate_candidate(
    dataset: BenchmarkDataset,
    candidate: Mapping[str, Any],
    *,
    seed: int,
    bootstrap_samples: int = 2000,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Evaluate ordered retrievals against authoritative judgments."""
    if (
        not isinstance(dataset, BenchmarkDataset)
        or dataset.schema_version != SCHEMA_VERSION
    ):
        raise BenchmarkError(f"dataset schema_version must be {SCHEMA_VERSION}")
    value = _validate_candidate(dataset, candidate)
    recalls: list[float] = []
    ndcgs: list[float] = []
    must_recall_failures: list[dict[str, Any]] = []
    must_not_return_failures: list[dict[str, Any]] = []
    for case in dataset.cases:
        case_id = case["case_id"]
        retrieved = value["retrievals"][case_id]
        recalls.append(_recall(case["relevance"], retrieved, 20))
        ndcgs.append(_ndcg(case["relevance"], retrieved, 10))
        top_twenty = set(retrieved[:20])
        for document_id in case["must_recall"]:
            if document_id not in top_twenty:
                must_recall_failures.append(
                    {"case_id": case_id, "document_id": document_id}
                )
        for document_id in case["must_not_return"]:
            if document_id in retrieved:
                must_not_return_failures.append(
                    {
                        "case_id": case_id,
                        "document_id": document_id,
                        "rank": retrieved.index(document_id) + 1,
                    }
                )
    intervals = _bootstrap_intervals(
        {"recall_at_20": recalls, "ndcg_at_10": ndcgs},
        seed=seed,
        samples=bootstrap_samples,
        confidence=confidence,
    )
    must_recall_passed = not must_recall_failures
    must_not_return_passed = not must_not_return_failures
    policy_passed = value["policy_passed"]
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": value["candidate_id"],
        "deployment_envelope": value["deployment_envelope"],
        "dataset_digest": dataset.dataset_digest,
        "metrics": {
            "recall_at_20": _mean(recalls),
            "ndcg_at_10": _mean(ndcgs),
        },
        "confidence_intervals": intervals,
        "bootstrap": {
            "seed": seed,
            "samples": bootstrap_samples,
            "confidence": float(confidence),
        },
        "gates": {
            "must_recall": {
                "passed": must_recall_passed,
                "failures": must_recall_failures,
            },
            "must_not_return": {
                "passed": must_not_return_passed,
                "failures": must_not_return_failures,
            },
            "policy": {"passed": policy_passed},
            "passed": must_recall_passed
            and must_not_return_passed
            and policy_passed,
        },
        "dimensions": value["dimensions"],
    }


def _ready(report: Mapping[str, Any]) -> bool:
    dimensions = report["dimensions"]
    return bool(
        report["gates"]["passed"]
        and dimensions["provider_available"]
        and dimensions["compatible"]
        and dimensions["license_ready"]
    )


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    at_least_as_good = all(
        left["metrics"][key] >= right["metrics"][key]
        for key in HIGHER_IS_BETTER
    ) and all(
        left["dimensions"][key] <= right["dimensions"][key]
        for key in LOWER_IS_BETTER
    )
    strictly_better = any(
        left["metrics"][key] > right["metrics"][key] for key in HIGHER_IS_BETTER
    ) or any(
        left["dimensions"][key] < right["dimensions"][key]
        for key in LOWER_IS_BETTER
    )
    return at_least_as_good and strictly_better


def pareto_frontier(
    reports: Iterable[Mapping[str, Any]],
) -> dict[str, list[str]]:
    """Return ready, non-dominated candidates per deployment envelope."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for report in reports:
        if _ready(report):
            grouped.setdefault(report["deployment_envelope"], []).append(report)
    frontiers: dict[str, list[str]] = {}
    for envelope, candidates in sorted(grouped.items()):
        frontiers[envelope] = sorted(
            candidate["candidate_id"]
            for candidate in candidates
            if not any(
                other is not candidate and _dominates(other, candidate)
                for other in candidates
            )
        )
    return frontiers


def _validate_thresholds(raw: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    if not isinstance(raw, Mapping) or set(raw) != {
        "max_retrieval_regression",
        "meaningful_gain",
    }:
        raise BenchmarkError(
            "promotion thresholds require max_retrieval_regression and "
            "meaningful_gain"
        )
    expected = {
        "max_retrieval_regression": set(HIGHER_IS_BETTER),
        "meaningful_gain": {
            "recall_at_20",
            "ndcg_at_10",
            "latency_ms_p95",
            "direct_cost_usd",
            "peak_memory_mb",
            "model_footprint_mb",
        },
    }
    normalized: dict[str, dict[str, float]] = {}
    for group, keys in expected.items():
        values = raw[group]
        if not isinstance(values, Mapping) or set(values) != keys:
            message = (
                f"promotion threshold {group} keys must be exactly "
                f"{sorted(keys)}"
            )
            raise BenchmarkError(message)
        normalized[group] = {}
        for key, value in values.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise BenchmarkError(
                    f"promotion threshold {group}.{key} must be non-negative"
                )
            normalized[group][key] = float(value)
    return normalized


def promotion_eligibility(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply thresholds without resolving or activating a model."""
    limits = _validate_thresholds(thresholds)
    epsilon = 1e-12
    regressions = [
        metric
        for metric in HIGHER_IS_BETTER
        if baseline["metrics"][metric] - candidate["metrics"][metric]
        > limits["max_retrieval_regression"][metric] + epsilon
    ]
    gains: list[str] = []
    for metric in HIGHER_IS_BETTER:
        delta = candidate["metrics"][metric] - baseline["metrics"][metric]
        if (
            delta > epsilon
            and delta + epsilon >= limits["meaningful_gain"][metric]
        ):
            gains.append(metric)
    for metric in (
        "latency_ms_p95",
        "direct_cost_usd",
        "peak_memory_mb",
        "model_footprint_mb",
    ):
        delta = baseline["dimensions"][metric] - candidate["dimensions"][metric]
        if (
            delta > epsilon
            and delta + epsilon >= limits["meaningful_gain"][metric]
        ):
            gains.append(metric)
    leakage_policy_safe = bool(
        candidate["gates"]["must_not_return"]["passed"]
        and candidate["gates"]["policy"]["passed"]
    )
    retrieval_gates_passed = bool(candidate["gates"]["passed"])
    readiness_passed = bool(
        candidate["dimensions"]["provider_available"]
        and candidate["dimensions"]["compatible"]
        and candidate["dimensions"]["license_ready"]
    )
    reasons: list[str] = []
    if regressions:
        reasons.append("material retrieval regression")
    if not retrieval_gates_passed:
        reasons.append("retrieval gate failure")
    if not leakage_policy_safe:
        reasons.append("policy or leakage failure")
    if not readiness_passed:
        reasons.append("provider, compatibility, or license gate failure")
    if not gains:
        reasons.append("no meaningful gain")
    eligible = (
        not regressions
        and retrieval_gates_passed
        and leakage_policy_safe
        and readiness_passed
        and bool(gains)
    )
    return {
        "eligible": eligible,
        "no_material_retrieval_regression": not regressions,
        "retrieval_gates_passed": retrieval_gates_passed,
        "no_policy_or_leakage_failure": leakage_policy_safe,
        "readiness_passed": readiness_passed,
        "has_meaningful_gain": bool(gains),
        "meaningful_gains": gains,
        "material_regressions": regressions,
        "reasons": reasons,
    }


def evaluate_benchmark(
    dataset: BenchmarkDataset,
    candidates: Iterable[Mapping[str, Any]],
    *,
    baseline_id: str,
    seed: int,
    bootstrap_samples: int,
    promotion_thresholds: Mapping[str, Any],
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Build a complete deterministic benchmark and promotion report."""
    reports = [
        evaluate_candidate(
            dataset,
            candidate,
            seed=seed,
            bootstrap_samples=bootstrap_samples,
            confidence=confidence,
        )
        for candidate in candidates
    ]
    by_id = {report["candidate_id"]: report for report in reports}
    if len(by_id) != len(reports):
        raise BenchmarkError("candidate_id values must be unique")
    if baseline_id not in by_id:
        raise BenchmarkError(f"baseline candidate {baseline_id!r} is missing")
    baseline = by_id[baseline_id]
    promotions = {
        report["candidate_id"]: promotion_eligibility(
            baseline, report, promotion_thresholds
        )
        for report in reports
        if report["candidate_id"] != baseline_id
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_digest": dataset.dataset_digest,
        "baseline_id": baseline_id,
        "bootstrap": {
            "seed": seed,
            "samples": bootstrap_samples,
            "confidence": float(confidence),
        },
        "candidates": reports,
        "pareto_frontiers": pareto_frontier(reports),
        "promotions": promotions,
    }
