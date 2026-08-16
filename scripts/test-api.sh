#!/usr/bin/env bash
# Runs the API contract tests against the real application on a
# throwaway database, then deletes it. Your working data is never
# touched — a separate database is created for the run and dropped
# afterwards, including when the tests fail.
#
# There is no mock server: the tests drive the actual app, seeded with
# the demo example the app itself knows how to create. See
# tests/conftest.py for why.
#
# Usage: ./scripts/test-api.sh [extra pytest args]
#   ./scripts/test-api.sh -k dry_run     # one group
#   ./scripts/test-api.sh -v             # verbose
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

TEST_DB="server_tracker_contract_test"
# Random per run: the tests must never depend on a token that happens to
# be configured in .env, and this one only ever exists in this process.
TEST_TOKEN="$(openssl rand -hex 16)"

set -a
# shellcheck disable=SC1091
[ -f .env ] && source .env
set +a
POSTGRES_USER="${POSTGRES_USER:-tracker}"

echo "[test] starting the database if it isn't up..."
docker compose up -d db >/dev/null
for _ in $(seq 1 30); do
  docker compose exec -T db pg_isready -U "$POSTGRES_USER" >/dev/null 2>&1 && break
  sleep 1
done

drop_test_db() {
  docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS $TEST_DB WITH (FORCE);" >/dev/null 2>&1 || true
}
trap drop_test_db EXIT

echo "[test] creating scratch database $TEST_DB..."
drop_test_db
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $TEST_DB;" >/dev/null

echo "[test] running migrations and contract tests..."
# Dev dependencies are installed into a throwaway container rather than
# baked into the image — the deployed image has no business carrying a
# test runner (see requirements-dev.txt).
docker compose run --rm \
  -e DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${TEST_DB}" \
  -e API_TOKEN="$TEST_TOKEN" \
  -e API_SERVICE_USERNAME="api" \
  -v "$PROJECT_DIR/tests:/app/tests" \
  -v "$PROJECT_DIR/requirements-dev.txt:/app/requirements-dev.txt" \
  -v "$PROJECT_DIR/AGENTS.md:/app/AGENTS.md:ro" \
  app sh -c "pip install -q -r requirements-dev.txt && alembic upgrade head >/dev/null 2>&1 && pytest tests $*"
