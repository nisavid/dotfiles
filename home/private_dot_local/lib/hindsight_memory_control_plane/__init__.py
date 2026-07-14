"""Desired-state primitives for the Hindsight memory control plane."""

from .canonical import canonical_bytes, digest
from .adapters import Adapter, AdapterError, AuthenticationError, FakeAdapter, RollbackBundle
from .http_adapter import HttpAdapter
from .inventory import InventoryError, load_inventory
from .ledger import LedgerError, append_record
from .migration_adapter import AdminMigrationAdapter, MigrationAdapterError
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
    ApplyError, ApplyResult, MutationPlan, apply_plan, build_mutation_plan,
    create_rollback_bundle, mutation_plan_from_dict, parse_migration_gate,
    verify_mutation_plan,
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
    "MigrationDiscovery",
    "MigrationError",
    "Plan",
    "PlanError",
    "RollbackBundle",
    "ShadowPlan",
    "FakeAdapter",
    "HttpAdapter",
    "apply_plan",
    "append_record",
    "build_plan",
    "build_mutation_plan",
    "canonical_bytes",
    "digest",
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
