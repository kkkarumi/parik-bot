import os
from pathlib import Path

from dotenv import load_dotenv

# .env лежит в корне проекта (parik/.env), рядом с docker-compose.yml
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BOT_TOKEN = os.environ["BOT_TOKEN"]
API_URL = os.environ.get("API_URL", "http://localhost:8000")
API_KEY = os.environ["TENANT_API_KEY"]
TZ = os.environ.get("TZ", "Europe/Moscow")
