#!/bin/bash
# Database backup — dumps tender_db to backups/YYYY-MM-DD.sql.gz.
# Run before risky operations (migrations, Docker reinstall, large rescans).
#
# Restore with:  gunzip -c backups/2026-04-28.sql.gz | docker exec -i jarvis-tender-ai-postgres-1 psql -U jarvis -d jarvis_db

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

export PATH="/c/Program Files/Docker/Docker/resources/bin:$PATH"

mkdir -p backups
DATE=$(date +%Y-%m-%d_%H%M)
OUT="backups/${DATE}.sql.gz"

echo "==> Dumping postgres → $OUT"
docker exec jarvis-tender-ai-postgres-1 sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  | gzip > "$OUT"

SIZE=$(du -h "$OUT" | cut -f1)
echo "  saved $SIZE → $OUT"
echo
echo "To restore later:"
echo "  gunzip -c $OUT | docker exec -i jarvis-tender-ai-postgres-1 psql -U jarvis -d jarvis_db"
