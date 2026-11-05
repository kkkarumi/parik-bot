#!/usr/bin/env bash
# Бэкап базы салона в ./backups (хранятся последние 14), а если в .env задан BACKUP_REMOTE —
# ещё и копия во внешнее хранилище через rclone (например BACKUP_REMOTE=s3remote:bucket/parik).
# Ежедневный запуск: ./scripts/install-cron.sh
# Проверить, что бэкап реально восстанавливается: ./scripts/restore-test.sh
# Восстановление в рабочую базу:
#   gunzip -c backups/<файл>.sql.gz | docker compose exec -T db psql -U app -d app
# Коды выхода: 0 — всё хорошо; 1 — бэкап не сделан; 3 — локальный бэкап есть, но наружу не выгрузился.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh
mkdir -p backups
f="backups/$(basename "$PWD")-$(date +%Y-%m-%d_%H%M).sql.gz"
# пишем во временный файл: если pg_dump упадёт, в backups/ не останется битого архива
docker compose exec -T db pg_dump -U app --clean --if-exists app | gzip > "$f.part"
mv "$f.part" "$f"
ls -1t backups/*.sql.gz | tail -n +15 | xargs -r rm --
echo "OK: $f ($(du -h "$f" | cut -f1))"

REMOTE="${BACKUP_REMOTE:-$(env_get BACKUP_REMOTE)}"
[ -n "$REMOTE" ] || exit 0
if ! command -v rclone >/dev/null 2>&1; then
  echo "ВНИМАНИЕ: в .env задан BACKUP_REMOTE=$REMOTE, но rclone не установлен — копия наружу НЕ сделана." >&2
  echo "Поставьте и настройте хранилище: curl https://rclone.org/install.sh | sudo bash && rclone config" >&2
  exit 3
fi
# у каждого салона своя подпапка (имя папки проекта), старые копии в хранилище не удаляются
if rclone copy "$f" "$REMOTE/$(basename "$PWD")/"; then
  echo "OK: копия в $REMOTE/$(basename "$PWD")/"
else
  echo "ВНИМАНИЕ: не удалось выгрузить бэкап в $REMOTE (локальная копия есть: $f)." >&2
  exit 3
fi
