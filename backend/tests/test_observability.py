"""Sentry без ПДн и секретов; одна строка ERROR, если Telegram недоступен."""
from pathlib import Path

import httpx
import pytest
from loguru import logger

from app import notify
from app.config import settings
from app.main import sentry_options
from app.sentry_scrub import make_before_send, relay_secret

TOKEN = "123456789:AAH" + "x" * 32


@pytest.mark.parametrize("phone", ["+79281112233", "+7 (928) 111-22-33", "8 928 111 22 33", "89281112233",
                                   "79281112233", "+995555123456"])
def test_phones_scrubbed(phone):
    ev = make_before_send()({"message": f"клиент {phone} записался", "extra": {"x": [f"tel:{phone}"]}}, {})
    assert phone not in str(ev) and "[phone]" in ev["message"]


def test_secrets_and_headers_scrubbed():
    scrub = make_before_send(TOKEN, "tenant-key-123", relay_secret("https://relay.example.com/s3cr3tpath"))
    ev = scrub({
        "event_id": "79281112233aaaa79281112233bbbbcc",
        "timestamp": "2026-11-05T10:00:00Z",
        "breadcrumbs": {"values": [{"message": f"POST https://relay.example.com/s3cr3tpath/bot{TOKEN}/sendMessage"}]},
        "request": {"headers": {"X-Api-Key": "tenant-key-123", "User-Agent": "httpx"},
                    "query_string": "telegram_id=501"},
        "exception": {"values": [{"value": "ApiError 409 at 2026-11-05 12:00, key tenant-key-123"}]},
        "extra": {"client_phone": "+79281112233", "client_name": "Иван"},
    }, {})
    s = str(ev)
    assert TOKEN not in s and "s3cr3tpath" not in s and "tenant-key-123" not in s and "Иван" not in s
    assert ev["request"]["headers"]["X-Api-Key"] == "[Filtered]"
    assert ev["event_id"] == "79281112233aaaa79281112233bbbbcc"  # служебные поля не трогаем
    assert "2026-11-05 12:00" in ev["exception"]["values"][0]["value"]  # даты не похожи на телефоны
    assert ev["request"]["query_string"] == "telegram_id=501"


def test_backend_sentry_options(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    o = sentry_options()
    assert o["send_default_pii"] is False and o["traces_sample_rate"] == 0.0
    assert o["include_local_variables"] is False and o["max_request_body_size"] == "never"
    assert TOKEN not in str(o["before_send"]({"message": TOKEN}, {}))


def test_scrubber_same_in_bot_and_backend():
    root = Path(__file__).resolve().parents[2]
    assert (root / "backend/app/sentry_scrub.py").read_text() == (root / "bot/sentry_scrub.py").read_text()


async def test_one_error_when_telegram_down(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    monkeypatch.setattr(notify, "_fail_streak", 0)
    lines = []
    sink = logger.add(lambda m: lines.append(m.record), level="INFO")
    down = True

    def handler(request):
        if down:
            raise httpx.ConnectTimeout("timed out")
        return httpx.Response(200, json={"ok": True, "result": {}})
    monkeypatch.setattr(notify, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        for _ in range(notify.ALERT_AFTER * 3):
            assert await notify.send(1, "x") is False
        errors = [r for r in lines if r["level"].name == "ERROR"]
        assert len(errors) == 1 and "Telegram недоступен" in errors[0]["message"]
        down = False
        assert await notify.send(1, "x") is True
        assert any("восстановлена" in r["message"] for r in lines) and notify._fail_streak == 0
    finally:
        logger.remove(sink)


async def test_blocked_user_is_not_an_outage(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    monkeypatch.setattr(notify, "_fail_streak", notify.ALERT_AFTER - 1)
    monkeypatch.setattr(notify, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}))))
    assert await notify.send(1, "x") is None
    assert notify._fail_streak == 0  # Telegram ответил — связь есть
