"""Single closed catalog for controller action validation and dispatch."""

from __future__ import annotations


DESTRUCTIVE_ACTION_KINDS = frozenset(
    {
        "delete_bank",
        "delete_directive",
        "delete_model",
        "delete_profile",
        "import_bank",
        "migrate_bank",
        "prune_bank",
        "prune_model",
        "replace_canonical_bank",
        "retire_artifact",
    }
)

MUTATION_ACTION_KINDS = frozenset(
    {"import_bank", "migrate_bank", "replace_canonical_bank"}
)

ACTION_SCHEMAS = {
    "activate_model": frozenset({"profile_id", "provider_id", "model_id", "revision"}),
    "configure_bank": frozenset({"bank", "artifact_digest"}),
    "configure_profile": frozenset({"profile_id", "artifact_digest"}),
    "create_bank": frozenset({"bank"}),
    "install_model": frozenset(
        {"profile_id", "provider_id", "model_id", "revision", "artifact_digest"}
    ),
    "reload_profile": frozenset({"profile_id", "reason_code"}),
    "report_unmanaged": frozenset({"profile_id", "reason_code"}),
    "set_auto_consolidation": frozenset({"bank", "enabled"}),
    "set_memory_defense": frozenset({"bank", "enabled"}),
    "upsert_directive": frozenset({"bank", "directive_id", "artifact_digest"}),
    "upsert_model": frozenset({"bank", "model_id", "revision", "artifact_digest"}),
}

# Adapter method names are data so fake and HTTP adapters cannot silently drift.
ACTION_METHODS = {
    "activate_model": "upsert_model",
    "configure_bank": "patch_config",
    "configure_profile": "patch_config",
    "install_model": "upsert_model",
    "set_auto_consolidation": "patch_config",
    "set_memory_defense": "patch_config",
    "upsert_directive": "upsert_directive",
    "upsert_model": "upsert_model",
}

DIRECT_ACTION_KINDS = frozenset(
    {"create_bank", "import_bank", "migrate_bank", "reload_profile", "replace_canonical_bank", "report_unmanaged"}
)

ARTIFACT_ACTION_KINDS = frozenset(
    {"configure_bank", "configure_profile", "install_model", "upsert_directive", "upsert_model"}
)

EXECUTABLE_ACTION_KINDS = frozenset(ACTION_METHODS) | DIRECT_ACTION_KINDS

if frozenset(ACTION_METHODS) & DIRECT_ACTION_KINDS:
    raise RuntimeError("action kind has multiple adapter routes")
if frozenset(ACTION_SCHEMAS) - EXECUTABLE_ACTION_KINDS:
    raise RuntimeError("plannable action catalog contains no adapter route")
if MUTATION_ACTION_KINDS - EXECUTABLE_ACTION_KINDS:
    raise RuntimeError("migration action catalog contains no adapter route")
