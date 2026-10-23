#!/usr/bin/env bash
# Бэкап базы салона в ./backups (хранятся последние 14). Для ежедневного запуска добавьте в crontab:
#   15 4 * * * cd /путь/к/проекту && ./scripts/backup.sh >> backups/backup.log 2>&1
# Восстановление:
#   gunzip -c backups/<файл>.sql.gz | docker compose exec -T db psql -U app -d app
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
f="backups/$(basename "$PWD")-$(date +%Y-%m-%d_%H%M).sql.gz"
docker compose exec -T db pg_dump -U app --clean --if-exists app | gzip > "$f"
ls -1t backups/*.sql.gz | tail -n +15 | xargs -r rm --
echo "OK: $f ($(du -h "$f" | cut -f1))"
