#!/usr/bin/env bash
# Установка бота для одного салона. Запускать на сервере из папки проекта: ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
rand() { openssl rand -hex "$1" 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex($1))"; }

if ! command -v docker >/dev/null 2>&1; then
  say "Docker не найден. Установите его одной командой и запустите setup.sh ещё раз:"
  echo "  curl -fsSL https://get.docker.com | sh"
  exit 1
fi

if [ -f .env ]; then
  say "Файл .env уже есть — использую его."
else
  say "Настройка нового салона"
  while true; do
    read -rp "Токен бота от @BotFather: " BOT_TOKEN
    [[ "$BOT_TOKEN" =~ ^[0-9]{6,}:[A-Za-z0-9_-]{30,}$ ]] && break
    echo "Это не похоже на токен (пример: 1234567890:AAH...). Ещё раз."
  done
  read -rp "Название салона: " SALON_NAME
  SALON_NAME=${SALON_NAME//\"/}
  read -rp "Часовой пояс [Europe/Moscow]: " TZ_NAME
  TZ_NAME=${TZ_NAME:-Europe/Moscow}
  cat > .env <<ENV
BOT_TOKEN=$BOT_TOKEN
SALON_NAME="${SALON_NAME:-Мой салон}"
TENANT_API_KEY=$(rand 24)
DB_PASSWORD=$(rand 16)
TZ=$TZ_NAME
ADMIN_CHAT_ID=
PREPAY_TIMEOUT_MIN=30
MAX_ACTIVE_BOOKINGS=3
BOOKING_HORIZON_DAYS=14
SLOT_STEP_MIN=30
SENTRY_DSN=
ENV
  chmod 600 .env
  echo ".env создан."
fi

say "Собираю и запускаю (первый раз — пара минут)…"
docker compose up -d --build

printf "Жду, пока поднимется API"
for _ in $(seq 1 60); do
  if docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" >/dev/null 2>&1; then
    echo " — готово"; break
  fi
  printf "."; sleep 2
done

docker compose exec -T backend python -m app.manage init

if [ -t 0 ]; then
  read -rp $'\nДобавить демо-услуги и демо-мастеров (удобно показать салону, потом поменять в /admin)? [y/N]: ' DEMO
  if [[ "${DEMO:-n}" =~ ^[YyДд] ]]; then
    docker compose exec -T backend python -m app.manage demo
  fi
fi

say "Готово!"
echo "• Откройте ссылку выше в Telegram — станете администратором, дальше всё настраивается командой /admin."
echo "• Отдать админку владельцу салона: /admin → Салон → «Передать админку» (или: docker compose exec backend python -m app.manage admin-link)."
echo "• Бэкап базы: ./scripts/backup.sh   (ежедневно — см. README)"
