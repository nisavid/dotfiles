#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import asyncpg


DEFAULT_DB_AUTH = ("hindsight", "hindsight")
DEFAULT_DB_NAME = "hindsight"
EXPECTED_BANK_ID_TABLES = {
    ("public", "async_operations"),
    ("public", "audit_log"),
    ("public", "bank_stats_cache"),
    ("public", "banks"),
    ("public", "chunks"),
    ("public", "directives"),
    ("public", "documents"),
    ("public", "entities"),
    ("public", "graph_maintenance_queue"),
    ("public", "invalidated_memory_units"),
    ("public", "llm_requests"),
    ("public", "memory_links"),
    ("public", "memory_units"),
    ("public", "mental_model_history"),
    ("public", "mental_models"),
    ("public", "observation_history"),
    ("public", "webhooks"),
}


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BankTable:
    schema: str
    table: str

    @property
    def qualified(self) -> str:
        return f"{quote_ident(self.schema)}.{quote_ident(self.table)}"


@dataclass(frozen=True)
class ForeignKey:
    schema: str
    table: str
    name: str
    definition: str

    @property
    def table_qualified(self) -> str:
        return f"{quote_ident(self.schema)}.{quote_ident(self.table)}"


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sanitize_profile(profile: str | None) -> str:
    if not profile:
        return "default"
    return re.sub(r"[^a-zA-Z0-9_-]", "-", profile)


def database_url_for_profile(profile: str) -> str:
    instance = f"hindsight-embed-{sanitize_profile(profile)}"
    pid_file = Path.home() / ".pg0" / "instances" / instance / "data" / "postmaster.pid"
    if not pid_file.exists():
        raise MigrationError(f"missing pg0 postmaster file: {pid_file}")

    lines = pid_file.read_text(encoding="utf-8").splitlines()
    if len(lines) < 4:
        raise MigrationError(f"malformed pg0 postmaster file: {pid_file}")

    port = lines[3].strip()
    if not port.isdigit():
        raise MigrationError(f"pg0 postmaster file has invalid port: {pid_file}")

    user, auth = DEFAULT_DB_AUTH
    return f"postgresql://{user}:{auth}@localhost:{port}/{DEFAULT_DB_NAME}"


async def fetch_bank_tables(conn: asyncpg.Connection) -> list[BankTable]:
    rows = await conn.fetch(
        """
        SELECT columns.table_schema, columns.table_name
        FROM information_schema.columns
        JOIN information_schema.tables
          ON tables.table_schema = columns.table_schema
         AND tables.table_name = columns.table_name
        WHERE columns.table_schema = 'public'
          AND columns.column_name = 'bank_id'
          AND tables.table_type = 'BASE TABLE'
        ORDER BY columns.table_schema, columns.table_name
        """
    )
    return [BankTable(row["table_schema"], row["table_name"]) for row in rows]


def validate_bank_tables(tables: list[BankTable]) -> None:
    actual = {(table.schema, table.table) for table in tables}
    missing = sorted(EXPECTED_BANK_ID_TABLES - actual)
    extra = sorted(actual - EXPECTED_BANK_ID_TABLES)
    if extra:
        raise MigrationError(
            "unreviewed bank_id tables: " + ", ".join(f"{schema}.{table}" for schema, table in extra)
        )
    if missing:
        message = "missing reviewed bank_id tables: " + ", ".join(f"{schema}.{table}" for schema, table in missing)
        if os.getenv("HINDSIGHT_EMBED_MIGRATION_STRICT_SCHEMA"):
            raise MigrationError(message)
        print(f"warning: {message}", file=sys.stderr)


async def fetch_unhandled_bank_columns(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT columns.table_schema, columns.table_name, columns.column_name
        FROM information_schema.columns
        JOIN information_schema.tables
          ON tables.table_schema = columns.table_schema
         AND tables.table_name = columns.table_name
        WHERE columns.table_schema = 'public'
          AND lower(columns.column_name) LIKE '%bank%'
          AND columns.column_name <> 'bank_id'
          AND tables.table_type = 'BASE TABLE'
        ORDER BY columns.table_schema, columns.table_name, columns.column_name
        """
    )
    return [f"{row['table_schema']}.{row['table_name']}.{row['column_name']}" for row in rows]


async def fetch_bank_counts(
    conn: asyncpg.Connection,
    tables: list[BankTable],
    bank_ids: list[str],
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for table in tables:
        table_counts: dict[str, int] = {}
        for bank_id in bank_ids:
            count = await conn.fetchval(
                f"SELECT count(*) FROM {table.qualified} WHERE bank_id = $1",
                bank_id,
            )
            table_counts[bank_id] = int(count or 0)
        counts[f"{table.schema}.{table.table}"] = table_counts
    return counts


async def fetch_distinct_bank_ids(conn: asyncpg.Connection, tables: list[BankTable]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for table in tables:
        rows = await conn.fetch(
            f"SELECT DISTINCT bank_id FROM {table.qualified} WHERE bank_id IS NOT NULL ORDER BY bank_id"
        )
        bank_ids = [row["bank_id"] for row in rows]
        if bank_ids:
            values[f"{table.schema}.{table.table}"] = bank_ids
    return values


async def fetch_foreign_keys(conn: asyncpg.Connection) -> list[ForeignKey]:
    rows = await conn.fetch(
        """
        SELECT ns.nspname AS schema_name,
               rel.relname AS table_name,
               con.conname AS constraint_name,
               pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = rel.relnamespace
        WHERE ns.nspname = 'public'
          AND con.contype = 'f'
          AND (
            EXISTS (
              SELECT 1
              FROM unnest(con.conkey) AS key(attnum)
              JOIN pg_attribute attr ON attr.attrelid = con.conrelid AND attr.attnum = key.attnum
              WHERE attr.attname = 'bank_id'
            )
            OR EXISTS (
              SELECT 1
              FROM unnest(con.confkey) AS key(attnum)
              JOIN pg_attribute attr ON attr.attrelid = con.confrelid AND attr.attnum = key.attnum
              WHERE attr.attname = 'bank_id'
            )
          )
        ORDER BY ns.nspname, rel.relname, con.conname
        """
    )
    return [
        ForeignKey(row["schema_name"], row["table_name"], row["constraint_name"], row["definition"])
        for row in rows
    ]


async def lock_tables(conn: asyncpg.Connection, tables: list[BankTable]) -> None:
    if not tables:
        return

    qualified_tables = ", ".join(table.qualified for table in tables)
    await conn.execute(f"LOCK TABLE {qualified_tables} IN SHARE ROW EXCLUSIVE MODE")


def print_counts(title: str, counts: dict[str, dict[str, int]]) -> None:
    print(title)
    for table, table_counts in counts.items():
        nonzero = {bank_id: count for bank_id, count in table_counts.items() if count}
        if not nonzero:
            continue
        rendered = ", ".join(f"{bank_id}={count}" for bank_id, count in nonzero.items())
        print(f"  {table}: {rendered}")


def source_reference_counts(
    counts: dict[str, dict[str, int]],
    source_banks: list[str],
    *,
    include_banks_table: bool = True,
) -> dict[str, int]:
    return {
        bank_id: sum(
            table_counts.get(bank_id, 0)
            for table, table_counts in counts.items()
            if include_banks_table or table != "public.banks"
        )
        for bank_id in source_banks
    }


def validate_distinct_bank_ids(
    distinct_bank_ids: dict[str, list[str]],
    source_banks: list[str],
    target_bank: str,
) -> None:
    unexpected_values: list[str] = []
    expected = {*source_banks, target_bank}
    for table, values in distinct_bank_ids.items():
        unexpected = [value for value in values if value not in expected]
        if unexpected:
            unexpected_values.append(f"{table}: {', '.join(unexpected)}")
    if unexpected_values:
        raise MigrationError(
            "database contains unplanned bank_id values; rerun with additional --source-bank values "
            "or resolve manually: "
            + "; ".join(unexpected_values)
        )


async def assert_target_bank(
    conn: asyncpg.Connection,
    target_bank: str,
) -> None:
    target_exists = await conn.fetchval('SELECT EXISTS (SELECT 1 FROM "public"."banks" WHERE bank_id = $1)', target_bank)
    if not target_exists:
        raise MigrationError(f"target bank does not exist: {target_bank}")


async def migrate(args: argparse.Namespace) -> None:
    database_url = database_url_for_profile(args.profile)
    conn = await asyncpg.connect(database_url)
    try:
        tables = await fetch_bank_tables(conn)
        validate_bank_tables(tables)
        update_tables = [table for table in tables if table.table != "banks"]
        bank_ids_to_count = [*args.source_bank, args.target_bank]
        counts = await fetch_bank_counts(conn, tables, bank_ids_to_count)
        distinct_bank_ids = await fetch_distinct_bank_ids(conn, tables)
        foreign_keys = await fetch_foreign_keys(conn)
        unhandled_columns = await fetch_unhandled_bank_columns(conn)

        print(f"profile: {args.profile}")
        print(f"target bank: {args.target_bank}")
        print(f"source banks: {', '.join(args.source_bank)}")
        print(f"bank-scoped tables: {len(update_tables)} updatable, banks row kept for target")
        print(f"foreign keys to cycle transactionally: {len(foreign_keys)}")
        print_counts("current rows by planned bank:", counts)

        validate_distinct_bank_ids(distinct_bank_ids, args.source_bank, args.target_bank)

        if unhandled_columns:
            raise MigrationError(
                "schema has bank-like columns that are not handled by this migration: "
                + ", ".join(unhandled_columns)
            )

        await assert_target_bank(conn, args.target_bank)

        source_refs = source_reference_counts(counts, args.source_bank, include_banks_table=False)
        source_non_bank_total = sum(source_refs.values())
        source_bank_row_total = sum(counts.get("public.banks", {}).get(bank_id, 0) for bank_id in args.source_bank)
        if source_non_bank_total == 0 and source_bank_row_total == 0:
            print("already clean: no source-bank references remain")
            return
        if source_non_bank_total == 0:
            if args.mode == "dry-run":
                print(f"dry-run: would delete {source_bank_row_total} source bank row(s); no non-bank references remain")
                return

        if args.mode == "dry-run":
            target_nonempty = sum(
                table_counts.get(args.target_bank, 0)
                for table, table_counts in counts.items()
                if table != "public.banks"
            )
            if target_nonempty and not args.allow_nonempty_target:
                raise MigrationError(
                    f"target bank has {target_nonempty} non-bank rows; rerun with --allow-nonempty-target "
                    "only after confirming they are safe to merge"
                )
            if target_nonempty:
                print(f"nonempty target override: {target_nonempty} existing non-bank rows")
            print("dry-run: no database changes made")
            return

        async with conn.transaction():
            await conn.execute("SET LOCAL lock_timeout = '10s'")
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('hindsight-single-bank-cleanup'))")
            await lock_tables(conn, tables)

            locked_distinct_bank_ids = await fetch_distinct_bank_ids(conn, tables)
            validate_distinct_bank_ids(locked_distinct_bank_ids, args.source_bank, args.target_bank)
            locked_counts = await fetch_bank_counts(conn, tables, bank_ids_to_count)
            locked_source_refs = source_reference_counts(locked_counts, args.source_bank, include_banks_table=False)
            locked_source_non_bank_total = sum(locked_source_refs.values())
            locked_source_bank_row_total = sum(
                locked_counts.get("public.banks", {}).get(bank_id, 0) for bank_id in args.source_bank
            )
            if locked_source_non_bank_total == 0 and locked_source_bank_row_total == 0:
                print("already clean: no source-bank references remain")
                return
            if locked_source_non_bank_total == 0:
                status = await conn.execute(
                    'DELETE FROM "public"."banks" WHERE bank_id = ANY($1::text[])',
                    args.source_bank,
                )
                print(f"public.banks: {status}")
                print("apply: source bank rows removed")
                return

            target_nonempty = sum(
                table_counts.get(args.target_bank, 0)
                for table, table_counts in locked_counts.items()
                if table != "public.banks"
            )
            if target_nonempty and not args.allow_nonempty_target:
                raise MigrationError(
                    f"target bank has {target_nonempty} non-bank rows; rerun with --allow-nonempty-target "
                    "only after confirming they are safe to merge"
                )
            if target_nonempty:
                print(f"nonempty target override: {target_nonempty} existing non-bank rows")

            for fk in foreign_keys:
                await conn.execute(
                    f"ALTER TABLE {fk.table_qualified} DROP CONSTRAINT {quote_ident(fk.name)}"
                )

            for table in update_tables:
                status = await conn.execute(
                    f"UPDATE {table.qualified} SET bank_id = $1 WHERE bank_id = ANY($2::text[])",
                    args.target_bank,
                    args.source_bank,
                )
                print(f"{table.schema}.{table.table}: {status}")

            remaining = await fetch_bank_counts(conn, update_tables, args.source_bank)
            remaining_total = sum(sum(table_counts.values()) for table_counts in remaining.values())
            if remaining_total:
                raise MigrationError(f"{remaining_total} source-bank references remain after update")

            await conn.execute(
                'DELETE FROM "public"."banks" WHERE bank_id = ANY($1::text[])',
                args.source_bank,
            )

            for fk in foreign_keys:
                await conn.execute(
                    f"ALTER TABLE {fk.table_qualified} ADD CONSTRAINT {quote_ident(fk.name)} {fk.definition}"
                )

        print("apply: migration committed")
    finally:
        await conn.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate Hindsight rows into a single canonical bank.")
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--source-bank", action="append", required=True)
    parser.add_argument("--target-bank", required=True)
    parser.add_argument("--allow-nonempty-target", action="store_true")
    args = parser.parse_args(argv)
    seen: set[str] = set()
    args.source_bank = [bank for bank in args.source_bank if not (bank in seen or seen.add(bank))]
    if args.target_bank in args.source_bank:
        raise MigrationError("target bank cannot also be a source bank")
    return args


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        asyncio.run(migrate(args))
    except (MigrationError, OSError, asyncpg.PostgresError) as exc:
        print(f"hindsight-embed-single-bank-migrate: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
