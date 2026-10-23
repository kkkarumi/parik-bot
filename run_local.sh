#!/usr/bin/env bash
# Локальный запуск без Docker (база SQLite): API + бот в одном окне. Остановить — Ctrl+C.
# Первый запуск сам создаст .venv и поставит зависимости (пара минут).
set -euo pipefail
cd "$(dirname "$0")"
PORT="${API_PORT:-8000}"

if [ ! -f .env ]; then
  echo "Нет файла .env. Скопируйте .env.example в .env и впишите BOT_TOKEN, TENANT_API_KEY, SALON_NAME."
  exit 1
fi

PY=""
for c in python3.12 python3.13 python3.11 python3.14 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Нужен Python 3.10 или новее: https://www.python.org/downloads/"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Создаю окружение .venv ($("$PY" --version))…"
  "$PY" -m venv .venv
fi

# зависимости ставим заново, только если поменялись requirements
HASH=$(.venv/bin/python -c "import hashlib; print(hashlib.sha1(open('backend/requirements.txt','rb').read() + open('bot/requirements.txt','rb').read()).hexdigest())")
if [ "$(cat .venv/.req-hash 2>/dev/null || true)" != "$HASH" ]; then
  echo "Ставлю зависимости…"
  .venv/bin/python -m pip install -q --upgrade pip
  grep -hv '^asyncpg' backend/requirements.txt bot/requirements.txt > .venv/req-local.txt  # Postgres локально не нужен
  .venv/bin/python -m pip install -q -r .venv/req-local.txt
  echo "$HASH" > .venv/.req-hash
fi

if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "Порт $PORT уже занят (старый запуск ещё работает?). Закройте его или запустите: API_PORT=8001 ./run_local.sh"
  exit 1
fi

# салон в базе (если его ещё нет — создастся и выдаст ссылку для админа)
(cd backend && ../.venv/bin/python -m app.manage init)

API_PID=""
cleanup() { [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd backend && exec ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning) &
API_PID=$!
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 || { echo "API не запустился"; exit 1; }

echo
echo "✅ API работает. Запускаю бота — пишите ему в Telegram. Остановить: Ctrl+C"
echo
cd bot && API_URL="http://127.0.0.1:$PORT" ../.venv/bin/python main.py
