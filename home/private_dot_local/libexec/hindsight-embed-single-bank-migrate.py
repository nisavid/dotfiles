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
    env_url = os.getenv("HINDSIGHT_EMBED_MIGRATION_DATABASE_URL")
    if env_url:
        return env_url

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
        SELECT table_schema, table_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name = 'bank_id'
        ORDER BY table_schema, table_name
        """
    )
    return [BankTable(row["table_schema"], row["table_name"]) for row in rows]


async def fetch_unhandled_bank_columns(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND lower(column_name) LIKE '%bank%'
          AND column_name <> 'bank_id'
        ORDER BY table_schema, table_name, column_name
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


def print_counts(title: str, counts: dict[str, dict[str, int]]) -> None:
    print(title)
    for table, table_counts in counts.items():
        nonzero = {bank_id: count for bank_id, count in table_counts.items() if count}
        if not nonzero:
            continue
        rendered = ", ".join(f"{bank_id}={count}" for bank_id, count in nonzero.items())
        print(f"  {table}: {rendered}")


async def assert_bank_rows(
    conn: asyncpg.Connection,
    target_bank: str,
    source_banks: list[str],
    counts: dict[str, dict[str, int]],
) -> None:
    target_exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM banks WHERE bank_id = $1)", target_bank)
    if not target_exists:
        raise MigrationError(f"target bank does not exist: {target_bank}")

    source_refs = {
        bank_id: sum(table_counts.get(bank_id, 0) for table_counts in counts.values())
        for bank_id in source_banks
    }
    missing = [bank_id for bank_id, count in source_refs.items() if count == 0]
    if missing:
        raise MigrationError(f"source bank has no references to migrate: {', '.join(missing)}")


async def migrate(args: argparse.Namespace) -> None:
    database_url = database_url_for_profile(args.profile)
    conn = await asyncpg.connect(database_url)
    try:
        tables = await fetch_bank_tables(conn)
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

        unexpected_values: list[str] = []
        expected = {*args.source_bank, args.target_bank}
        for table, values in distinct_bank_ids.items():
            unexpected = [value for value in values if value not in expected]
            if unexpected:
                unexpected_values.append(f"{table}: {', '.join(unexpected)}")
        if unexpected_values:
            print("other bank_id values left untouched:")
            for value in unexpected_values:
                print(f"  {value}")

        if unhandled_columns:
            raise MigrationError(
                "schema has bank-like columns that are not handled by this migration: "
                + ", ".join(unhandled_columns)
            )

        await assert_bank_rows(conn, args.target_bank, args.source_bank, counts)

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

        if args.mode == "dry-run":
            print("dry-run: no database changes made")
            return

        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('hindsight-single-bank-cleanup'))")

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
                "DELETE FROM banks WHERE bank_id = ANY($1::text[])",
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
    parser.add_argument("--profile", default="systalyze")
    parser.add_argument("--source-bank", action="append", default=[])
    parser.add_argument("--target-bank", default="engineering")
    parser.add_argument("--allow-nonempty-target", action="store_true")
    args = parser.parse_args(argv)
    if not args.source_bank:
        args.source_bank = ["claude_code", "Engineering"]
    else:
        seen: set[str] = set()
        args.source_bank = [bank for bank in args.source_bank if not (bank in seen or seen.add(bank))]
    if args.target_bank in args.source_bank:
        raise MigrationError("target bank cannot also be a source bank")
    return args


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        asyncio.run(migrate(args))
    except (MigrationError, asyncpg.PostgresError) as exc:
        print(f"hindsight-embed-single-bank-migrate: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
