import json
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.canonical import digest
from hindsight_memory_control_plane.policy import (
    PolicyError,
    observation_scope,
    resolve_policy,
    resolve_session_route,
    validate_durable_policy_input,
    validate_tags,
)
from hindsight_memory_control_plane.providers import (
    ProviderCompatibilityError,
    validate_provider_compatibility,
)


ENGINEERING_RETAIN = (
    "Extract durable engineering knowledge from trusted user/assistant "
    "conversations and structured outcome records: explicit preferences and "
    "corrections, approval boundaries, settled team and workflow conventions, "
    "product and technical decisions with rationale and trade-offs, reusable "
    "procedures, failure chains from symptom through verified fix, and "
    "relationships among people, repositories, systems, issues, pull requests, "
    "releases, clusters, and tools. Preserve provenance and time. Treat "
    "branch, "
    "review, deployment, cluster, service, provider, and quota state as dated "
    "evidence requiring live verification. Ignore greetings, unchosen "
    "brainstorming, session and tool bookkeeping, raw tool output, secrets, "
    "credentials, opaque volatile identifiers, transient local paths, recalled "
    "memory blocks, and unsupported assumptions."
)

PERSONAL_RETAIN = (
    "Apply only to explicitly personal sessions. Extract durable preferences, "
    "goals, commitments, relationships, recurring routines and logistics, "
    "non-work project decisions, and corrections while preserving attribution, "
    "time, confidence, and provenance. Treat schedules, travel, location, and "
    "task status as dated. Exclude credentials, authentication material, "
    "health, medical, financial, legal, and regulated details, raw "
    "external-app "
    "content, unnecessary third-party private facts, pleasantries, agent "
    "mechanics, and recalled memory blocks."
)
CIPHERTEXT_DIGEST = "c" * 64


def private_catalog():
    return {
        "schema_version": 1,
        "contextual_models": [
            {
                "id": "private-review-model",
                "selector_tag": "workflow:synthetic-review",
                "source_filter_tags": ["workflow:synthetic-review"],
            },
            {
                "id": "private-repository-model",
                "selector_tag": "repo:synthetic-repository",
                "source_filter_tags": ["repo:synthetic-repository"],
            },
        ],
        "contextual_model_migrations": [
            {
                "source_id": "private-review-model",
                "disposition": "retain",
                "target_id": "private-review-model",
            },
            {
                "source_id": "private-repository-model",
                "disposition": "retain",
                "target_id": "private-repository-model",
            },
        ],
        "repository_catalog": {
            "canonical": ["repo:synthetic-repository"],
            "aliases": {"project:synthetic": "repo:synthetic-repository"},
            "drop_aliases": ["project:obsolete"],
        },
        "workflow_catalog": {"controlled": ["workflow:synthetic-review"]},
        "privacy": {
            "public_forbidden_literals": [
                "private-review-model",
                "private-repository-model",
                "workflow:synthetic-review",
                "repo:synthetic-repository",
                "project:synthetic",
                "project:obsolete",
            ]
        },
    }


def public_policy():
    return {
        "schema_version": 1,
        "engineering_enabled": True,
        "banks": [
            {
                "id": "engineering",
                "kind": "engineering",
                "authority": "authoritative",
                "writable": True,
            },
            {
                "id": "personal",
                "kind": "personal",
                "authority": "none",
                "writable": True,
            },
            {
                "id": "airlock",
                "kind": "airlock",
                "authority": "none",
                "writable": True,
            },
        ],
        "machine_default": "engineering",
        "workspace_mappings": [
            {
                "selector_id": "workspace:personal",
                "specificity": 10,
                "bank_id": "personal",
            },
            {
                "selector_id": "workspace:engineering",
                "specificity": 5,
                "bank_id": "engineering",
            },
        ],
        "allowed_companions": {
            "engineering": ["personal"],
            "personal": ["engineering"],
            "airlock": [],
        },
    }


class BankPolicyTest(unittest.TestCase):
    def setUp(self):
        self.catalog = private_catalog()
        self.policy = resolve_policy(
            public_policy(),
            self.catalog,
            digest(self.catalog),
            private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
        )

    def test_exact_bank_archetypes_are_immutable_and_closed(self):
        engineering = self.policy.bank("engineering")
        personal = self.policy.bank("personal")
        airlock = self.policy.bank("airlock")
        self.assertEqual(engineering.retain_mission, ENGINEERING_RETAIN)
        self.assertEqual(personal.retain_mission, PERSONAL_RETAIN)
        self.assertEqual(airlock.extraction_mode, "chunk-only")
        self.assertFalse(airlock.observations_enabled)
        self.assertFalse(airlock.entity_extraction_enabled)
        self.assertEqual(airlock.models, ())
        self.assertIn("untrusted", airlock.retain_mission)
        self.assertIn("no authorization", airlock.reflect_mission)
        self.assertEqual(
            engineering.disposition,
            {"skepticism": 4, "literalism": 3, "empathy": 2},
        )
        self.assertEqual(
            personal.disposition,
            {"skepticism": 4, "literalism": 3, "empathy": 4},
        )
        self.assertEqual(
            engineering.entity_labels["kind"],
            (
                "rule",
                "principle",
                "runbook",
                "decision",
                "incident",
                "state",
                "reference",
            ),
        )
        self.assertEqual(
            personal.entity_labels["kind"],
            (
                "preference",
                "goal",
                "commitment",
                "relationship",
                "routine",
                "logistics",
                "project",
                "state",
                "reference",
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            engineering.retain_mission = "changed"
        with self.assertRaises(TypeError):
            engineering.disposition["empathy"] = 9

    def test_models_have_exact_caps_sources_and_controller_only_refresh(self):
        engineering = self.policy.bank("engineering")
        self.assertEqual(
            [(model.id, model.max_tokens) for model in engineering.models],
            [("operator-profile", 1536), ("engineering-principles", 2048)],
        )
        for model in engineering.models:
            self.assertEqual(model.refresh_mode, "delta")
            self.assertEqual(model.source_evidence, ("facts", "observations"))
            self.assertTrue(model.exclude_mental_models)
            self.assertFalse(model.refresh_after_consolidation)
            self.assertIsNone(model.refresh_cron)
        personal = self.policy.bank("personal").models
        self.assertEqual(
            [(model.id, model.max_tokens) for model in personal],
            [("personal-profile", 1024)],
        )
        self.assertEqual(self.policy.contextual_model_cap, 1)
        self.assertTrue(
            all(
                model.strict_source_filter
                for model in self.policy.contextual_models
            )
        )

    def test_defense_tracing_and_cross_bank_writes_are_fail_closed(self):
        for bank_id in ("engineering", "personal", "airlock"):
            bank = self.policy.bank(bank_id)
            self.assertEqual(bank.memory_defense, "sensitive_data")
            self.assertFalse(bank.native_audit_logging)
            self.assertFalse(bank.native_llm_tracing)
        self.assertEqual(self.policy.cross_bank_write_mode, "projection-only")
        projection = self.policy.projection_policy
        self.assertTrue(projection["minimal"])
        self.assertTrue(projection["idempotent"])
        self.assertTrue(projection["provenance_linked"])
        self.assertTrue(projection["independently_deletable"])
        self.assertEqual(
            projection["deny_policy"],
            "source-target-intersection",
        )
        self.assertIn("credential", projection["deny_classes"])
        self.assertIn("recalled_memory_block", projection["deny_classes"])
        self.assertEqual(
            projection["reviewer_bounds"],
            {
                "reviewer_id": "cross-bank-reviewer",
                "provider_binding": "profile-llm",
                "source_data_classes": ("engineering", "personal"),
                "target_data_classes": ("engineering", "personal"),
                "max_input_bytes": 65536,
                "max_output_bytes": 8192,
                "timeout_seconds": 30,
                "no_payload_log": True,
            },
        )
        self.assertEqual(
            projection["stable_identity_fields"],
            (
                "source_session",
                "turn_range",
                "target_bank_ref",
                "policy_version",
            ),
        )
        self.assertTrue(projection["live_notice_required"])
        self.assertTrue(projection["payload_free_ledger"])

    def test_public_serialization_discloses_no_private_catalog_literals(self):
        rendered = json.dumps(self.policy.to_dict(), sort_keys=True)
        for private_literal in self.catalog["privacy"][
            "public_forbidden_literals"
        ]:
            self.assertNotIn(private_literal, rendered)
        self.assertEqual(
            self.policy.to_dict()["private_catalog_digest"],
            digest(self.catalog),
        )
        self.assertEqual(
            self.policy.to_dict()["private_catalog_ciphertext_digest"],
            CIPHERTEXT_DIGEST,
        )
        self.assertTrue(
            all(
                ref.startswith("private:")
                for ref in self.policy.to_dict()["contextual_model_refs"]
            )
        )

    def test_privacy_guard_covers_every_migration_source_id(self):
        catalog = private_catalog()
        catalog["contextual_model_migrations"][0] = {
            "source_id": "legacy-private-review-model",
            "disposition": "supersede",
            "target_id": "private-review-model",
        }

        with self.assertRaisesRegex(PolicyError, "privacy guard"):
            resolve_policy(
                public_policy(),
                catalog,
                digest(catalog),
                private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
            )

    def test_policy_digest_binds_every_public_semantic_field(self):
        body = self.policy.to_dict()
        policy_digest = body.pop("policy_digest")
        self.assertEqual(policy_digest, digest(body))

    def test_catalog_and_policy_schemas_are_closed_and_authenticated(
        self,
    ):
        bad_public = public_policy()
        bad_public["caller_bank"] = "personal"
        with self.assertRaisesRegex(PolicyError, "policy keys are closed"):
            resolve_policy(
                bad_public,
                self.catalog,
                digest(self.catalog),
                private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
            )
        bad_catalog = private_catalog()
        bad_catalog["secret_note"] = "must not serialize"
        with self.assertRaisesRegex(PolicyError, "catalog keys are closed"):
            resolve_policy(
                public_policy(),
                bad_catalog,
                digest(bad_catalog),
                private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
            )
        with self.assertRaisesRegex(PolicyError, "catalog digest"):
            resolve_policy(
                public_policy(),
                self.catalog,
                "0" * 64,
                private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
            )
        with self.assertRaisesRegex(PolicyError, "ciphertext"):
            resolve_policy(
                public_policy(),
                self.catalog,
                digest(self.catalog),
                private_catalog_ciphertext_digest="not-a-digest",
            )

    def test_exactly_one_engineering_authority_when_enabled(self):
        for authority in ("none", "replica"):
            config = public_policy()
            config["banks"][0]["authority"] = authority
            with (
                self.subTest(authority=authority),
                self.assertRaisesRegex(PolicyError, "exactly one"),
            ):
                resolve_policy(
                    config,
                    self.catalog,
                    digest(self.catalog),
                    private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
                )
        config = public_policy()
        config["banks"].append(
            {
                "id": "engineering-shadow",
                "kind": "engineering",
                "authority": "authoritative",
                "writable": True,
            }
        )
        with self.assertRaisesRegex(PolicyError, "exactly one"):
            resolve_policy(
                config,
                self.catalog,
                digest(self.catalog),
                private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
            )

    def test_closed_tags_and_exactly_one_semantic_observation_scope(self):
        validate_tags(
            self.policy,
            ("agent:codex", "source:codex-hook", "scope:active", "kind:rule"),
        )
        validate_tags(
            self.policy,
            ("repo:synthetic-repository", "workflow:synthetic-review"),
        )
        with self.assertRaisesRegex(PolicyError, "unknown tag"):
            validate_tags(self.policy, ("repo:guessed",))
        self.assertEqual(
            observation_scope(self.policy, ("repo:synthetic-repository",)),
            "repo:synthetic-repository",
        )
        with self.assertRaisesRegex(PolicyError, "paired"):
            observation_scope(
                self.policy,
                ("repo:synthetic-repository", "scope:active"),
            )
        self.assertEqual(
            observation_scope(self.policy, ("agent:codex", "scope:active")),
            "scope:active",
        )
        self.assertEqual(
            observation_scope(
                self.policy, ("source:file-memory", "scope:archive")
            ),
            "scope:archive",
        )
        self.assertEqual(
            observation_scope(
                self.policy, ("source:airlock-bridge", "scope:airlock")
            ),
            "scope:airlock",
        )
        with self.assertRaisesRegex(PolicyError, "one lifecycle scope"):
            observation_scope(self.policy, ("scope:archive", "scope:airlock"))
        with self.assertRaisesRegex(
            PolicyError, "one semantic observation scope"
        ):
            observation_scope(
                self.policy, ("repo:synthetic-repository", "repo:guessed")
            )

    def test_home_and_context_selector_precedence(
        self,
    ):
        route = resolve_session_route(
            self.policy,
            explicit_home_bank="engineering",
            matched_workspaces=("workspace:personal",),
            workflow_selectors=("workflow:synthetic-review",),
            repository_selectors=("repo:synthetic-repository",),
        )
        self.assertEqual(route.home_bank, "engineering")
        self.assertEqual(route.contextual_model_id, "private-review-model")
        with self.assertRaisesRegex(PolicyError, "explicitly personal"):
            resolve_session_route(
                self.policy, matched_workspaces=("workspace:personal",)
            )
        route = resolve_session_route(
            self.policy,
            matched_workspaces=("workspace:personal",),
            personal_session=True,
        )
        self.assertEqual(route.home_bank, "personal")
        with self.assertRaisesRegex(PolicyError, "explicitly personal"):
            resolve_session_route(self.policy, explicit_home_bank="personal")
        route = resolve_session_route(
            self.policy, explicit_home_bank="personal", personal_session=True
        )
        self.assertEqual(route.home_bank, "personal")
        with self.assertRaisesRegex(PolicyError, "personal route"):
            resolve_session_route(
                self.policy,
                explicit_home_bank="engineering",
                personal_session=True,
            )
        with self.assertRaisesRegex(PolicyError, "isolated airlock"):
            resolve_session_route(self.policy, explicit_home_bank="airlock")

    def test_airlock_bank_cannot_be_an_ordinary_default_or_workspace_route(
        self,
    ):
        for field in ("machine_default", "workspace_mappings"):
            with self.subTest(field=field):
                config = public_policy()
                if field == "machine_default":
                    config[field] = "airlock"
                else:
                    config[field][0]["bank_id"] = "airlock"
                with self.assertRaisesRegex(PolicyError, "isolated airlock"):
                    resolve_policy(
                        config,
                        self.catalog,
                        digest(self.catalog),
                        private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
                    )

    def test_private_repository_aliases_are_disjoint_from_canonical_values(
        self,
    ):
        for field, value in (
            (
                "aliases",
                {"repo:synthetic-repository": "repo:synthetic-repository"},
            ),
            ("drop_aliases", ["repo:synthetic-repository"]),
        ):
            catalog = private_catalog()
            catalog["repository_catalog"][field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(PolicyError, "canonical"),
            ):
                resolve_policy(
                    public_policy(),
                    catalog,
                    digest(catalog),
                    private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
                )
        catalog = private_catalog()
        catalog["repository_catalog"]["drop_aliases"] = ["invalid alias"]
        with self.assertRaisesRegex(PolicyError, "alias form"):
            resolve_policy(
                public_policy(),
                catalog,
                digest(catalog),
                private_catalog_ciphertext_digest=CIPHERTEXT_DIGEST,
            )

    def test_uncertain_context_and_arbitrary_companion_banks_fail_closed(self):
        route = resolve_session_route(
            self.policy,
            workflow_selectors=(
                "workflow:synthetic-review",
                "workflow:unknown",
            ),
            repository_selectors=("repo:synthetic-repository",),
        )
        self.assertIsNone(route.contextual_model_id)
        route = resolve_session_route(
            self.policy, requested_companions=("personal",)
        )
        self.assertEqual(route.companion_banks, ("personal",))
        with self.assertRaisesRegex(PolicyError, "caller-supplied companion"):
            resolve_session_route(self.policy, requested_companions=("other",))

    def test_transient_sensitive_and_reversed_inputs_never_become_policy(self):
        forbidden = (
            "transient_state",
            "credential",
            "tool_traffic",
            "injected_memory_block",
            "recently_reversed_convention",
        )
        for input_class in forbidden:
            with (
                self.subTest(input_class=input_class),
                self.assertRaisesRegex(PolicyError, "durable policy input"),
            ):
                validate_durable_policy_input((input_class,))
        validate_durable_policy_input(("settled_user_rule", "verified_runbook"))


def provider(
    provider_id,
    role,
    *,
    artifact_id,
    placement="local",
    state="current",
    gates=None,
    fallback=None,
    revision="rev-1",
    active_revision="rev-1",
    active_artifact_id=None,
):
    if role == "llm":
        api = (
            "openai-responses"
            if artifact_id == "gpt-5.3-codex-spark"
            else "anthropic-messages"
        )
    elif role == "embedding":
        api = "openai-compatible"
    else:
        api = "cohere-compatible"
    return {
        "id": provider_id,
        "role": role,
        "placement": placement,
        "data_classes": ["engineering", "personal"],
        "transport": {
            "protocol": "https" if placement != "local" else "loopback",
            "api": api,
        },
        "tls": {"server_name": "provider.invalid", "trust_roots": ["system"]}
        if placement == "private-remote"
        else None,
        "credential": None
        if placement == "local"
        else {"mode": "keychain", "locator": f"keychain:{provider_id}"},
        "readiness": {
            "ready": True,
            "version_compatible": True,
            "license_ready": True,
        },
        "model": {
            "artifact_id": artifact_id,
            "active_artifact_id": (
                artifact_id
                if active_artifact_id is None
                else active_artifact_id
            ),
            "revision": revision,
            "active_revision": active_revision,
            "reasoning_effort": (
                "xhigh"
                if artifact_id == "gpt-5.3-codex-spark"
                else "default"
                if role == "llm"
                else None
            ),
        },
        "contract": {
            "readiness_probe": {
                "kind": "http" if placement != "local" else "process",
                "target": "health",
            },
            "timeout_seconds": 30,
            "no_payload_log": True,
            "api_compatible": True,
        },
        "state": state,
        "gates": {} if gates is None else gates,
        "fallback": fallback,
    }


class ProviderCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.providers = [
            provider(
                "claude-code-live",
                "llm",
                artifact_id="claude-code",
                placement="third-party-hosted",
            ),
            provider(
                "codex-spark-desired",
                "llm",
                artifact_id="gpt-5.3-codex-spark",
                placement="third-party-hosted",
                state="desired",
                gates={"provider_adapter_sends_reasoning_effort": False},
            ),
            provider(
                "openai-embedding",
                "embedding",
                artifact_id="text-embedding-3-small",
                placement="third-party-hosted",
            ),
            provider(
                "jina-mlx-live",
                "reranking",
                artifact_id="nisavid/mxbai-rerank-large-v2-mlx-4bit",
            ),
            provider(
                "memreranker-desired",
                "reranking",
                artifact_id="nisavid/MemReranker-4B-OptiQ-4bit",
                state="desired",
                gates={
                    "cohere_adapter_compatibility": False,
                    "private_benchmark": False,
                },
                fallback="jina-mlx-live",
            ),
        ]
        self.profile = {
            "id": "core",
            "data_classes": ["engineering", "personal"],
            "roles": {
                "llm": {
                    "current": "claude-code-live",
                    "desired": "codex-spark-desired",
                },
                "embedding": {"current": "openai-embedding"},
                "reranking": {
                    "current": "jina-mlx-live",
                    "desired": "memreranker-desired",
                },
            },
            "allowed_placements": {
                "engineering": [
                    "local",
                    "third-party-hosted",
                    "private-remote",
                ],
                "personal": ["local", "third-party-hosted", "private-remote"],
            },
            "llm_failover": ["claude-code-live"],
        }
        self.storage = {
            "populated": True,
            "embedding_artifact_id": "text-embedding-3-small",
            "embedding_revision": "rev-1",
        }

    def validate(self, providers=None, profile=None, storage=None, switches=()):
        return validate_provider_compatibility(
            self.profile if profile is None else profile,
            self.providers if providers is None else providers,
            self.storage if storage is None else storage,
            revision_switches=switches,
        )

    def test_roles_independent_and_desired_candidates_blocked(
        self,
    ):
        report = self.validate()
        self.assertEqual(
            report.role_bindings["llm"],
            {"current": "claude-code-live", "desired": "codex-spark-desired"},
        )
        self.assertEqual(report.result("claude-code-live").state, "current")
        self.assertTrue(report.result("claude-code-live").activatable)
        self.assertEqual(report.result("jina-mlx-live").state, "current")
        spark = report.result("codex-spark-desired")
        self.assertEqual(
            (spark.state, spark.activatable), ("blocked_candidate", False)
        )
        self.assertIn(
            "provider_adapter_sends_reasoning_effort", spark.blocked_by
        )
        mem = report.result("memreranker-desired")
        self.assertEqual(
            (mem.state, mem.activatable), ("blocked_candidate", False)
        )
        self.assertEqual(
            mem.blocked_by,
            ("cohere_adapter_compatibility", "private_benchmark"),
        )
        self.assertEqual(
            report.reranking_disposition,
            {
                "state": "fallback",
                "provider_id": "jina-mlx-live",
                "visible_degradation": True,
            },
        )
        with self.assertRaises(FrozenInstanceError):
            mem.activatable = True

    def test_named_desired_candidates_require_complete_gate_evidence(self):
        for index in (1, 4):
            providers = list(self.providers)
            providers[index] = {**providers[index], "gates": {}}
            with (
                self.subTest(provider=providers[index]["id"]),
                self.assertRaisesRegex(
                    ProviderCompatibilityError,
                    "required candidate gates",
                ),
            ):
                self.validate(providers=providers)

    def test_named_desired_candidates_cannot_be_omitted(self):
        for role in ("llm", "reranking"):
            profile = {
                **self.profile,
                "roles": {
                    **self.profile["roles"],
                    role: {"current": self.profile["roles"][role]["current"]},
                },
            }
            with (
                self.subTest(role=role),
                self.assertRaisesRegex(
                    ProviderCompatibilityError,
                    "desired",
                ),
            ):
                self.validate(profile=profile)

    def test_llm_failover_is_optional(self):
        profile = {**self.profile, "llm_failover": []}
        report = self.validate(profile=profile)
        self.assertEqual(
            report.role_bindings["llm"]["current"], "claude-code-live"
        )

    def test_placement_data_class_and_role_mismatch_fail_closed(self):
        providers = list(self.providers)
        providers[0] = {**providers[0], "data_classes": ["engineering"]}
        with self.assertRaisesRegex(ProviderCompatibilityError, "personal"):
            self.validate(providers=providers)
        providers = list(self.providers)
        model = {**providers[0]["model"], "reasoning_effort": None}
        providers[0] = {
            **providers[0],
            "role": "embedding",
            "model": model,
        }
        with self.assertRaisesRegex(ProviderCompatibilityError, "role"):
            self.validate(providers=providers)

    def test_private_remote_requires_tls_identity_and_trust_roots(self):
        providers = list(self.providers)
        providers[0] = {
            **providers[0],
            "placement": "private-remote",
            "tls": None,
        }
        with self.assertRaisesRegex(ProviderCompatibilityError, "TLS identity"):
            self.validate(providers=providers)

    def test_credentials_are_locators_only_and_never_values(self):
        providers = list(self.providers)
        providers[0] = {
            **providers[0],
            "credential": {
                "mode": "keychain",
                "locator": "keychain:item",
                "value": "secret",
            },
        }
        with self.assertRaisesRegex(ProviderCompatibilityError, "credential"):
            self.validate(providers=providers)
        providers = list(self.providers)
        providers[3] = {
            **providers[3],
            "credential": {"mode": "keychain", "locator": ""},
        }
        with self.assertRaisesRegex(
            ProviderCompatibilityError, "credential locator"
        ):
            self.validate(providers=providers)
        providers = list(self.providers)
        providers[0] = {
            **providers[0],
            "credential": {
                "mode": "keychain",
                "locator": "inline-secret",
            },
        }
        with self.assertRaisesRegex(
            ProviderCompatibilityError,
            "locator shape",
        ):
            self.validate(providers=providers)

    def test_provider_contract_is_complete_and_fail_closed(self):
        for key, value in (
            ("readiness_probe", None),
            ("timeout_seconds", 0),
            ("no_payload_log", False),
            ("api_compatible", False),
        ):
            providers = list(self.providers)
            contract = dict(providers[0]["contract"])
            contract[key] = value
            providers[0] = {**providers[0], "contract": contract}
            with (
                self.subTest(key=key),
                self.assertRaises(ProviderCompatibilityError),
            ):
                self.validate(providers=providers)

    def test_readiness_version_and_license_are_independent_gates(self):
        for gate in ("ready", "version_compatible", "license_ready"):
            providers = list(self.providers)
            readiness = dict(providers[0]["readiness"])
            readiness[gate] = False
            providers[0] = {**providers[0], "readiness": readiness}
            with self.subTest(gate=gate):
                result = self.validate(providers=providers).result(
                    "claude-code-live"
                )
                self.assertFalse(result.activatable)
                self.assertIn(gate, result.blocked_by)

    def test_populated_embedding_identity_requires_explicit_blue_green_switch(
        self,
    ):
        providers = list(self.providers)
        providers[2] = provider(
            "openai-embedding",
            "embedding",
            artifact_id="other-embedding",
            placement="third-party-hosted",
            revision="rev-2",
            active_revision="rev-1",
        )
        blocked = self.validate(providers=providers).result("openai-embedding")
        self.assertFalse(blocked.activatable)
        self.assertIn("embedding_identity_immutable", blocked.blocked_by)
        switches = (
            {
                "provider_id": "openai-embedding",
                "from_artifact_id": "text-embedding-3-small",
                "from_revision": "rev-1",
                "to_artifact_id": "other-embedding",
                "to_revision": "rev-2",
                "blue_green_rebuild": True,
                "approved": True,
            },
        )
        allowed = self.validate(providers=providers, switches=switches).result(
            "openai-embedding"
        )
        self.assertTrue(allowed.activatable)

    def test_revision_drift_requires_an_exact_explicit_switch(self):
        providers = list(self.providers)
        providers[3] = provider(
            "jina-mlx-live",
            "reranking",
            artifact_id="nisavid/mxbai-rerank-large-v2-mlx-4bit",
            revision="rev-2",
            active_revision="rev-1",
        )
        result = self.validate(providers=providers).result("jina-mlx-live")
        self.assertIn("revision_switch_not_approved", result.blocked_by)

    def test_artifact_drift_requires_an_exact_explicit_switch(self):
        providers = list(self.providers)
        providers[3] = provider(
            "jina-mlx-live",
            "reranking",
            artifact_id="nisavid/mxbai-rerank-large-v2-mlx-4bit",
            active_artifact_id="previous-reranker",
        )
        result = self.validate(providers=providers).result("jina-mlx-live")
        self.assertIn("revision_switch_not_approved", result.blocked_by)

    def test_dangling_or_irrelevant_switches_fail_closed(self):
        switch = {
            "provider_id": "missing-provider",
            "from_artifact_id": "old",
            "from_revision": "old-rev",
            "to_artifact_id": "new",
            "to_revision": "new-rev",
            "blue_green_rebuild": False,
            "approved": True,
        }
        with self.assertRaisesRegex(
            ProviderCompatibilityError,
            "revision switch",
        ):
            self.validate(switches=(switch,))

    def test_current_machine_keeps_claude_and_jina_current(self):
        providers = list(self.providers)
        providers[0] = provider(
            "claude-code-live",
            "llm",
            artifact_id="unexpected-current-llm",
            placement="third-party-hosted",
        )
        with self.assertRaisesRegex(
            ProviderCompatibilityError,
            "current LLM",
        ):
            self.validate(providers=providers)

        providers = list(self.providers)
        providers[3] = provider(
            "jina-mlx-live",
            "reranking",
            artifact_id="unexpected-current-reranker",
        )
        with self.assertRaisesRegex(
            ProviderCompatibilityError,
            "current reranker",
        ):
            self.validate(providers=providers)

    def test_incompatible_reranker_without_fallback_is_visibly_disabled(self):
        providers = list(self.providers)
        providers[3] = {
            **providers[3],
            "readiness": {
                "ready": False,
                "version_compatible": True,
                "license_ready": True,
            },
        }
        providers[4] = {**providers[4], "fallback": None}
        report = self.validate(providers=providers)
        self.assertEqual(
            report.reranking_disposition,
            {
                "state": "disabled",
                "provider_id": None,
                "visible_degradation": True,
            },
        )

    def test_unbound_declared_reranker_fallback_is_evaluated(self):
        providers = [
            *self.providers,
            provider(
                "alternate-reranker",
                "reranking",
                artifact_id="alternate-reranker-artifact",
                state="fallback",
            ),
        ]
        providers[4] = {
            **providers[4],
            "fallback": "alternate-reranker",
        }

        report = self.validate(providers=providers)

        self.assertTrue(report.result("alternate-reranker").activatable)
        self.assertEqual(
            report.reranking_disposition,
            {
                "state": "fallback",
                "provider_id": "alternate-reranker",
                "visible_degradation": True,
            },
        )

    def test_reranker_fallback_must_exist_and_serve_reranking(self):
        for fallback in ("missing-provider", "claude-code-live"):
            providers = list(self.providers)
            providers[4] = {**providers[4], "fallback": fallback}
            with (
                self.subTest(fallback=fallback),
                self.assertRaisesRegex(
                    ProviderCompatibilityError, "reranker fallback"
                ),
            ):
                self.validate(providers=providers)


if __name__ == "__main__":
    unittest.main()
