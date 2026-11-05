#!/usr/bin/env bash
# Проверка, что бэкап реально восстанавливается. Поднимает ВРЕМЕННЫЙ Postgres в Docker, заливает туда бэкап
# и печатает, сколько в нём клиентов и записей. Рабочую базу не трогает, временный контейнер удаляется сам.
#   ./scripts/restore-test.sh                       # самый свежий backups/*.sql.gz
#   ./scripts/restore-test.sh backups/ФАЙЛ.sql.gz   # конкретный файл (например, скачанный из хранилища)
set -euo pipefail
cd "$(dirname "$0")/.."
f="${1:-$(ls -1t backups/*.sql.gz 2>/dev/null | head -n 1 || true)}"
if [ -z "$f" ] || [ ! -f "$f" ]; then
  echo "Нет файла бэкапа. Сначала: ./scripts/backup.sh"
  exit 1
fi
gzip -t "$f" || { echo "Архив повреждён: $f"; exit 1; }

name="restore-test-$(basename "$PWD")-$$"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker run -d --rm --name "$name" -e POSTGRES_USER=app -e POSTGRES_PASSWORD=restore-test -e POSTGRES_DB=app \
  postgres:16-alpine >/dev/null

printf "Жду временный Postgres"
ready=""
for _ in $(seq 1 60); do
  # по TCP: во время первичной инициализации образ слушает только сокет, так мы не попадём во «временный» сервер
  if docker exec "$name" psql -h 127.0.0.1 -U app -d app -tAc "select 1" >/dev/null 2>&1; then ready=1; break; fi
  printf "."; sleep 1
done
echo
[ -n "$ready" ] || { echo "Временный Postgres не поднялся"; exit 1; }

echo "Восстанавливаю $f …"
gunzip -c "$f" | docker exec -i "$name" psql -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U app -d app >/dev/null
q() { docker exec "$name" psql -h 127.0.0.1 -U app -d app -tAc "$1"; }
echo "Версия схемы:  $(q 'select version_num from alembic_version')"
echo "Салонов:       $(q 'select count(*) from tenants')"
echo "Клиентов:      $(q 'select count(*) from clients')"
echo "Записей:       $(q 'select count(*) from bookings')"
echo "Последняя запись создана: $(q 'select max(created_at) from bookings')"
echo "OK: бэкап восстанавливается."
