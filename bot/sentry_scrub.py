"""Чистка событий Sentry перед отправкой: Sentry — сервис за рубежом, туда не должны уходить
телефоны клиентов, токен бота, ключ API салона и секрет релея.

Файл одинаковый в backend/app/sentry_scrub.py и bot/sentry_scrub.py — правьте оба (за этим следит тест).
Имена клиентов регуляркой не поймать, поэтому вместе с этим: send_default_pii=False,
include_local_variables=False (без значений переменных в трейсбеках) и без тел запросов.
"""
import re
from urllib.parse import urlsplit

TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")  # токен бота: 123456789:AAH…
PHONE_RE = re.compile(
    r"(?<![\w+])(?:\+7|7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\w)"  # +7 928 111-22-33, 89281112233
    r"|(?<![\w+])\+\d{10,15}(?!\w)")                                                # +995555123456
SECRET_KEYS = {"x_api_key", "authorization", "cookie", "set_cookie", "token", "bot_token", "api_key",
               "tenant_api_key", "phone", "client_phone", "name", "client_name", "username", "client_username"}
SKIP_KEYS = {"event_id", "trace_id", "span_id", "parent_span_id", "timestamp", "start_timestamp",
             "release", "sdk", "modules", "platform"}


def relay_secret(api_base: str | None) -> str:
    """https://relay.example.com/SECRET → SECRET (секретный путь релея из TELEGRAM_API_BASE)."""
    return urlsplit(api_base or "").path.strip("/")


def make_before_send(*secrets: str):
    secrets = tuple(s for s in secrets if s and len(s) >= 6)

    def clean(value, key: str = ""):
        if key in SKIP_KEYS:
            return value
        if isinstance(value, str):
            for s in secrets:
                value = value.replace(s, "[secret]")
            return PHONE_RE.sub("[phone]", TOKEN_RE.sub("[token]", value))
        if isinstance(value, dict):
            return {k: "[Filtered]" if str(k).lower().replace("-", "_") in SECRET_KEYS else clean(v, str(k))
                    for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value

    def before_send(event, hint):
        return clean(event)

    return before_send
