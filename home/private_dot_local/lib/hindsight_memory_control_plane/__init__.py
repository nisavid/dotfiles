"""Desired-state primitives for the Hindsight memory control plane."""

from .canonical import StrictJsonError, canonical_bytes, digest, strict_json_loads
from .adapters import Adapter, AdapterError, AuthenticationError, FakeAdapter, RollbackBundle
from .http_adapter import HttpAdapter
from .inventory import InventoryError, load_inventory
from .ledger import LedgerError, append_record
from .migration_adapter import (
    AdminMigrationAdapter,
    MigrationAdapterError,
    MigrationApplyAdapter,
    hindsight_admin_argv,
)
from .migration import (
    MigrationDiscovery,
    MigrationError,
    ShadowPlan,
    discover_migration_state,
    verify_shadow_plan,
)
from .model import Action, BankRef, EndpointIdentity, Inventory, OperationSnapshot, Plan
from .planning import PlanError, build_plan, inventory_endpoint, plan_from_dict, verify_plan
from .reconcile import (
    ApplyError, ApplyResult, MigrationGateDescriptor, MutationPlan, apply_plan,
    build_mutation_plan, capture_migration_gate, create_rollback_bundle,
    mutation_plan_from_dict, parse_migration_gate, verify_mutation_plan,
)

__all__ = [
    "Action",
    "Adapter",
    "AdapterError",
    "AdminMigrationAdapter",
    "ApplyError",
    "ApplyResult",
    "AuthenticationError",
    "BankRef",
    "EndpointIdentity",
    "Inventory",
    "InventoryError",
    "LedgerError",
    "OperationSnapshot",
    "MutationPlan",
    "MigrationAdapterError",
    "MigrationApplyAdapter",
    "MigrationDiscovery",
    "MigrationError",
    "MigrationGateDescriptor",
    "Plan",
    "PlanError",
    "RollbackBundle",
    "ShadowPlan",
    "StrictJsonError",
    "FakeAdapter",
    "HttpAdapter",
    "hindsight_admin_argv",
    "apply_plan",
    "append_record",
    "build_plan",
    "build_mutation_plan",
    "capture_migration_gate",
    "canonical_bytes",
    "digest",
    "strict_json_loads",
    "discover_migration_state",
    "load_inventory",
    "inventory_endpoint",
    "create_rollback_bundle",
    "mutation_plan_from_dict",
    "parse_migration_gate",
    "plan_from_dict",
    "verify_plan",
    "verify_mutation_plan",
    "verify_shadow_plan",
]
