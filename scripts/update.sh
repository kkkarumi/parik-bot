#!/usr/bin/env bash
# Обновить бота до свежей версии из git. Миграции базы применяются сами при старте.
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/backup.sh || { code=$?; [ "$code" -eq 3 ] || exit "$code"; echo "Продолжаю: локальный бэкап есть."; }
git pull --ff-only
docker compose up -d --build
docker compose ps
