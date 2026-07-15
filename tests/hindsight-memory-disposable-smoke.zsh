#!/bin/zsh

set -euo pipefail
unsetopt BG_NICE

umask 077

typeset -r HINDSIGHT_API=${HINDSIGHT_API:-$(command -v hindsight-api)}
typeset -r HINDSIGHT_ADMIN=${HINDSIGHT_ADMIN:-$(command -v hindsight-admin)}
typeset -r HINDSIGHT_CLI=${HINDSIGHT_CLI:-$(command -v hindsight)}
typeset -r HINDSIGHT_PYTHON=${HINDSIGHT_PYTHON:-$(head -n 1 "$HINDSIGHT_API" | sed 's/^#!//')}
typeset -r CURL=${CURL:-$(command -v curl)}
typeset -r JQ=${JQ:-$(command -v jq)}
typeset -r OPENSSL=${OPENSSL:-$(command -v openssl)}
typeset -r HOST_HF_HOME=${HF_HOME:-$HOME/.cache/huggingface}

for executable in "$HINDSIGHT_API" "$HINDSIGHT_ADMIN" "$HINDSIGHT_CLI" \
  "$HINDSIGHT_PYTHON" "$CURL" "$JQ" "$OPENSSL"; do
  [[ -x "$executable" ]] || {
    print -u2 -- "required disposable-smoke executable is unavailable"
    exit 1
  }
done

typeset -r API_VERSION=$(
  "$HINDSIGHT_PYTHON" -c 'import importlib.metadata as m; print(m.version("hindsight-api"))'
)
typeset -r CLI_VERSION=$(
  "$HINDSIGHT_CLI" --version | awk '{print $2}'
)
[[ "$API_VERSION" == 0.8.4 && "$CLI_VERSION" == 0.8.4 ]] || {
  print -u2 -- "disposable smoke requires Hindsight API and CLI 0.8.4"
  exit 1
}

typeset -r SMOKE_PARENT=${TMPDIR:-/private/tmp}
typeset -r SMOKE_ROOT=$(mktemp -d "${SMOKE_PARENT%/}/hindsight-memory-smoke.XXXXXX")
typeset -r SMOKE_HOME="$SMOKE_ROOT/home"
typeset -r SMOKE_RUN_ID=$($OPENSSL rand -hex 16)
typeset -r SMOKE_PROFILE_MARKER="$SMOKE_ROOT/disposable-profile.marker"
typeset -r SOURCE_DATA="$SMOKE_ROOT/postgres-source"
typeset -r IMPORT_DATA="$SMOKE_ROOT/postgres-import"
typeset -r RESTORE_DATA="$SMOKE_ROOT/postgres-restore"
typeset -r SOURCE_BANK=smoke-source
typeset -r IMPORT_BANK=smoke-imported
typeset -r API_KEY=$($OPENSSL rand -hex 32)
typeset -r SOURCE_DB_PASSWORD=$($OPENSSL rand -hex 24)
typeset -r IMPORT_DB_PASSWORD=$($OPENSSL rand -hex 24)
typeset -r RESTORE_DB_PASSWORD=$($OPENSSL rand -hex 24)
typeset -r EXPORT_PASSPHRASE_FILE="$SMOKE_ROOT/export.passphrase"
typeset -r CURL_AUTH_CONFIG="$SMOKE_ROOT/curl-auth.conf"
typeset -a API_PIDS=()
typeset -a PG_NAMES=()
typeset CURRENT_PHASE=bootstrap
typeset CLEANED_UP=0

mkdir -p "$SMOKE_HOME" "$SOURCE_DATA" "$IMPORT_DATA" "$RESTORE_DATA"
/usr/bin/install -m 600 /dev/null "$SMOKE_PROFILE_MARKER"
print -r -- "$SMOKE_RUN_ID" >"$SMOKE_PROFILE_MARKER"
$OPENSSL rand -out "$EXPORT_PASSPHRASE_FILE" 48
print -r -- "header = \"Authorization: Bearer $API_KEY\"" >"$CURL_AUTH_CONFIG"
chmod 600 "$CURL_AUTH_CONFIG"

cleanup() {
  emulate -L zsh
  unsetopt ERR_EXIT
  (( CLEANED_UP )) && return 0
  CLEANED_UP=1
  local pid name registration
  for pid in $API_PIDS; do
    kill -TERM "$pid" >/dev/null 2>&1 || true
  done
  for pid in $API_PIDS; do
    wait "$pid" >/dev/null 2>&1 || true
  done
  for name in $PG_NAMES; do
    PG0_NAME="$name" "$HINDSIGHT_PYTHON" -c \
      'import os; from pg0 import Pg0; Pg0(name=os.environ["PG0_NAME"]).drop(force=True)' \
      >/dev/null 2>&1 || true
    registration="$HOME/.pg0/instances/$name"
    case "$registration" in
      "$HOME"/.pg0/instances/hindsight-smoke-*)
        [[ -d "$registration" ]] && /bin/rm -rf -- "$registration"
        ;;
    esac
  done
  case "$SMOKE_ROOT" in
    "${SMOKE_PARENT%/}"/hindsight-memory-smoke.*)
      /bin/rm -rf -- "$SMOKE_ROOT"
      ;;
    *)
      print -u2 -- "refusing to remove unexpected disposable-smoke path"
      ;;
  esac
}
trap cleanup EXIT INT TERM

TRAPZERR() {
  print -u2 -- "disposable smoke failed during phase: $CURRENT_PHASE"
  cleanup
}

free_port() {
  "$HINDSIGHT_PYTHON" -c \
    'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

require_disposable_profile() {
  [[ -f "$SMOKE_PROFILE_MARKER" && ! -L "$SMOKE_PROFILE_MARKER" ]] || return 1
  [[ $(stat -f '%Lp' "$SMOKE_PROFILE_MARKER") == 600 ]] || return 1
  [[ $(stat -f '%u' "$SMOKE_PROFILE_MARKER") == $EUID ]] || return 1
  [[ $(<"$SMOKE_PROFILE_MARKER") == "$SMOKE_RUN_ID" ]] || return 1
  case "$SMOKE_ROOT" in
    "${SMOKE_PARENT%/}"/hindsight-memory-smoke.*) ;;
    *) return 1 ;;
  esac
  return 0
}

install_disposable_target_guard() {
  local database_url=$1
  local role=$2
  require_disposable_profile || {
    print -u2 -- "refusing to install a guard for an invalid disposable profile"
    return 1
  }
  HINDSIGHT_SMOKE_DB_URL="$database_url" \
    HINDSIGHT_SMOKE_RUN_ID="$SMOKE_RUN_ID" \
    HINDSIGHT_SMOKE_TARGET_ROLE="$role" "$HINDSIGHT_PYTHON" -c '
import asyncio
import ipaddress
import os
import re

import asyncpg

async def main():
    run_id = os.environ["HINDSIGHT_SMOKE_RUN_ID"]
    role = os.environ["HINDSIGHT_SMOKE_TARGET_ROLE"]
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        raise SystemExit("invalid disposable run marker")
    if role not in {"source", "import", "restore"}:
        raise SystemExit("invalid disposable target role")
    connection = await asyncpg.connect(
        os.environ["HINDSIGHT_SMOKE_DB_URL"], timeout=5
    )
    try:
        address = await connection.fetchval("SELECT inet_server_addr()::text")
        database = await connection.fetchval("SELECT current_database()")
        database_user = await connection.fetchval("SELECT current_user")
        system_identifier = await connection.fetchval(
            "SELECT system_identifier::text FROM pg_control_system()"
        )
        expected_identity = f"hindsight_{role}_{run_id}"
        if (
            address is None
            or database != expected_identity
            or database_user != expected_identity
            or not system_identifier
            or not ipaddress.ip_interface(address).ip.is_loopback
        ):
            raise SystemExit("target is not a disposable database")
        if await connection.fetchval(
            "SELECT to_regclass($1)", "hindsight_smoke_guard.target_identity"
        ) is not None:
            raise SystemExit("disposable target guard already exists")
        await connection.execute("CREATE SCHEMA hindsight_smoke_guard")
        await connection.execute(
            "CREATE TABLE hindsight_smoke_guard.target_identity "
            "(run_id text PRIMARY KEY, target_role text NOT NULL, "
            "system_identifier text NOT NULL, database_name text NOT NULL, "
            "database_user text NOT NULL)"
        )
        await connection.execute(
            "INSERT INTO hindsight_smoke_guard.target_identity "
            "VALUES ($1, $2, $3, $4, $5)",
            run_id,
            role,
            system_identifier,
            database,
            database_user,
        )
    finally:
        await connection.close()

asyncio.run(main())
' || return 1
  return 0
}

require_disposable_target() {
  local database_url=$1
  local role=$2
  require_disposable_profile || {
    print -u2 -- "refusing mutation for an invalid disposable profile"
    return 1
  }
  HINDSIGHT_SMOKE_DB_URL="$database_url" \
    HINDSIGHT_SMOKE_RUN_ID="$SMOKE_RUN_ID" \
    HINDSIGHT_SMOKE_TARGET_ROLE="$role" "$HINDSIGHT_PYTHON" -c '
import asyncio
import ipaddress
import os

import asyncpg

async def main():
    connection = await asyncpg.connect(
        os.environ["HINDSIGHT_SMOKE_DB_URL"], timeout=5
    )
    try:
        row = await connection.fetchrow(
            "SELECT run_id, target_role, system_identifier, database_name, "
            "database_user "
            "FROM hindsight_smoke_guard.target_identity"
        )
        address = await connection.fetchval("SELECT inet_server_addr()::text")
        database = await connection.fetchval("SELECT current_database()")
        database_user = await connection.fetchval("SELECT current_user")
        system_identifier = await connection.fetchval(
            "SELECT system_identifier::text FROM pg_control_system()"
        )
        expected_identity = "hindsight_{}_{}".format(
            os.environ["HINDSIGHT_SMOKE_TARGET_ROLE"],
            os.environ["HINDSIGHT_SMOKE_RUN_ID"],
        )
        if (
            row is None
            or address is None
            or row["run_id"] != os.environ["HINDSIGHT_SMOKE_RUN_ID"]
            or row["target_role"] != os.environ["HINDSIGHT_SMOKE_TARGET_ROLE"]
            or row["system_identifier"] != system_identifier
            or row["database_name"] != database
            or row["database_user"] != database_user
            or database != expected_identity
            or database_user != expected_identity
            or not ipaddress.ip_interface(address).ip.is_loopback
        ):
            raise SystemExit("target is not the selected disposable database")
    finally:
        await connection.close()

asyncio.run(main())
' || return 1
  return 0
}

start_postgres() {
  local name=$1
  local port=$2
  local data_dir=$3
  local role=$4
  local password=$5
  PG_NAMES+=("$name")
  PG0_NAME="$name" PG0_PORT="$port" PG0_DATA_DIR="$data_dir" \
    PG0_ROLE="$role" PG0_RUN_ID="$SMOKE_RUN_ID" PG0_PASSWORD="$password" \
    "$HINDSIGHT_PYTHON" -c '
import os
from pg0 import Pg0

identity = "hindsight_{}_{}".format(
    os.environ["PG0_ROLE"], os.environ["PG0_RUN_ID"]
)
pg = Pg0(
    name=os.environ["PG0_NAME"],
    port=int(os.environ["PG0_PORT"]),
    username=identity,
    password=os.environ["PG0_PASSWORD"],
    database=identity,
    data_dir=os.environ["PG0_DATA_DIR"],
    config={"listen_addresses": "127.0.0.1"},
)
print(pg.start().uri)
'
}

typeset STARTED_PG_PORT=
typeset STARTED_PG_NAME=
start_postgres_on_free_port() {
  local role=$1
  local data_dir=$2
  local password=$3
  local output_file=$4
  local attempt port name
  for attempt in {1..10}; do
    port=$(free_port)
    name="hindsight-smoke-${role}-${port}"
    if start_postgres "$name" "$port" "$data_dir" "$role" "$password" \
      >"$output_file" 2>"${output_file}.log"; then
      STARTED_PG_PORT=$port
      STARTED_PG_NAME=$name
      return 0
    fi
  done
  print -u2 -- "disposable PostgreSQL could not bind a selected loopback port"
  return 1
}

typeset STARTED_API_PID=
start_api() {
  local database_url=$1
  local role=$2
  local port=$3
  local log_file=$4
  require_disposable_target "$database_url" "$role" || {
    print -u2 -- "refusing to start an API for a non-disposable target"
    return 1
  }
  env \
    HOME="$SMOKE_HOME" \
    HF_HOME="$HOST_HF_HOME" \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HINDSIGHT_API_DATABASE_URL="$database_url" \
    HINDSIGHT_API_HOST=127.0.0.1 \
    HINDSIGHT_API_PORT="$port" \
    HINDSIGHT_API_TENANT_EXTENSION=hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension \
    HINDSIGHT_API_TENANT_API_KEY="$API_KEY" \
    HINDSIGHT_API_LLM_PROVIDER=mock \
    HINDSIGHT_API_LLM_MODEL=disposable-smoke \
    HINDSIGHT_API_RETAIN_EXTRACTION_MODE=verbatim \
    HINDSIGHT_API_EMBEDDINGS_PROVIDER=local \
    HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU=true \
    HINDSIGHT_API_RERANKER_PROVIDER=rrf \
    HINDSIGHT_API_ENABLE_OBSERVATIONS=false \
    HINDSIGHT_API_ENABLE_BANK_CONFIG_API=true \
    HINDSIGHT_API_WORKER_ENABLED=false \
    HINDSIGHT_API_ACCESS_LOG=false \
    "$HINDSIGHT_API" --host 127.0.0.1 --port "$port" --no-access-log \
    >"$log_file" 2>&1 &
  STARTED_API_PID=$!
  API_PIDS+=("$STARTED_API_PID")
}

wait_for_api() {
  local port=$1
  local pid=$2
  local attempt
  for attempt in {1..240}; do
    if "$CURL" --silent --show-error --fail --max-time 2 \
      "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      return 0
    fi
    kill -0 "$pid" >/dev/null 2>&1 || {
      print -u2 -- "disposable Hindsight API exited before becoming healthy"
      return 1
    }
    sleep 0.5
  done
  print -u2 -- "disposable Hindsight API did not become healthy"
  return 1
}

typeset STARTED_API_PORT=
start_api_on_free_port() {
  local database_url=$1
  local role=$2
  local log_file=$3
  local attempt port pid
  for attempt in {1..10}; do
    port=$(free_port)
    start_api "$database_url" "$role" "$port" "$log_file"
    pid=$STARTED_API_PID
    if wait_for_api "$port" "$pid"; then
      STARTED_API_PORT=$port
      return 0
    fi
    kill -TERM "$pid" >/dev/null 2>&1 || true
    wait "$pid" >/dev/null 2>&1 || true
  done
  print -u2 -- "disposable Hindsight API could not bind a selected loopback port"
  return 1
}

hindsight_cli() {
  local api_url=$1
  shift
  HINDSIGHT_API_URL="$api_url" HINDSIGHT_API_KEY="$API_KEY" \
    "$HINDSIGHT_CLI" "$@"
}

hindsight_cli_mutate() {
  local database_url=$1
  local role=$2
  local api_url=$3
  shift 3
  require_disposable_target "$database_url" "$role" || {
    print -u2 -- "refusing non-disposable Hindsight API mutation target"
    return 1
  }
  [[ "$role" == source && "$api_url" == "$SOURCE_API_URL" ]] || {
    print -u2 -- "refusing non-disposable Hindsight API mutation target"
    return 1
  }
  hindsight_cli "$api_url" "$@"
}

hindsight_admin() {
  local database_url=$1
  local role=$2
  shift 2
  require_disposable_target "$database_url" "$role" || {
    print -u2 -- "refusing non-disposable hindsight-admin mutation target"
    return 1
  }
  env \
    HOME="$SMOKE_HOME" \
    HF_HOME="$HOST_HF_HOME" \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HINDSIGHT_API_DATABASE_URL="$database_url" \
    HINDSIGHT_API_TENANT_EXTENSION=hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension \
    HINDSIGHT_API_TENANT_API_KEY="$API_KEY" \
    HINDSIGHT_API_LLM_PROVIDER=mock \
    HINDSIGHT_API_LLM_MODEL=disposable-smoke \
    HINDSIGHT_API_RETAIN_EXTRACTION_MODE=verbatim \
    HINDSIGHT_API_EMBEDDINGS_PROVIDER=local \
    HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU=true \
    HINDSIGHT_API_RERANKER_PROVIDER=rrf \
    HINDSIGHT_API_ENABLE_OBSERVATIONS=false \
    HINDSIGHT_API_WORKER_ENABLED=false \
    "$HINDSIGHT_ADMIN" "$@"
}

authenticated_get() {
  local api_url=$1
  local path=$2
  local output=$3
  "$CURL" --silent --show-error --fail --max-time 30 \
    --config "$CURL_AUTH_CONFIG" \
    "$api_url$path" >"$output"
}

invalidated_fingerprint() {
  local database_url=$1
  local bank_id=$2
  SMOKE_DB_URL="$database_url" SMOKE_BANK_ID="$bank_id" \
    "$HINDSIGHT_PYTHON" -c '
import asyncio
import hashlib
import json
import os

import asyncpg

async def main():
    connection = await asyncpg.connect(os.environ["SMOKE_DB_URL"])
    try:
        rows = await connection.fetch(
            "SELECT to_jsonb(t) - $2 AS payload "
            "FROM public.invalidated_memory_units AS t "
            "WHERE bank_id = $1 ORDER BY id::text",
            os.environ["SMOKE_BANK_ID"],
            "bank_id",
        )
        payloads = []
        for row in rows:
            payload = row["payload"]
            payloads.append(json.loads(payload) if isinstance(payload, str) else payload)
        canonical = json.dumps(payloads, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        print(f"{len(payloads)}:{hashlib.sha256(canonical.encode()).hexdigest()}")
    finally:
        await connection.close()

asyncio.run(main())
'
}

bank_transfer_counts() {
  local database_url=$1
  local bank_id=$2
  SMOKE_DB_URL="$database_url" SMOKE_BANK_ID="$bank_id" \
    "$HINDSIGHT_PYTHON" -c '
import asyncio
import os

import asyncpg

async def main():
    connection = await asyncpg.connect(os.environ["SMOKE_DB_URL"])
    try:
        bank_id = os.environ["SMOKE_BANK_ID"]
        counts = []
        for table in ("documents", "memory_units", "directives"):
            counts.append(await connection.fetchval(f"SELECT count(*) FROM public.{table} WHERE bank_id = $1", bank_id))
        print(":".join(str(count) for count in counts))
    finally:
        await connection.close()

asyncio.run(main())
'
}

seal_export() {
  local plain=$1
  local sealed=$2
  local digest
  digest=$($OPENSSL dgst -sha256 -r "$plain" | awk '{print $1}')
  $OPENSSL enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
    -pass "file:$EXPORT_PASSPHRASE_FILE" -in "$plain" -out "$sealed"
  [[ $(od -An -tx1 -N2 "$sealed" | tr -d ' ') != 504b ]]
  rm -f -- "$plain"
  print -r -- "$digest"
}

unseal_export() {
  local sealed=$1
  local plain=$2
  local expected_digest=$3
  local actual_digest
  $OPENSSL enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
    -pass "file:$EXPORT_PASSPHRASE_FILE" -in "$sealed" -out "$plain"
  actual_digest=$($OPENSSL dgst -sha256 -r "$plain" | awk '{print $1}')
  [[ "$actual_digest" == "$expected_digest" ]]
}

start_postgres_on_free_port source "$SOURCE_DATA" "$SOURCE_DB_PASSWORD" \
  "$SMOKE_ROOT/source-db-url"
typeset -r SOURCE_PG_PORT=$STARTED_PG_PORT
typeset -r SOURCE_PG_NAME=$STARTED_PG_NAME
typeset -r SOURCE_DB_URL=$(<"$SMOKE_ROOT/source-db-url")
[[ -n "$SOURCE_DB_URL" ]]
install_disposable_target_guard "$SOURCE_DB_URL" source || {
  print -u2 -- "failed to install the source disposable-target guard"
  exit 1
}
start_api_on_free_port "$SOURCE_DB_URL" source "$SMOKE_ROOT/source-api.log"
typeset -r SOURCE_API_PORT=$STARTED_API_PORT
typeset -r SOURCE_API_PID=$STARTED_API_PID
typeset -r SOURCE_API_URL="http://127.0.0.1:$SOURCE_API_PORT"

CURRENT_PHASE=authentication
typeset -r UNAUTHORIZED_STATUS=$(
  "$CURL" --silent --output /dev/null --write-out '%{http_code}' --max-time 10 \
    "$SOURCE_API_URL/v1/default/banks/$SOURCE_BANK/config"
)
[[ "$UNAUTHORIZED_STATUS" == 401 ]]

CURRENT_PHASE=create-bank
hindsight_cli_mutate "$SOURCE_DB_URL" source "$SOURCE_API_URL" \
  bank create "$SOURCE_BANK" --name "Disposable smoke" -o json \
  >"$SMOKE_ROOT/bank-create.json"
CURRENT_PHASE=create-directive
hindsight_cli_mutate "$SOURCE_DB_URL" source "$SOURCE_API_URL" \
  directive create "$SOURCE_BANK" smoke-directive \
  "Use only disposable smoke data." -o json >"$SMOKE_ROOT/directive-create.json"
CURRENT_PHASE=retain
hindsight_cli_mutate "$SOURCE_DB_URL" source "$SOURCE_API_URL" \
  memory retain "$SOURCE_BANK" \
  "Disposable contract smoke memory." --doc-id smoke-document -o json \
  >"$SMOKE_ROOT/retain.json"
hindsight_cli_mutate "$SOURCE_DB_URL" source "$SOURCE_API_URL" \
  memory retain "$SOURCE_BANK" \
  "Disposable live transfer memory." --doc-id smoke-live-document -o json \
  >"$SMOKE_ROOT/retain-live.json"

hindsight_cli "$SOURCE_API_URL" memory list "$SOURCE_BANK" -o json \
  >"$SMOKE_ROOT/memory-list.json"
typeset -r MEMORY_ID=$(
  "$JQ" -er '
    (.items // .memories // .)
    | map(select(.document_id == "smoke-document"))[0].id
  ' "$SMOKE_ROOT/memory-list.json"
)

CURRENT_PHASE=curation
require_disposable_target "$SOURCE_DB_URL" source || {
  print -u2 -- "refusing non-disposable curation target"
  exit 1
}
"$CURL" --silent --show-error --fail --max-time 30 \
  -X PATCH \
  --config "$CURL_AUTH_CONFIG" \
  -H 'Content-Type: application/json' \
  --data '{"state":"invalidated","reason":"disposable contract smoke"}' \
  "$SOURCE_API_URL/v1/default/banks/$SOURCE_BANK/memories/$MEMORY_ID" \
  >"$SMOKE_ROOT/curation.json"

CURRENT_PHASE=authenticated-reads
hindsight_cli "$SOURCE_API_URL" bank template-schema -o json >"$SMOKE_ROOT/schema.json"
hindsight_cli "$SOURCE_API_URL" bank config "$SOURCE_BANK" -o json >"$SMOKE_ROOT/config.json"
authenticated_get "$SOURCE_API_URL" "/v1/default/banks/$SOURCE_BANK/export" "$SMOKE_ROOT/template.json"
hindsight_cli "$SOURCE_API_URL" mental-model list "$SOURCE_BANK" -o json >"$SMOKE_ROOT/models.json"
hindsight_cli "$SOURCE_API_URL" directive list "$SOURCE_BANK" -o json >"$SMOKE_ROOT/directives.json"
hindsight_cli "$SOURCE_API_URL" document list "$SOURCE_BANK" -o json >"$SMOKE_ROOT/documents.json"
hindsight_cli "$SOURCE_API_URL" operation list "$SOURCE_BANK" -o json >"$SMOKE_ROOT/operations.json"
authenticated_get "$SOURCE_API_URL" \
  "/v1/default/banks/$SOURCE_BANK/memories/list?state=invalidated" \
  "$SMOKE_ROOT/invalidated.json"

typeset -r SOURCE_FINGERPRINT=$(invalidated_fingerprint "$SOURCE_DB_URL" "$SOURCE_BANK")
[[ "${SOURCE_FINGERPRINT%%:*}" -gt 0 ]]
typeset -r SOURCE_TRANSFER_COUNTS=$(bank_transfer_counts "$SOURCE_DB_URL" "$SOURCE_BANK")

CURRENT_PHASE=bank-export
hindsight_admin "$SOURCE_DB_URL" source export-bank --bank "$SOURCE_BANK" \
  --output "$SMOKE_ROOT/bank.zip" >"$SMOKE_ROOT/export-bank.log" 2>&1
typeset -r BANK_PLAIN_DIGEST=$(seal_export "$SMOKE_ROOT/bank.zip" "$SMOKE_ROOT/bank.zip.enc")
unseal_export "$SMOKE_ROOT/bank.zip.enc" "$SMOKE_ROOT/bank.restore.zip" "$BANK_PLAIN_DIGEST"
start_postgres_on_free_port import "$IMPORT_DATA" "$IMPORT_DB_PASSWORD" \
  "$SMOKE_ROOT/import-db-url"
typeset -r IMPORT_PG_PORT=$STARTED_PG_PORT
typeset -r IMPORT_PG_NAME=$STARTED_PG_NAME
typeset -r IMPORT_DB_URL=$(<"$SMOKE_ROOT/import-db-url")
[[ -n "$IMPORT_DB_URL" ]]
install_disposable_target_guard "$IMPORT_DB_URL" import || {
  print -u2 -- "failed to install the import disposable-target guard"
  exit 1
}
typeset -r WRONG_TARGET_DB_URL=$(
  WRONG_SOURCE_DB_URL="$SOURCE_DB_URL" WRONG_IMPORT_PG_PORT="$IMPORT_PG_PORT" \
    "$HINDSIGHT_PYTHON" -c '
import os
from urllib.parse import urlsplit, urlunsplit

value = urlsplit(os.environ["WRONG_SOURCE_DB_URL"])
host = value.hostname or "127.0.0.1"
credentials = ""
if value.username:
    credentials = value.username
    if value.password:
        credentials += f":{value.password}"
    credentials += "@"
print(urlunsplit((
    value.scheme,
    f"{credentials}{host}:" + os.environ["WRONG_IMPORT_PG_PORT"],
    value.path,
    value.query,
    value.fragment,
)))
'
)
if require_disposable_target "$WRONG_TARGET_DB_URL" source >/dev/null 2>&1; then
  print -u2 -- "wrong-target disposable credentials were accepted"
  exit 1
fi
CURRENT_PHASE=bank-import-migration
hindsight_admin "$IMPORT_DB_URL" import run-db-migration --schema public \
  >"$SMOKE_ROOT/import-migration.log" 2>&1
CURRENT_PHASE=bank-import
hindsight_admin "$IMPORT_DB_URL" import import-bank --archive "$SMOKE_ROOT/bank.restore.zip" \
  --target-bank "$IMPORT_BANK" >"$SMOKE_ROOT/import-bank.log" 2>&1
rm -f -- "$SMOKE_ROOT/bank.restore.zip"

typeset -r IMPORT_FINGERPRINT=$(invalidated_fingerprint "$IMPORT_DB_URL" "$IMPORT_BANK")
typeset -r IMPORT_TRANSFER_COUNTS=$(bank_transfer_counts "$IMPORT_DB_URL" "$IMPORT_BANK")
[[ "${IMPORT_FINGERPRINT%%:*}" == 0 ]]
[[ "$IMPORT_TRANSFER_COUNTS" == "$SOURCE_TRANSFER_COUNTS" ]]

CURRENT_PHASE=schema-backup
hindsight_admin "$SOURCE_DB_URL" source backup "$SMOKE_ROOT/schema.zip" --schema public \
  >"$SMOKE_ROOT/backup-schema.log" 2>&1
typeset -r SCHEMA_PLAIN_DIGEST=$(seal_export "$SMOKE_ROOT/schema.zip" "$SMOKE_ROOT/schema.zip.enc")
unseal_export "$SMOKE_ROOT/schema.zip.enc" "$SMOKE_ROOT/schema.restore.zip" "$SCHEMA_PLAIN_DIGEST"

start_postgres_on_free_port restore "$RESTORE_DATA" "$RESTORE_DB_PASSWORD" \
  "$SMOKE_ROOT/restore-db-url"
typeset -r RESTORE_PG_PORT=$STARTED_PG_PORT
typeset -r RESTORE_PG_NAME=$STARTED_PG_NAME
typeset -r RESTORE_DB_URL=$(<"$SMOKE_ROOT/restore-db-url")
[[ -n "$RESTORE_DB_URL" ]]
install_disposable_target_guard "$RESTORE_DB_URL" restore || {
  print -u2 -- "failed to install the restore disposable-target guard"
  exit 1
}
CURRENT_PHASE=schema-restore-migration
hindsight_admin "$RESTORE_DB_URL" restore run-db-migration --schema public \
  >"$SMOKE_ROOT/restore-migration.log" 2>&1
CURRENT_PHASE=schema-restore
hindsight_admin "$RESTORE_DB_URL" restore restore "$SMOKE_ROOT/schema.restore.zip" \
  --schema public --yes >"$SMOKE_ROOT/restore-schema.log" 2>&1
rm -f -- "$SMOKE_ROOT/schema.restore.zip"

typeset -r RESTORE_FINGERPRINT=$(invalidated_fingerprint "$RESTORE_DB_URL" "$SOURCE_BANK")
[[ "$RESTORE_FINGERPRINT" == "$SOURCE_FINGERPRINT" ]]

CURRENT_PHASE=target-identity-negative-check
SMOKE_DB_URL="$RESTORE_DB_URL" "$HINDSIGHT_PYTHON" -c '
import asyncio
import os

import asyncpg

async def main():
    connection = await asyncpg.connect(os.environ["SMOKE_DB_URL"], timeout=5)
    try:
        await connection.execute(
            "UPDATE hindsight_smoke_guard.target_identity "
            "SET system_identifier = $1",
            "tampered",
        )
    finally:
        await connection.close()

asyncio.run(main())
'
if require_disposable_target "$RESTORE_DB_URL" restore >/dev/null 2>&1; then
  print -u2 -- "tampered disposable server identity was accepted"
  exit 1
fi

CURRENT_PHASE=content-free-report
typeset -r POSTGRES_VERSION=$(
  SMOKE_DB_URL="$SOURCE_DB_URL" "$HINDSIGHT_PYTHON" -c '
import asyncio
import os
import asyncpg

async def main():
    connection = await asyncpg.connect(os.environ["SMOKE_DB_URL"])
    try:
        print(await connection.fetchval("SHOW server_version"))
    finally:
        await connection.close()

asyncio.run(main())
'
)
typeset -r BANK_CIPHERTEXT_DIGEST=$($OPENSSL dgst -sha256 -r "$SMOKE_ROOT/bank.zip.enc" | awk '{print $1}')
typeset -r SCHEMA_CIPHERTEXT_DIGEST=$($OPENSSL dgst -sha256 -r "$SMOKE_ROOT/schema.zip.enc" | awk '{print $1}')

CURRENT_PHASE=cleanup
cleanup
trap - EXIT INT TERM
[[ ! -e "$SMOKE_ROOT" ]]
typeset -r REMAINING_SMOKE_INSTANCES=$(
  SMOKE_PG_NAMES="${(j:,:)PG_NAMES}" "$HINDSIGHT_PYTHON" -c '
import os
import pg0

expected = set(filter(None, os.environ["SMOKE_PG_NAMES"].split(",")))
print(sum(instance.name in expected for instance in pg0.list_instances()))
'
)
[[ "$REMAINING_SMOKE_INSTANCES" == 0 ]]

$JQ -n \
  --arg hindsight_api_version "$API_VERSION" \
  --arg hindsight_cli_version "$CLI_VERSION" \
  --arg postgres_version "$POSTGRES_VERSION" \
  --arg invalidated_fingerprint "$SOURCE_FINGERPRINT" \
  --arg bank_transfer_counts "$SOURCE_TRANSFER_COUNTS" \
  --arg bank_export_ciphertext_sha256 "$BANK_CIPHERTEXT_DIGEST" \
  --arg schema_backup_ciphertext_sha256 "$SCHEMA_CIPHERTEXT_DIGEST" \
  '{
    passed: true,
    authentication: {unauthorized_status: 401, authenticated_reads: 8},
    versions: {
      hindsight_api: $hindsight_api_version,
      hindsight_cli: $hindsight_cli_version,
      postgresql: $postgres_version
    },
    restores: {
      bank_export_import: "verified_supported_payload",
      bank_transfer_counts: $bank_transfer_counts,
      bank_import_invalidated_policy: "excluded_by_hindsight_0.8.4_contract",
      full_schema_backup_restore: "verified",
      invalidated_fingerprint: $invalidated_fingerprint
    },
    encrypted_exports: {
      bank_export_ciphertext_sha256: $bank_export_ciphertext_sha256,
      schema_backup_ciphertext_sha256: $schema_backup_ciphertext_sha256
    },
    cleanup: "verified"
  }'
