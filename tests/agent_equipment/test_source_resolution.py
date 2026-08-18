from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from agent_equipment import source_resolution
from agent_equipment.canonical import canonical_json_sha256
from agent_equipment.model import FrozenJsonObject, freeze_json, thaw_json
from agent_equipment.secrets import contains_literal_credential
from agent_equipment.source_resolution import (
    MAX_SOURCE_FIELD_CHARACTERS,
    MAX_SOURCE_RESOLUTION_BYTES,
    MAX_SOURCE_RESOLUTION_DEPTH,
    MAX_SOURCE_RESOLUTION_REQUEST_BYTES,
    SourceResolution,
    SourceResolutionRequest,
    admit_source_manifest,
    admit_source_resolution,
    admit_source_resolution_request,
    materialize_source_manifest,
)

CATALOG_DIGEST = f"sha256:{'a' * 64}"
LOCK_DIGEST = f"sha256:{'b' * 64}"
LITERAL_SECRET_ERROR = "source-resolution input contains literal secret material"
OLD_GIT_REVISION = "0123456789abcdef0123456789abcdef01234567"
NEW_GIT_REVISION = "89abcdef0123456789abcdef0123456789abcdef"
OLD_CONTENT_DIGEST = f"sha256:{'1' * 64}"
NEW_CONTENT_DIGEST = f"sha256:{'2' * 64}"
EQUIPMENT = ("skill:example/a", "skill:example/b")


def patterned_value(prefix: str, length: int) -> str:
    if length < len(prefix):
        raise ValueError("fixture length is shorter than its prefix")
    return prefix + "a" * (length - len(prefix))


def public_git_repository(length: int) -> str:
    prefix = "https://example.com/"
    suffix = ".git"
    if length < len(prefix) + len(suffix) + 1:
        raise ValueError("fixture repository length is too short")
    return prefix + "a" * (length - len(prefix) - len(suffix)) + suffix


def artifact_suffix_for_total_length(length: int) -> str:
    prefix = f"git+https://example.com/equipment.git@{OLD_GIT_REVISION}#"
    if length < len(prefix) + 1:
        raise ValueError("fixture artifact length is too short")
    return "#" + "a" * (length - len(prefix))


def frozen_object(document: object) -> FrozenJsonObject:
    frozen = freeze_json(document)
    if not isinstance(frozen, FrozenJsonObject):
        raise TypeError("fixture must be an object")
    return frozen


def reseal(document: dict[str, object], digest_field: str) -> FrozenJsonObject:
    payload = {key: value for key, value in document.items() if key != digest_field}
    return frozen_object(payload | {digest_field: canonical_json_sha256(payload)})


def source_manifest(
    *,
    distribution_identity: str,
    source: dict[str, object],
    resolved_source: dict[str, object],
    restore: dict[str, object],
    available_equipment: tuple[str, ...] = EQUIPMENT,
    equipment: tuple[str, ...] = ("skill:example/a",),
) -> FrozenJsonObject:
    payload: dict[str, object] = {
        "schema_version": "source-manifest/v1",
        "distribution_identity": distribution_identity,
        "source": copy.deepcopy(source),
        "resolved_source": copy.deepcopy(resolved_source),
        "available_equipment": list(available_equipment),
        "membership_evidence": {
            "kind": "authoritative_source_listing",
            "evidence_digest": canonical_json_sha256(
                {"available_equipment": list(available_equipment)}
            ),
        },
        "equipment": list(equipment),
        "restore": copy.deepcopy(restore),
    }
    return reseal(payload, "source_manifest_digest")


def git_manifest(
    *,
    source: dict[str, object] | None = None,
    artifact_suffix: str = "#skills/a,skills/b",
    distribution_identity: str = "distribution:example/git",
) -> FrozenJsonObject:
    configured = source or {
        "kind": "git",
        "repository": "https://example.com/equipment.git",
    }
    repository = configured["repository"]
    return source_manifest(
        distribution_identity=distribution_identity,
        source=configured,
        resolved_source={"kind": "git", "revision": OLD_GIT_REVISION},
        restore={
            "class": "immutable",
            "revision": OLD_GIT_REVISION,
            "artifact_ref": (f"git+{repository}@{OLD_GIT_REVISION}{artifact_suffix}"),
            "content_digest": OLD_CONTENT_DIGEST,
            "native_update_control": "not_applicable",
        },
    )


def native_version(kind: str, value: str | None = None) -> dict[str, object]:
    document: dict[str, object] = {"kind": kind}
    if value is not None:
        document["value"] = value
    return document


def native_restore(
    source: dict[str, object],
    version: dict[str, object],
    *,
    observation_source: str = "reviewed manager metadata",
    native_update_control: str = "suppressible",
) -> dict[str, object]:
    manager = source["manager"]
    package = source["package"]
    channel = source.get("channel", "latest")
    value = version.get("value")
    if manager == "npx":
        restore_channel = f"npm:{value}"
        baseline = f"{package}@{value}"
    elif manager == "http":
        restore_channel = channel
        baseline = package
    else:
        restore_channel = channel
        baseline = value
    return {
        "class": "native_rolling",
        "channel": restore_channel,
        "reviewed_baseline": baseline,
        "observation_source": observation_source,
        "native_update_control": native_update_control,
    }


def native_manifest(
    *,
    source: dict[str, object],
    version: dict[str, object],
    distribution_identity: str = "distribution:example/native",
) -> FrozenJsonObject:
    return source_manifest(
        distribution_identity=distribution_identity,
        source=source,
        resolved_source={"kind": "native_manager", "version": version},
        restore=native_restore(source, version),
    )


def request_document(
    *,
    source: object,
    selection: object,
    base_source_manifest_digest: str,
    distribution_identity: str = "distribution:example/equipment",
) -> FrozenJsonObject:
    payload = {
        "schema_version": "source-resolution-request/v1",
        "command": "update",
        "base_catalog_digest": CATALOG_DIGEST,
        "base_lock_digest": LOCK_DIGEST,
        "distribution_identity": distribution_identity,
        "source": source,
        "base_source_manifest_digest": base_source_manifest_digest,
        "selection": selection,
    }
    return reseal(payload, "request_digest")


def source_request(
    *,
    source: object,
    selection: object,
    base_manifest: FrozenJsonObject | None = None,
    distribution_identity: str = "distribution:example/equipment",
) -> SourceResolutionRequest:
    digest = (
        base_manifest["source_manifest_digest"]
        if base_manifest is not None
        else f"sha256:{'c' * 64}"
    )
    if not isinstance(digest, str):
        raise TypeError("fixture manifest digest must be a string")
    return admit_source_resolution_request(
        request_document(
            source=source,
            selection=selection,
            distribution_identity=distribution_identity,
            base_source_manifest_digest=digest,
        )
    )


def resolution_document(
    request: SourceResolutionRequest,
    facts: dict[str, object],
) -> FrozenJsonObject:
    payload = {
        "schema_version": "source-resolution-facts/v1",
        "request_digest": request.request_digest,
        "facts": copy.deepcopy(facts),
    }
    return reseal(payload, "resolution_digest")


def git_facts(
    *,
    revision: str = NEW_GIT_REVISION,
    content_digest: str = NEW_CONTENT_DIGEST,
    available_equipment: tuple[str, ...] = EQUIPMENT,
) -> dict[str, object]:
    return {
        "kind": "git",
        "revision": revision,
        "content_digest": content_digest,
        "available_equipment": list(available_equipment),
    }


def native_facts(
    version: dict[str, object],
    *,
    available_equipment: tuple[str, ...] = EQUIPMENT,
) -> dict[str, object]:
    return {
        "kind": "native_manager",
        "version": copy.deepcopy(version),
        "available_equipment": list(available_equipment),
    }


def admitted_resolution(
    request: SourceResolutionRequest,
    facts: dict[str, object],
) -> SourceResolution:
    return admit_source_resolution(request, resolution_document(request, facts))


class SourceResolutionRequestTest(unittest.TestCase):
    def test_admits_closed_digest_bound_tracking_requests(self) -> None:
        sources = (
            {"kind": "git", "repository": "https://example.com/equipment.git"},
            {
                "kind": "git",
                "repository": "https://example.com/equipment.git",
                "branch": "release/v2",
            },
            {"kind": "native_manager", "manager": "npx", "package": "tool"},
            {
                "kind": "native_manager",
                "manager": "claude",
                "package": "tool@official",
                "channel": "stable",
            },
        )
        for source in sources:
            with self.subTest(source=source):
                request = source_request(source=source, selection={"all": True})
                self.assertEqual(thaw_json(request.source), source)

        invalid = thaw_json(
            request_document(
                source=sources[0],
                selection={"all": True},
                base_source_manifest_digest=f"sha256:{'c' * 64}",
            )
        )
        assert isinstance(invalid, dict)
        invalid["request_digest"] = f"sha256:{'0' * 64}"
        with self.assertRaisesRegex(ValueError, "request digest"):
            admit_source_resolution_request(frozen_object(invalid))

    def test_request_rejects_hostile_sources_selections_and_extras(self) -> None:
        valid_source = {
            "kind": "git",
            "repository": "https://example.com/equipment.git",
        }
        invalid_branches = (
            "HEAD",
            "-release",
            ".release",
            "release/.hidden",
            "release//candidate",
            "release..candidate",
            "release@{candidate",
            "release\\candidate",
            "release.lock",
            "release/",
            "release.",
            "release candidate",
        )
        for branch in invalid_branches:
            with (
                self.subTest(branch=branch),
                self.assertRaisesRegex(ValueError, "branch"),
            ):
                source_request(
                    source=valid_source | {"branch": branch},
                    selection={"all": True},
                )

        for document in (
            request_document(
                source=valid_source | {"to" + "ken": "redacted"},
                selection={"all": True},
                base_source_manifest_digest=f"sha256:{'c' * 64}",
            ),
            request_document(
                source=valid_source,
                selection={"equipment": ["skill:example/b", "skill:example/a"]},
                base_source_manifest_digest=f"sha256:{'c' * 64}",
            ),
            request_document(
                source={"kind": "git", "repository": "file:///tmp/private.git"},
                selection={"all": True},
                base_source_manifest_digest=f"sha256:{'c' * 64}",
            ),
        ):
            with (
                self.subTest(document=thaw_json(document)),
                self.assertRaises(ValueError),
            ):
                admit_source_resolution_request(document)

    def test_npx_package_cannot_hide_a_tag_or_version_selector(self) -> None:
        for package in ("tool@beta", "tool@1.2.3"):
            with (
                self.subTest(package=package),
                self.assertRaisesRegex(ValueError, "package|tracking policy"),
            ):
                source_request(
                    source={
                        "kind": "native_manager",
                        "manager": "npx",
                        "package": package,
                    },
                    selection={"all": True},
                )

        source_request(
            source={
                "kind": "native_manager",
                "manager": "npx",
                "package": "@example/tool",
            },
            selection={"all": True},
        )
        for manager in ("claude", "codex", "cursor"):
            with self.subTest(manager=manager):
                source_request(
                    source={
                        "kind": "native_manager",
                        "manager": manager,
                        "package": "tool@reviewed-registry",
                    },
                    selection={"all": True},
                )

    def test_request_rejects_literal_and_opaque_private_values(self) -> None:
        literal_canary = "sk-" + "x" * 32
        opaque_canary = "V7p!opaque.private.value!9Qx"
        self.assertFalse(contains_literal_credential(opaque_canary))
        for canary in (literal_canary, opaque_canary):
            with self.subTest(canary=canary), self.assertRaises(ValueError) as raised:
                source_request(
                    source={
                        "kind": "native_manager",
                        "manager": "npx",
                        "package": canary,
                    },
                    selection={"all": True},
                )
            self.assertNotIn(canary, str(raised.exception))

    def test_request_byte_bound_precedes_field_admission(self) -> None:
        oversized = request_document(
            source={
                "kind": "git",
                "repository": "https://example.com/"
                + "a" * MAX_SOURCE_RESOLUTION_REQUEST_BYTES
                + ".git",
            },
            selection={"all": True},
            base_source_manifest_digest=f"sha256:{'c' * 64}",
        )
        with self.assertRaisesRegex(ValueError, "byte bound"):
            admit_source_resolution_request(oversized)

    def test_request_source_and_identity_fields_share_the_manifest_bound(self) -> None:
        maximum_repository = public_git_repository(MAX_SOURCE_FIELD_CHARACTERS)
        maximum_branch = "a" * MAX_SOURCE_FIELD_CHARACTERS
        maximum_equipment = patterned_value(
            "skill:",
            MAX_SOURCE_FIELD_CHARACTERS,
        )
        maximum_distribution = patterned_value(
            "distribution:",
            MAX_SOURCE_FIELD_CHARACTERS,
        )
        source_request(
            source={
                "kind": "git",
                "repository": maximum_repository,
                "branch": maximum_branch,
            },
            selection={"equipment": [maximum_equipment]},
            distribution_identity=maximum_distribution,
        )

        over_limit = MAX_SOURCE_FIELD_CHARACTERS + 1
        cases = (
            (
                {"kind": "git", "repository": public_git_repository(over_limit)},
                {"all": True},
                "distribution:example/equipment",
            ),
            (
                {
                    "kind": "git",
                    "repository": "https://example.com/equipment.git",
                    "branch": "a" * over_limit,
                },
                {"all": True},
                "distribution:example/equipment",
            ),
            (
                {
                    "kind": "git",
                    "repository": "https://example.com/equipment.git",
                },
                {"equipment": [patterned_value("skill:", over_limit)]},
                "distribution:example/equipment",
            ),
            (
                {
                    "kind": "git",
                    "repository": "https://example.com/equipment.git",
                },
                {"all": True},
                patterned_value("distribution:", over_limit),
            ),
        )
        for source, selection, distribution_identity in cases:
            with (
                self.subTest(distribution_identity=distribution_identity),
                self.assertRaisesRegex(ValueError, "bounded|string|invalid"),
            ):
                source_request(
                    source=source,
                    selection=selection,
                    distribution_identity=distribution_identity,
                )


class SourceResolutionFactAdmissionTest(unittest.TestCase):
    def _assert_rejected_before_response_serialization(
        self,
        request: SourceResolutionRequest,
        document: FrozenJsonObject,
    ) -> None:
        canonical_json_bytes = source_resolution.canonical_json_bytes

        def guard(value: object) -> bytes:
            if value is document:
                raise AssertionError(
                    "untrusted source response reached canonical serialization"
                )
            return canonical_json_bytes(value)

        with (
            patch.object(source_resolution, "canonical_json_bytes", side_effect=guard),
            self.assertRaises((TypeError, ValueError)),
        ):
            admit_source_resolution(request, document)

    def test_rejects_a_delayed_frozen_response_subclass_without_invoking_it(
        self,
    ) -> None:
        canary = "V7pDelayedSourceExitPrivate9Qx"
        request = source_request(
            source={"kind": "git", "repository": "https://example.com/tool.git"},
            selection={"all": True},
        )
        valid = resolution_document(request, git_facts())

        class DelayedExitDocument(FrozenJsonObject):
            def __iter__(self):  # type: ignore[no-untyped-def]
                raise SystemExit(canary)

        hostile = DelayedExitDocument(tuple(valid.items()))

        with self.assertRaises((TypeError, ValueError)) as raised:
            admit_source_resolution(request, hostile)

        self.assertNotIn(canary, str(raised.exception))

    def test_oversized_response_is_rejected_before_canonical_serialization(
        self,
    ) -> None:
        request = source_request(
            source={"kind": "git", "repository": "https://example.com/tool.git"},
            selection={"all": True},
        )
        payload = thaw_json(resolution_document(request, git_facts()))
        assert isinstance(payload, dict)
        payload["hostile_extra"] = "x" * (MAX_SOURCE_RESOLUTION_BYTES + 1)
        oversized = frozen_object(payload)

        self._assert_rejected_before_response_serialization(request, oversized)

    def test_overdeep_response_is_rejected_before_canonical_serialization(
        self,
    ) -> None:
        request = source_request(
            source={"kind": "git", "repository": "https://example.com/tool.git"},
            selection={"all": True},
        )
        payload = thaw_json(resolution_document(request, git_facts()))
        assert isinstance(payload, dict)
        nested: object = "leaf"
        for _ in range(MAX_SOURCE_RESOLUTION_DEPTH + 1):
            nested = [nested]
        payload["hostile_extra"] = nested
        overdeep = frozen_object(payload)

        self._assert_rejected_before_response_serialization(request, overdeep)

    def test_admits_exact_git_facts(self) -> None:
        request = source_request(
            source={"kind": "git", "repository": "https://example.com/tool.git"},
            selection={"all": True},
        )
        document = resolution_document(request, git_facts())

        resolution = admit_source_resolution(request, document)

        self.assertEqual(resolution.document, document)
        self.assertEqual(resolution.request_digest, request.request_digest)
        self.assertEqual(thaw_json(resolution.facts), git_facts())

    def test_admits_only_manager_typed_native_versions(self) -> None:
        cases = (
            ("npx", "tool", None, native_version("semantic_version", "1.7.0")),
            (
                "claude",
                "tool@official",
                "stable",
                native_version("semantic_version", "1.0.4+codex.20260711030014"),
            ),
            (
                "cursor",
                "tool@marketplace",
                "preview",
                native_version("semantic_version", "2.3.4-beta.1+build.5"),
            ),
            ("codex", "tool@curated", "stable", native_version("revision", "11c74d6b")),
            (
                "http",
                "https://example.com/tool.json",
                "static",
                native_version("static_source"),
            ),
        )
        for manager, package, channel, version in cases:
            source: dict[str, object] = {
                "kind": "native_manager",
                "manager": manager,
                "package": package,
            }
            if channel is not None:
                source["channel"] = channel
            request = source_request(source=source, selection={"all": True})
            with self.subTest(manager=manager, version=version):
                resolution = admitted_resolution(request, native_facts(version))
                self.assertEqual(thaw_json(resolution.facts["version"]), version)

    def test_rejects_unknown_manager_version_combinations(self) -> None:
        cases = (
            ("claude", native_version("revision", "11c74d6b")),
            ("codex", native_version("semantic_version", "1.2.3")),
            ("http", native_version("semantic_version", "1.2.3")),
            ("brew", native_version("semantic_version", "1.2.3")),
        )
        for manager, version in cases:
            request = source_request(
                source={
                    "kind": "native_manager",
                    "manager": manager,
                    "package": "tool",
                },
                selection={"all": True},
            )
            with (
                self.subTest(manager=manager),
                self.assertRaisesRegex(ValueError, "manager.*version|version.*manager"),
            ):
                admitted_resolution(request, native_facts(version))

    def test_rejects_letters_only_codex_revision_canary(self) -> None:
        canary = "deadbeef"
        self.assertFalse(contains_literal_credential(canary))
        request = source_request(
            source={
                "kind": "native_manager",
                "manager": "codex",
                "package": "tool@curated",
            },
            selection={"all": True},
        )
        with self.assertRaisesRegex(ValueError, "revision") as raised:
            admitted_resolution(
                request, native_facts(native_version("revision", canary))
            )
        self.assertNotIn(canary, str(raised.exception))

    def test_rejects_legacy_full_manifest_response(self) -> None:
        base = git_manifest()
        request = source_request(
            source=thaw_json(base["source"]),
            selection={"all": True},
            base_manifest=base,
            distribution_identity=str(base["distribution_identity"]),
        )
        legacy_payload = {
            "schema_version": "source-resolution/v1",
            "request_digest": request.request_digest,
            "source_manifest": thaw_json(base),
        }
        legacy = reseal(legacy_payload, "resolution_digest")
        with self.assertRaisesRegex(ValueError, "closed|schema version"):
            admit_source_resolution(request, legacy)

    def test_rejects_hostile_extras_at_every_fact_boundary(self) -> None:
        request = source_request(
            source={"kind": "git", "repository": "https://example.com/tool.git"},
            selection={"all": True},
        )
        valid = thaw_json(resolution_document(request, git_facts()))
        assert isinstance(valid, dict)
        hostile_envelope = copy.deepcopy(valid)
        hostile_envelope["source"] = {"branch": "attacker"}
        hostile_envelope = thaw_json(reseal(hostile_envelope, "resolution_digest"))
        assert isinstance(hostile_envelope, dict)
        hostile_facts = git_facts() | {"branch": "attacker"}
        for document in (
            frozen_object(hostile_envelope),
            resolution_document(request, hostile_facts),
        ):
            with (
                self.subTest(document=thaw_json(document)),
                self.assertRaisesRegex(ValueError, "closed"),
            ):
                admit_source_resolution(request, document)

        native_request = source_request(
            source={"kind": "native_manager", "manager": "npx", "package": "tool"},
            selection={"all": True},
        )
        hostile_version = native_version("semantic_version", "1.2.3") | {
            "channel": "attacker"
        }
        with self.assertRaisesRegex(ValueError, "version.*closed"):
            admitted_resolution(native_request, native_facts(hostile_version))

    def test_response_rejects_literal_credentials_before_admission(self) -> None:
        canary = "sk-" + "x" * 32
        request = source_request(
            source={"kind": "git", "repository": "https://example.com/tool.git"},
            selection={"all": True},
        )
        document = thaw_json(resolution_document(request, git_facts()))
        assert isinstance(document, dict)
        document["resolution_digest"] = canary
        with self.assertRaises(ValueError) as raised:
            admit_source_resolution(request, frozen_object(document))
        self.assertEqual(str(raised.exception), LITERAL_SECRET_ERROR)
        self.assertNotIn(canary, str(raised.exception))


class SourceManifestTest(unittest.TestCase):
    def test_admits_fact_only_resolved_source_adjacent_to_its_source(self) -> None:
        manifests = (
            git_manifest(),
            native_manifest(
                source={
                    "kind": "native_manager",
                    "manager": "npx",
                    "package": "tool",
                },
                version=native_version("semantic_version", "1.2.3"),
            ),
            native_manifest(
                source={
                    "kind": "native_manager",
                    "manager": "codex",
                    "package": "tool@curated",
                    "channel": "stable",
                },
                version=native_version("revision", "11c74d6b"),
            ),
            native_manifest(
                source={
                    "kind": "native_manager",
                    "manager": "http",
                    "package": "https://example.com/tool.json",
                    "channel": "static",
                },
                version=native_version("static_source"),
            ),
        )
        for document in manifests:
            with self.subTest(source=thaw_json(document["source"])):
                manifest = admit_source_manifest(document)
                self.assertEqual(manifest.document, document)

    def test_manifest_rejects_mismatched_or_policy_bearing_resolved_source(
        self,
    ) -> None:
        base = thaw_json(git_manifest())
        assert isinstance(base, dict)
        hostile = copy.deepcopy(base)
        hostile["resolved_source"] = {
            "kind": "git",
            "repository": "https://attacker.invalid/tool.git",
            "branch": "main",
            "revision": OLD_GIT_REVISION,
        }
        hostile = thaw_json(reseal(hostile, "source_manifest_digest"))
        assert isinstance(hostile, dict)

        native = thaw_json(
            native_manifest(
                source={
                    "kind": "native_manager",
                    "manager": "codex",
                    "package": "tool@curated",
                },
                version=native_version("revision", "11c74d6b"),
            )
        )
        assert isinstance(native, dict)
        native["resolved_source"] = {
            "kind": "native_manager",
            "version": native_version("semantic_version", "1.2.3"),
        }
        native = thaw_json(reseal(native, "source_manifest_digest"))
        assert isinstance(native, dict)

        for document in (hostile, native):
            with self.subTest(document=document), self.assertRaises(ValueError):
                admit_source_manifest(frozen_object(document))

    def test_complete_manifest_string_fields_share_the_character_bound(self) -> None:
        maximum_distribution = patterned_value(
            "distribution:",
            MAX_SOURCE_FIELD_CHARACTERS,
        )
        maximum_equipment = patterned_value(
            "skill:",
            MAX_SOURCE_FIELD_CHARACTERS,
        )
        maximum = source_manifest(
            distribution_identity=maximum_distribution,
            source={
                "kind": "git",
                "repository": "https://example.com/equipment.git",
                "branch": "a" * MAX_SOURCE_FIELD_CHARACTERS,
            },
            resolved_source={"kind": "git", "revision": OLD_GIT_REVISION},
            restore={
                "class": "immutable",
                "revision": OLD_GIT_REVISION,
                "artifact_ref": (
                    "git+https://example.com/equipment.git@"
                    f"{OLD_GIT_REVISION}"
                    f"{artifact_suffix_for_total_length(MAX_SOURCE_FIELD_CHARACTERS)}"
                ),
                "content_digest": OLD_CONTENT_DIGEST,
                "native_update_control": "not_applicable",
            },
            available_equipment=(maximum_equipment,),
            equipment=(maximum_equipment,),
        )
        self.assertEqual(admit_source_manifest(maximum).document, maximum)

        over_limit = MAX_SOURCE_FIELD_CHARACTERS + 1
        oversized_manifests = (
            git_manifest(
                artifact_suffix="#" + "a" * over_limit,
            ),
            git_manifest(
                distribution_identity=patterned_value("distribution:", over_limit),
            ),
            source_manifest(
                distribution_identity="distribution:example/git",
                source={
                    "kind": "git",
                    "repository": "https://example.com/equipment.git",
                },
                resolved_source={"kind": "git", "revision": OLD_GIT_REVISION},
                restore={
                    "class": "immutable",
                    "revision": OLD_GIT_REVISION,
                    "artifact_ref": (
                        "git+https://example.com/equipment.git@" + OLD_GIT_REVISION
                    ),
                    "content_digest": OLD_CONTENT_DIGEST,
                    "native_update_control": "not_applicable",
                },
                available_equipment=(patterned_value("skill:", over_limit),),
                equipment=(patterned_value("skill:", over_limit),),
            ),
            git_manifest(
                source={
                    "kind": "git",
                    "repository": "https://example.com/equipment.git",
                    "branch": "a" * over_limit,
                }
            ),
            git_manifest(
                source={
                    "kind": "git",
                    "repository": public_git_repository(over_limit),
                },
                artifact_suffix="",
            ),
        )
        for document in oversized_manifests:
            with (
                self.subTest(source=thaw_json(document["source"])),
                self.assertRaisesRegex(ValueError, "bounded|string|invalid"),
            ):
                admit_source_manifest(document)


class SourceManifestMaterializationTest(unittest.TestCase):
    def test_materializes_git_facts_for_default_and_explicit_branch_policies(
        self,
    ) -> None:
        sources = (
            {"kind": "git", "repository": "https://example.com/tool.git"},
            {
                "kind": "git",
                "repository": "https://example.com/tool.git",
                "branch": "release/v2",
            },
        )
        for source in sources:
            base = git_manifest(
                source=source,
                artifact_suffix="#skills/a,skills/b",
                distribution_identity="distribution:example/git",
            )
            request = source_request(
                source=source,
                selection={"equipment": ["skill:example/b"]},
                base_manifest=base,
                distribution_identity="distribution:example/git",
            )
            resolution = admitted_resolution(request, git_facts())

            manifest = materialize_source_manifest(request, resolution, base)
            document = thaw_json(manifest.document)
            assert isinstance(document, dict)

            with self.subTest(source=source):
                self.assertEqual(document["source"], source)
                self.assertEqual(
                    document["resolved_source"],
                    {"kind": "git", "revision": NEW_GIT_REVISION},
                )
                self.assertEqual(document["available_equipment"], list(EQUIPMENT))
                self.assertEqual(document["equipment"], ["skill:example/b"])
                self.assertEqual(
                    document["membership_evidence"],
                    {
                        "kind": "authoritative_source_listing",
                        "evidence_digest": canonical_json_sha256(
                            {"available_equipment": list(EQUIPMENT)}
                        ),
                    },
                )
                self.assertEqual(
                    document["restore"],
                    {
                        "class": "immutable",
                        "revision": NEW_GIT_REVISION,
                        "artifact_ref": (
                            "git+https://example.com/tool.git@"
                            f"{NEW_GIT_REVISION}#skills/a,skills/b"
                        ),
                        "content_digest": NEW_CONTENT_DIGEST,
                        "native_update_control": "not_applicable",
                    },
                )
                self.assertEqual(admit_source_manifest(manifest.document), manifest)

    def test_all_selection_materializes_complete_membership(self) -> None:
        base = git_manifest(
            source={"kind": "git", "repository": "https://example.com/tool.git"},
            artifact_suffix="",
            distribution_identity="distribution:example/git",
        )
        request = source_request(
            source=thaw_json(base["source"]),
            selection={"all": True},
            base_manifest=base,
            distribution_identity="distribution:example/git",
        )
        manifest = materialize_source_manifest(
            request,
            admitted_resolution(request, git_facts()),
            base,
        )
        self.assertEqual(manifest.document["equipment"], tuple(EQUIPMENT))

    def test_materialization_rejects_an_overlong_reviewed_artifact_subpath(
        self,
    ) -> None:
        source = {"kind": "git", "repository": "https://example.com/equipment.git"}
        base = git_manifest(
            source=source,
            artifact_suffix="#" + "a" * (MAX_SOURCE_FIELD_CHARACTERS + 1),
            distribution_identity="distribution:example/git",
        )
        request = source_request(
            source=source,
            selection={"all": True},
            base_manifest=base,
            distribution_identity="distribution:example/git",
        )

        with self.assertRaisesRegex(ValueError, "bounded string"):
            materialize_source_manifest(
                request,
                admitted_resolution(request, git_facts()),
                base,
            )

    def test_materializes_native_facts_and_preserves_reviewed_controls(self) -> None:
        cases = (
            (
                {"kind": "native_manager", "manager": "npx", "package": "tool"},
                native_version("semantic_version", "2.0.0"),
                "npm:2.0.0",
                "tool@2.0.0",
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "claude",
                    "package": "tool@official",
                    "channel": "stable",
                },
                native_version("semantic_version", "2.0.0-rc.1"),
                "stable",
                "2.0.0-rc.1",
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "cursor",
                    "package": "tool@marketplace",
                    "channel": "preview",
                },
                native_version("semantic_version", "3.1.4"),
                "preview",
                "3.1.4",
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "codex",
                    "package": "tool@curated",
                    "channel": "openai-curated",
                },
                native_version("revision", "11c74d6b"),
                "openai-curated",
                "11c74d6b",
            ),
            (
                {
                    "kind": "native_manager",
                    "manager": "http",
                    "package": "https://example.com/tool.json",
                    "channel": "static",
                },
                native_version("static_source"),
                "static",
                "https://example.com/tool.json",
            ),
        )
        old_versions = {
            "npx": native_version("semantic_version", "1.0.0"),
            "claude": native_version("semantic_version", "1.0.0"),
            "cursor": native_version("semantic_version", "1.0.0"),
            "codex": native_version("revision", "1234abcd"),
            "http": native_version("static_source"),
        }
        for source, version, expected_channel, expected_baseline in cases:
            manager = str(source["manager"])
            base = native_manifest(
                source=source,
                version=old_versions[manager],
                distribution_identity="distribution:example/native",
            )
            base_document = thaw_json(base)
            assert isinstance(base_document, dict)
            base_restore = base_document["restore"]
            assert isinstance(base_restore, dict)
            base_restore["observation_source"] = "operator reviewed exact source"
            base_restore["native_update_control"] = "unsuppressible"
            base = reseal(base_document, "source_manifest_digest")
            request = source_request(
                source=source,
                selection={"all": True},
                base_manifest=base,
                distribution_identity="distribution:example/native",
            )

            materialized = materialize_source_manifest(
                request,
                admitted_resolution(request, native_facts(version)),
                base,
            )
            document = thaw_json(materialized.document)
            assert isinstance(document, dict)
            restore = document["restore"]
            assert isinstance(restore, dict)
            with self.subTest(manager=manager):
                self.assertEqual(
                    document["resolved_source"],
                    {"kind": "native_manager", "version": version},
                )
                self.assertEqual(restore["channel"], expected_channel)
                self.assertEqual(restore["reviewed_baseline"], expected_baseline)
                self.assertEqual(
                    restore["observation_source"],
                    "operator reviewed exact source",
                )
                self.assertEqual(
                    restore["native_update_control"],
                    "unsuppressible",
                )

    def test_materialization_binds_base_digest_distribution_source_and_selection(
        self,
    ) -> None:
        source = {"kind": "git", "repository": "https://example.com/tool.git"}
        base = git_manifest(
            source=source,
            artifact_suffix="",
            distribution_identity="distribution:example/git",
        )
        request = source_request(
            source=source,
            selection={"equipment": ["skill:example/a"]},
            base_manifest=base,
            distribution_identity="distribution:example/git",
        )
        resolution = admitted_resolution(
            request,
            git_facts(available_equipment=("skill:example/b",)),
        )
        with self.assertRaisesRegex(ValueError, "selection"):
            materialize_source_manifest(request, resolution, base)

        base_document = thaw_json(base)
        assert isinstance(base_document, dict)
        mutations = (
            ("distribution_identity", "distribution:example/other"),
            (
                "source",
                {"kind": "git", "repository": "https://example.com/other.git"},
            ),
        )
        valid_resolution = admitted_resolution(request, git_facts())
        for field, value in mutations:
            changed = copy.deepcopy(base_document)
            changed[field] = value
            if field == "source":
                changed_restore = changed["restore"]
                assert isinstance(changed_restore, dict)
                changed_restore["artifact_ref"] = (
                    f"git+https://example.com/other.git@{OLD_GIT_REVISION}"
                )
            changed = thaw_json(reseal(changed, "source_manifest_digest"))
            assert isinstance(changed, dict)
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "base.*request|digest"),
            ):
                materialize_source_manifest(
                    request,
                    valid_resolution,
                    frozen_object(changed),
                )

        wrong_digest_request_document = thaw_json(request.document)
        assert isinstance(wrong_digest_request_document, dict)
        wrong_digest_request_document["base_source_manifest_digest"] = (
            f"sha256:{'d' * 64}"
        )
        wrong_digest_request = admit_source_resolution_request(
            reseal(wrong_digest_request_document, "request_digest")
        )
        wrong_digest_resolution = admitted_resolution(
            wrong_digest_request,
            git_facts(),
        )
        with self.assertRaisesRegex(ValueError, "digest"):
            materialize_source_manifest(
                wrong_digest_request,
                wrong_digest_resolution,
                base,
            )

    def test_materialization_rejects_forged_request_convenience_fields(self) -> None:
        source = {"kind": "git", "repository": "https://example.com/tool.git"}
        base = git_manifest(
            source=source,
            artifact_suffix="",
            distribution_identity="distribution:example/git",
        )
        request = source_request(
            source=source,
            selection={"equipment": ["skill:example/a"]},
            base_manifest=base,
            distribution_identity="distribution:example/git",
        )
        resolution = admitted_resolution(request, git_facts())
        forged = SourceResolutionRequest(
            document=request.document,
            command=request.command,
            base_catalog_digest=request.base_catalog_digest,
            base_lock_digest=request.base_lock_digest,
            distribution_identity=request.distribution_identity,
            source=request.source,
            base_source_manifest_digest=request.base_source_manifest_digest,
            selection=frozen_object({"all": True}),
            request_digest=request.request_digest,
        )

        with self.assertRaisesRegex(ValueError, "request"):
            materialize_source_manifest(forged, resolution, base)


if __name__ == "__main__":
    unittest.main()
