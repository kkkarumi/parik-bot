import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# .env лежит в корне проекта, рядом с docker-compose.yml
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TELEGRAM_API_DEFAULT = "https://api.telegram.org"


def api_base(raw: str | None) -> str:
    return (raw or "").strip().rstrip("/") or TELEGRAM_API_DEFAULT


BOT_TOKEN = os.environ["BOT_TOKEN"]
# Адрес Bot API. С сервера в РФ — адрес релея (relay/README.md), например https://relay.example.com/SECRET
TELEGRAM_API_BASE = api_base(os.environ.get("TELEGRAM_API_BASE"))
API_URL = os.environ.get("API_URL", "http://localhost:8000")
API_KEY = os.environ["TENANT_API_KEY"]
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Moscow"))
PREPAY_TIMEOUT_MIN = int(os.environ.get("PREPAY_TIMEOUT_MIN") or 30)
# где хранить состояние диалогов (чтобы рестарт бота не сбрасывал запись на полпути); пусто = в памяти
STATE_FILE = os.environ.get("BOT_STATE_FILE", "")
