#!/usr/bin/env bash
# Idempotent init+deploy for a local-network production instance. Safe
# to re-run: never overwrites an existing .env, never touches existing
# data directories, `alembic upgrade head` is a no-op if already
# current. First run creates everything from scratch; later runs just
# rebuild/restart on top of whatever's already there (e.g. after a
# `git pull`).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [ ! -f .env ]; then
  echo "[deploy] .env not found, generating one from .env.example with random secrets..."
  cp .env.example .env
  sed -i.bak "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
  sed -i.bak "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
  rm -f .env.bak
  echo "[deploy] .env created — review it (POSTGRES_DB/USER, DATA_DIR/BACKUP_DIR paths) before going further if the defaults don't suit you."
else
  echo "[deploy] .env already exists, leaving it as-is."
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

DATA_DIR="${DATA_DIR:-./data}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"

echo "[deploy] ensuring data directories exist: $DATA_DIR/postgres, $DATA_DIR/uploads, $BACKUP_DIR..."
mkdir -p "$DATA_DIR/postgres" "$DATA_DIR/uploads" "$BACKUP_DIR/db" "$BACKUP_DIR/uploads"

if [ ! -f Caddyfile ] || grep -q "tracker.internal.example" Caddyfile; then
  echo "[deploy] NOTE: Caddyfile still has the placeholder domain (tracker.internal.example)."
  echo "[deploy]       Edit it to your real internal hostname/IP before relying on HTTPS from Caddy."
fi

echo "[deploy] building and starting containers..."
docker compose up -d --build

echo "[deploy] waiting for the database to be healthy..."
for _ in $(seq 1 30); do
  status="$(docker compose ps --format '{{.Health}}' db 2>/dev/null || true)"
  [ "$status" = "healthy" ] && break
  sleep 2
done

echo "[deploy] applying migrations..."
docker compose exec -T app alembic upgrade head

# Guard against the failure mode this project is most exposed to: models
# changed, but no new Alembic revision was written for the change. Then
# `upgrade head` above is a silent no-op, and the app starts against a
# schema that's missing the column it expects — a 500 on first use
# instead of an error here. `alembic check` compares the live schema to
# the models and reports the difference.
#
# Deliberately not fatal: containers are already up at this point, and
# aborting wouldn't undo that. A loud warning that the operator has to
# read is the useful behaviour.
echo "[deploy] checking that the DB schema matches the models..."
if ! docker compose exec -T app alembic check >/tmp/alembic-check.$$ 2>&1; then
  echo
  echo "[deploy] !!! WARNING: the database schema does NOT match the models."
  echo "[deploy] !!! Most likely a model was changed without a new Alembic revision."
  echo "[deploy] !!! The app is running, but anything touching the changed table may fail."
  echo "[deploy] !!! Details:"
  grep -Ev "^INFO  \[alembic\.(ddl|runtime)" /tmp/alembic-check.$$ | sed 's/^/[deploy]     /'
  echo
fi
rm -f /tmp/alembic-check.$$

echo
echo "[deploy] done."
echo "[deploy] first run only: open the app and go to /setup to create the first admin"
echo "[deploy]   (this also seeds one demo platform/item so the UI isn't empty on first look)."
echo "[deploy] set up periodic backups: cron entry example in README.md -> scripts/backup.sh"
