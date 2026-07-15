import json
import hashlib
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(LIB))

from hindsight_memory_control_plane.benchmark import (
    BenchmarkDataset,
    BenchmarkError,
    evaluate_benchmark,
    evaluate_candidate,
    load_cases,
    pareto_frontier,
    promotion_eligibility,
)


CASES = [
    {
        "schema_version": 1,
        "case_id": "graded",
        "query": "Which synthetic decisions are relevant?",
        "relevance": {"decision-primary": 3, "decision-secondary": 1},
        "must_recall": ["decision-primary"],
        "must_not_return": ["private-decoy"],
    },
    {
        "schema_version": 1,
        "case_id": "missed",
        "query": "Which synthetic constraint applies?",
        "relevance": {"constraint": 2},
        "must_recall": ["constraint"],
        "must_not_return": ["secret-decoy"],
    },
]
SYNTHETIC_DATASET_DIGEST = (
    "fba84844cc4e75995377d78a9a29fff884c511c05f9646eaf02e49a9a408480e"
)


def cases_digest(cases):
    canonical = json.dumps(
        cases,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def dimensions(**overrides):
    value = {
        "latency_ms_p95": 90.0,
        "direct_cost_usd": 0.02,
        "peak_memory_mb": 700.0,
        "model_footprint_mb": 500.0,
        "provider_available": True,
        "compatible": True,
        "license_ready": True,
    }
    value.update(overrides)
    return value


def candidate(candidate_id="candidate", **overrides):
    value = {
        "candidate_id": candidate_id,
        "deployment_envelope": "local",
        "retrievals": {
            "graded": ["decision-primary", "irrelevant", "decision-secondary"],
            "missed": ["irrelevant"],
        },
        "dimensions": dimensions(),
        "policy_passed": True,
    }
    value.update(overrides)
    return value


class BenchmarkTest(unittest.TestCase):
    def write_cases(self, path, cases=CASES):
        path.write_text(
            "".join(json.dumps(case, sort_keys=True) + "\n" for case in cases),
            encoding="utf-8",
        )

    def test_loads_schema_versioned_cases_and_digest_binds_canonical_content(
        self,
    ):
        schema_path = (
            ROOT
            / "home/dot_config/private_hindsight-memory/benchmark-schema.json"
        )
        fixture_path = ROOT / (
            "home/dot_config/private_hindsight-memory/synthetic-benchmark.jsonl"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(
            schema["required"],
            [
                "schema_version",
                "case_id",
                "query",
                "relevance",
                "must_recall",
                "must_not_return",
            ],
        )
        self.assertEqual(schema["properties"]["case_id"]["pattern"], ".*\\S.*")
        self.assertEqual(schema["properties"]["query"]["pattern"], ".*\\S.*")
        self.assertEqual(
            schema["properties"]["relevance"]["propertyNames"]["pattern"],
            ".*\\S.*",
        )
        self.assertIn("must_recall", schema["$comment"])
        self.assertIn("must_not_return", schema["$comment"])

        with self.assertRaises(TypeError):
            load_cases(fixture_path)
        dataset = load_cases(
            fixture_path, expected_digest=SYNTHETIC_DATASET_DIGEST
        )
        self.assertEqual(dataset.schema_version, 1)
        self.assertEqual(len(dataset.cases), 3)
        self.assertEqual(dataset.cases[0]["case_id"], "architecture-decision")
        self.assertEqual(
            dataset.dataset_digest,
            SYNTHETIC_DATASET_DIGEST,
        )
        self.assertEqual(
            load_cases(fixture_path, expected_digest=dataset.dataset_digest),
            dataset,
        )

        with self.assertRaisesRegex(BenchmarkError, "dataset digest mismatch"):
            load_cases(fixture_path, expected_digest="0" * 64)

    def test_loaded_cases_cannot_change_after_their_digest_is_bound(self):
        fixture_path = ROOT / (
            "home/dot_config/private_hindsight-memory/synthetic-benchmark.jsonl"
        )
        dataset = load_cases(
            fixture_path, expected_digest=SYNTHETIC_DATASET_DIGEST
        )
        bound_digest = dataset.dataset_digest

        with self.assertRaises(TypeError):
            dataset.cases[0]["relevance"]["post-digest-document"] = 3
        with self.assertRaises(TypeError):
            dataset.cases[0]["query"] = "changed after digest"
        with self.assertRaises((AttributeError, TypeError)):
            dataset.cases[0]["must_recall"].append("post-digest-document")

        with self.assertRaisesRegex(BenchmarkError, "dataset digest mismatch"):
            BenchmarkDataset(1, tuple(CASES), "a" * 64)
        with self.assertRaisesRegex(BenchmarkError, "dataset schema_version"):
            BenchmarkDataset(2, tuple(CASES), "a" * 64)
        with self.assertRaisesRegex(BenchmarkError, "relevance"):
            BenchmarkDataset(
                1,
                ({**CASES[0], "relevance": {"decision-primary": 0}},),
                "a" * 64,
            )
        with self.assertRaisesRegex(BenchmarkError, "duplicate case_id"):
            BenchmarkDataset(1, (CASES[0], CASES[0]), "a" * 64)

        directly_constructed = BenchmarkDataset(
            dataset.schema_version, dataset.cases, bound_digest
        )
        with self.assertRaises(TypeError):
            directly_constructed.cases[0]["relevance"][
                "post-digest-document"
            ] = 3

        self.assertEqual(dataset.dataset_digest, bound_digest)
        report = evaluate_candidate(
            dataset,
            {
                "candidate_id": "digest-bound",
                "deployment_envelope": "local",
                "retrievals": {
                    "architecture-decision": [
                        "public-decision",
                        "public-context",
                    ],
                    "operational-constraint": ["public-constraint"],
                    "historical-noise": ["public-current-convention"],
                },
                "dimensions": dimensions(),
                "policy_passed": True,
            },
            seed=11,
            bootstrap_samples=10,
        )
        json.dumps(report)
        self.assertEqual(report["dataset_digest"], bound_digest)

    def test_rejects_unknown_schema_invalid_judgments_and_duplicate_cases(self):
        invalid_sets = [
            [{**CASES[0], "schema_version": 2}],
            [{**CASES[0], "relevance": {"decision-primary": 0}}],
            [CASES[0], CASES[0]],
            [{**CASES[0], "surprise": True}],
            [{**CASES[0], "must_recall": ["unjudged"]}],
            [{**CASES[0], "must_not_return": ["decision-primary"]}],
            [{**CASES[0], "case_id": "   "}],
            [{**CASES[0], "query": "\t"}],
            [{**CASES[0], "relevance": {" ": 1}}],
        ]
        messages = [
            "schema_version",
            "relevance",
            "duplicate case_id",
            "keys",
            "must_recall",
            "must_not_return",
            "case_id",
            "query",
            "relevance document ID",
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, (cases, message) in enumerate(
                zip(invalid_sets, messages)
            ):
                path = Path(directory) / f"invalid-{index}.jsonl"
                self.write_cases(path, cases)
                with self.assertRaisesRegex(BenchmarkError, message):
                    load_cases(path, expected_digest=cases_digest(cases))

    def test_metrics_bootstrap_and_retrieval_gates_are_exact_and_deterministic(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            self.write_cases(path)
            dataset = load_cases(path, expected_digest=cases_digest(CASES))

        report = evaluate_candidate(
            dataset, candidate(), seed=1701, bootstrap_samples=200
        )
        # Hand-calculated from the literal relevance grades and ranks.
        self.assertEqual(report["metrics"]["recall_at_20"], 0.5)
        self.assertAlmostEqual(
            report["metrics"]["ndcg_at_10"], 0.49142111395336985, places=15
        )
        self.assertEqual(
            report["bootstrap"],
            {"seed": 1701, "samples": 200, "confidence": 0.95},
        )
        self.assertEqual(
            report["confidence_intervals"]["recall_at_20"], [0.0, 1.0]
        )
        self.assertEqual(
            report["confidence_intervals"]["ndcg_at_10"],
            [0.0, 0.9828422279067397],
        )
        self.assertEqual(
            report,
            evaluate_candidate(
                dataset, candidate(), seed=1701, bootstrap_samples=200
            ),
        )
        self.assertEqual(
            report["gates"]["must_recall"]["failures"],
            [{"case_id": "missed", "document_id": "constraint"}],
        )
        self.assertTrue(report["gates"]["must_not_return"]["passed"])
        self.assertFalse(report["gates"]["passed"])

        leaking = candidate(
            retrievals={
                "graded": [
                    "decision-primary",
                    "private-decoy",
                    "decision-secondary",
                ],
                "missed": ["constraint", "secret-decoy"],
            }
        )
        leaked = evaluate_candidate(
            dataset, leaking, seed=7, bootstrap_samples=20
        )
        self.assertEqual(
            leaked["gates"]["must_not_return"]["failures"],
            [
                {
                    "case_id": "graded",
                    "document_id": "private-decoy",
                    "rank": 2,
                },
                {"case_id": "missed", "document_id": "secret-decoy", "rank": 2},
            ],
        )
        self.assertFalse(leaked["gates"]["passed"])

    def test_pareto_frontier_is_per_envelope_and_excludes_unready_candidates(
        self,
    ):
        def report(
            candidate_id,
            recall,
            ndcg,
            dims,
            envelope="local",
            gates_passed=True,
        ):
            return {
                "candidate_id": candidate_id,
                "deployment_envelope": envelope,
                "metrics": {"recall_at_20": recall, "ndcg_at_10": ndcg},
                "dimensions": dims,
                "gates": {"passed": gates_passed},
            }

        reports = [
            report(
                "balanced",
                0.9,
                0.9,
                dimensions(latency_ms_p95=80, direct_cost_usd=0.02),
            ),
            report(
                "dominated",
                0.8,
                0.8,
                dimensions(latency_ms_p95=100, direct_cost_usd=0.03),
            ),
            report(
                "fast",
                0.8,
                0.8,
                dimensions(latency_ms_p95=40, direct_cost_usd=0.03),
            ),
            report(
                "license-blocked", 1.0, 1.0, dimensions(license_ready=False)
            ),
            report(
                "hosted",
                0.7,
                0.7,
                dimensions(latency_ms_p95=10),
                envelope="hosted",
            ),
        ]
        self.assertEqual(
            pareto_frontier(reports),
            {"hosted": ["hosted"], "local": ["balanced", "fast"]},
        )

    def test_promotion_requires_safety_readiness_and_a_meaningful_gain(
        self,
    ):
        base = {
            "candidate_id": "base",
            "metrics": {"recall_at_20": 0.90, "ndcg_at_10": 0.80},
            "dimensions": dimensions(
                latency_ms_p95=100, direct_cost_usd=0.02, peak_memory_mb=800
            ),
            "gates": {
                "passed": True,
                "must_not_return": {"passed": True},
                "policy": {"passed": True},
            },
        }
        improved = {
            "candidate_id": "improved",
            "metrics": {"recall_at_20": 0.89, "ndcg_at_10": 0.80},
            "dimensions": dimensions(
                latency_ms_p95=75, direct_cost_usd=0.02, peak_memory_mb=800
            ),
            "gates": {
                "passed": True,
                "must_not_return": {"passed": True},
                "policy": {"passed": True},
            },
        }
        thresholds = {
            "max_retrieval_regression": {
                "recall_at_20": 0.02,
                "ndcg_at_10": 0.01,
            },
            "meaningful_gain": {
                "recall_at_20": 0.02,
                "ndcg_at_10": 0.02,
                "latency_ms_p95": 10.0,
                "direct_cost_usd": 0.005,
                "peak_memory_mb": 100.0,
                "model_footprint_mb": 100.0,
            },
        }
        decision = promotion_eligibility(base, improved, thresholds)
        self.assertTrue(decision["eligible"])
        self.assertEqual(decision["meaningful_gains"], ["latency_ms_p95"])

        no_gain = {
            **improved,
            "candidate_id": "no-gain",
            "dimensions": dimensions(latency_ms_p95=95, peak_memory_mb=800),
        }
        self.assertFalse(
            promotion_eligibility(base, no_gain, thresholds)["eligible"]
        )
        regression = {
            **improved,
            "candidate_id": "regression",
            "metrics": {"recall_at_20": 0.87, "ndcg_at_10": 0.80},
        }
        self.assertFalse(
            promotion_eligibility(base, regression, thresholds)["eligible"]
        )
        leak = {
            **improved,
            "candidate_id": "leak",
            "gates": {
                "passed": False,
                "must_not_return": {"passed": False},
                "policy": {"passed": True},
            },
        }
        self.assertFalse(
            promotion_eligibility(base, leak, thresholds)["eligible"]
        )
        blocked = {
            **improved,
            "candidate_id": "blocked",
            "dimensions": dimensions(latency_ms_p95=75, compatible=False),
        }
        self.assertFalse(
            promotion_eligibility(base, blocked, thresholds)["eligible"]
        )
        footprint_gain = {
            **base,
            "candidate_id": "footprint-gain",
            "dimensions": dimensions(
                latency_ms_p95=100,
                direct_cost_usd=0.02,
                peak_memory_mb=800,
                model_footprint_mb=350,
            ),
        }
        self.assertEqual(
            promotion_eligibility(base, footprint_gain, thresholds)[
                "meaningful_gains"
            ],
            ["model_footprint_mb"],
        )
        self.assertTrue(
            promotion_eligibility(base, footprint_gain, thresholds)["eligible"]
        )

        zero_thresholds = {
            "max_retrieval_regression": {
                "recall_at_20": 0.0,
                "ndcg_at_10": 0.0,
            },
            "meaningful_gain": {
                "recall_at_20": 0.0,
                "ndcg_at_10": 0.0,
                "latency_ms_p95": 0.0,
                "direct_cost_usd": 0.0,
                "peak_memory_mb": 0.0,
                "model_footprint_mb": 0.0,
            },
        }
        unchanged = {**base, "candidate_id": "unchanged"}
        self.assertFalse(
            promotion_eligibility(base, unchanged, zero_thresholds)["eligible"]
        )

    def test_full_evaluation_records_seed_dimensions_frontier_and_promotions(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            self.write_cases(path)
            dataset = load_cases(path, expected_digest=cases_digest(CASES))
        base = candidate(
            "base",
            retrievals={
                "graded": ["decision-primary", "decision-secondary"],
                "missed": ["constraint"],
            },
            dimensions=dimensions(latency_ms_p95=100),
        )
        faster = candidate(
            "faster",
            retrievals={
                "graded": ["decision-primary", "decision-secondary"],
                "missed": ["constraint"],
            },
            dimensions=dimensions(latency_ms_p95=70),
        )
        report = evaluate_benchmark(
            dataset,
            [base, faster],
            baseline_id="base",
            seed=42,
            bootstrap_samples=50,
            promotion_thresholds={
                "max_retrieval_regression": {
                    "recall_at_20": 0.0,
                    "ndcg_at_10": 0.0,
                },
                "meaningful_gain": {
                    "recall_at_20": 0.01,
                    "ndcg_at_10": 0.01,
                    "latency_ms_p95": 10,
                    "direct_cost_usd": 0.001,
                    "peak_memory_mb": 10,
                    "model_footprint_mb": 10,
                },
            },
        )
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["bootstrap"]["seed"], 42)
        self.assertEqual(report["pareto_frontiers"], {"local": ["faster"]})
        self.assertTrue(report["promotions"]["faster"]["eligible"])
        self.assertEqual(
            report["candidates"][1]["dimensions"]["provider_available"], True
        )


if __name__ == "__main__":
    unittest.main()
