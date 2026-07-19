#!/usr/bin/env bash
# Dumps the DB and archives the uploaded-files directory, then rotates
# each to the last BACKUP_RETENTION copies. Meant to run on a schedule
# (see cron example in README.md), but safe to run by hand too.
#
# Usage: ./scripts/backup.sh   (run from the project root, or set
# PROJECT_DIR below to wherever docker-compose.yml lives)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

set -a
# shellcheck disable=SC1091
[ -f .env ] && source .env
set +a

POSTGRES_USER="${POSTGRES_USER:-tracker}"
POSTGRES_DB="${POSTGRES_DB:-server_tracker}"
DATA_DIR="${DATA_DIR:-./data}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_RETENTION="${BACKUP_RETENTION:-10}"

mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/uploads"

timestamp="$(date +%Y-%m-%d_%H-%M-%S)"

echo "[backup] dumping database..."
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "$BACKUP_DIR/db/${timestamp}.sql.gz"

echo "[backup] archiving uploads..."
if [ -d "$DATA_DIR/uploads" ]; then
  tar czf "$BACKUP_DIR/uploads/${timestamp}.tar.gz" -C "$DATA_DIR" uploads
else
  echo "[backup] $DATA_DIR/uploads does not exist yet, skipping (nothing uploaded so far)"
fi

rotate() {
  local dir="$1"
  local keep="$2"
  local count
  count=$(find "$dir" -maxdepth 1 -type f | wc -l)
  if [ "$count" -gt "$keep" ]; then
    find "$dir" -maxdepth 1 -type f -printf '%T@ %p\n' \
      | sort -n \
      | head -n "$((count - keep))" \
      | cut -d' ' -f2- \
      | xargs -r rm -v
  fi
}

echo "[backup] rotating (keeping last $BACKUP_RETENTION of each)..."
rotate "$BACKUP_DIR/db" "$BACKUP_RETENTION"
rotate "$BACKUP_DIR/uploads" "$BACKUP_RETENTION"

echo "[backup] done: $BACKUP_DIR/db/${timestamp}.sql.gz"
