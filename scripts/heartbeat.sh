#!/usr/bin/env bash
# Пинг внешнего мониторинга (push-монитор Uptime Kuma, healthchecks.io и т. п.), если салон жив:
#   • API отвечает на /health (проверяем изнутри контейнера — порт 8000 наружу НЕ открываем);
#   • контейнер бота healthy (значит, getUpdates доходит до Telegram/релея).
# Если что-то не так — не пингуем: мониторинг сам поднимет тревогу, когда пинги перестанут приходить.
# Адрес — HEARTBEAT_URL в .env. Запуск раз в минуту ставит ./scripts/install-cron.sh. Подробно: scripts/deploy-checklist.md
set -uo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh
URL="${HEARTBEAT_URL:-$(env_get HEARTBEAT_URL)}"
[ -n "$URL" ] || { echo "HEARTBEAT_URL не задан в .env" >&2; exit 1; }
fail() { echo "$(date '+%F %T') не пингую: $*" >&2; exit 2; }

docker compose exec -T backend python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" >/dev/null 2>&1 \
  || fail "API не отвечает на /health"
bot="$(docker compose ps -q bot 2>/dev/null)"
[ -n "$bot" ] || fail "контейнер бота не запущен"
state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$bot" 2>/dev/null)"
[ "$state" = "healthy" ] || fail "бот: ${state:-неизвестно} (нет связи с Telegram/релеем или бот завис)"
curl -fsS -m 10 --retry 2 "$URL" >/dev/null || fail "не достучался до мониторинга"
