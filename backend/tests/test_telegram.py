"""Адрес Telegram API (TELEGRAM_API_BASE / релей), разбор ошибок отправки, check-telegram."""
import httpx
import pytest
from loguru import logger

from app import manage, notify
from app.config import Settings, settings

RELAY = "https://x.example/SECRET"


@pytest.fixture
def relay(monkeypatch):
    monkeypatch.setattr(settings, "telegram_api_base", RELAY)
    monkeypatch.setattr(settings, "bot_token", "123456:" + "A" * 35)
    return settings.bot_token


def test_default_base_is_telegram():
    assert Settings.model_fields["telegram_api_base"].default == "https://api.telegram.org"


def test_base_trailing_slash_and_empty():
    assert Settings(telegram_api_base="https://x.example/SECRET/").telegram_api_base == RELAY
    assert Settings(telegram_api_base="  ").telegram_api_base == "https://api.telegram.org"


def test_api_url_with_prefix(relay):
    assert notify.api_url("sendMessage") == f"{RELAY}/bot{relay}/sendMessage"


def test_api_url_default(monkeypatch):
    monkeypatch.setattr(settings, "telegram_api_base", "https://api.telegram.org")
    monkeypatch.setattr(settings, "bot_token", "42:abc")
    assert notify.api_url("getMe") == "https://api.telegram.org/bot42:abc/getMe"


def _mock(monkeypatch, handler):
    seen = []

    def wrapped(request: httpx.Request):
        seen.append(str(request.url))
        return handler(request)
    monkeypatch.setattr(notify, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))
    return seen


async def test_send_goes_to_relay_and_classifies_errors(relay, monkeypatch):
    def handler(request):
        body = request.read().decode()
        if '"chat_id":1' in body:
            return httpx.Response(200, json={"ok": True, "result": {}})
        if '"chat_id":2' in body:
            return httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"})
        if '"chat_id":3' in body:
            return httpx.Response(502, text="<html>bad gateway</html>")
        raise httpx.ConnectError(f"cannot connect to {request.url}")
    seen = _mock(monkeypatch, handler)
    assert await notify.send(1, "hi") is True
    assert await notify.send(2, "hi") is None       # клиент заблокировал бота — повторять бессмысленно
    assert await notify.send(3, "hi") is False      # релей/Telegram сбоит — можно повторить
    assert await notify.send(4, "hi") is False      # нет связи
    assert await notify.send(None, "hi") is None    # некому
    assert seen and all(u == f"{RELAY}/bot{relay}/sendMessage" for u in seen)


async def test_token_not_in_logs(relay, monkeypatch):
    lines = []
    sink = logger.add(lambda m: lines.append(str(m)), level="WARNING")
    try:
        _mock(monkeypatch, lambda r: (_ for _ in ()).throw(httpx.ConnectError(f"boom {r.url}")))
        await notify.send(5, "hi")
    finally:
        logger.remove(sink)
    assert lines and all(relay not in line and "SECRET" not in line for line in lines), lines


def test_mask_hides_any_bot_token():
    assert "<token>" in notify.mask("url https://api.telegram.org/bot987654321:AAH" + "x" * 30 + "/getMe")


# ---------- check-telegram ----------
def _fake_get(monkeypatch, response=None, exc=None):
    calls = []

    def get(url, timeout):
        calls.append(url)
        if exc:
            raise exc
        return response
    monkeypatch.setattr(manage.httpx, "get", get)
    return calls


def test_check_telegram_ok(relay, monkeypatch, capsys):
    req = httpx.Request("GET", "https://x")
    calls = _fake_get(monkeypatch, httpx.Response(200, json={"ok": True, "result": {"username": "parik_bot"}},
                                                  request=req))
    assert manage.check_telegram() is True
    out = capsys.readouterr().out
    assert "OK, бот @parik_bot" in out
    assert calls == [f"{RELAY}/bot{relay}/getMe"]
    assert "SECRET" not in out and relay not in out


@pytest.mark.parametrize("response,exc,expect", [
    (None, httpx.ConnectTimeout("timed out"), "нет ответа"),
    (None, httpx.ConnectError("Connection refused"), "ConnectError"),
    (httpx.Response(404, text="<html>404</html>"), None, "не от Telegram"),
    (httpx.Response(404, json={"ok": False, "error_code": 404, "description": "Not Found"}), None, "BOT_TOKEN"),
])
def test_check_telegram_fail(relay, monkeypatch, capsys, response, exc, expect):
    _fake_get(monkeypatch, response, exc)
    assert manage.check_telegram() is False
    out = capsys.readouterr().out
    assert "Не достучался до Telegram" in out and expect in out and "relay/README.md" in out
    assert relay not in out


def test_check_telegram_without_token(monkeypatch, capsys):
    monkeypatch.setattr(settings, "bot_token", "")
    assert manage.check_telegram() is False
    assert "BOT_TOKEN" in capsys.readouterr().out
