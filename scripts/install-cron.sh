#!/usr/bin/env bash
# Ставит задачи cron для ЭТОЙ папки салона. Можно запускать сколько угодно раз — дублей не будет
# (свои строки узнаёт по метке «# parik-bot:<папка>», чужие строки crontab не трогает).
#   • всегда: ежедневный бэкап в 04:15 → backups/backup.log
#   • если в .env задан HEARTBEAT_URL: пинг мониторинга раз в минуту (scripts/heartbeat.sh)
#   • если в .env DEMO_MODE=1: сброс демо-салона каждую ночь в 04:45 (manage reset-demo)
# Убрать задачи этой папки: ./scripts/install-cron.sh --remove
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh
command -v crontab >/dev/null 2>&1 || { echo "crontab не найден. Ubuntu: apt install -y cron"; exit 1; }
DIR="$PWD"
TAG="# parik-bot:$DIR"
mkdir -p backups  # туда пишутся логи cron-задач

others="$(crontab -l 2>/dev/null | grep -vF "$TAG" || true)"
mine=""
if [ "${1:-}" != "--remove" ]; then
  mine="15 4 * * * cd '$DIR' && ./scripts/backup.sh >> backups/backup.log 2>&1 $TAG"
  if [ -n "$(env_get HEARTBEAT_URL)" ]; then
    mine="$mine
* * * * * cd '$DIR' && ./scripts/heartbeat.sh >> backups/heartbeat.log 2>&1 $TAG"
  fi
  if [ "$(env_get DEMO_MODE)" = "1" ]; then
    mine="$mine
45 4 * * * cd '$DIR' && docker compose exec -T backend python -m app.manage reset-demo >> backups/reset-demo.log 2>&1 $TAG"
  fi
fi
{ [ -n "$others" ] && printf '%s\n' "$others"; [ -n "$mine" ] && printf '%s\n' "$mine"; true; } | crontab -

if [ -n "$mine" ]; then
  echo "Задачи cron для $DIR:"
  printf '%s\n' "$mine" | sed "s|  *$TAG||; s|^|  |"
else
  echo "Задачи cron для $DIR удалены."
fi
