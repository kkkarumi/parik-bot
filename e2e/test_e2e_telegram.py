"""Бот ходит в Telegram по адресу из TELEGRAM_API_BASE (релей), не падает и не висит, если Telegram недоступен."""
import asyncio

import pytest_asyncio

import config as bot_config
import main as bot_main
from e2e.conftest import CLIENT

RELAY = "https://x.example/SECRET"


def test_api_base_parsing():
    assert bot_config.api_base(None) == "https://api.telegram.org"
    assert bot_config.api_base("  ") == "https://api.telegram.org"
    assert bot_config.api_base("https://x.example/SECRET/") == RELAY


@pytest_asyncio.fixture
async def relay(monkeypatch):
    monkeypatch.setattr(bot_config, "TELEGRAM_API_BASE", RELAY)


async def test_all_requests_go_to_relay(relay, h):
    token = bot_config.BOT_TOKEN
    assert h.app.bot.base_url == f"{RELAY}/bot{token}"
    assert h.app.bot.base_file_url == f"{RELAY}/file/bot{token}"
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    await c.press("menu_book")
    assert h.tg.urls and all(u.startswith(f"{RELAY}/bot{token}/") for u in h.tg.urls), h.tg.urls


def test_default_build_sets_timeouts(monkeypatch):
    monkeypatch.setattr(bot_config, "STATE_FILE", "")
    monkeypatch.setattr(bot_config, "TELEGRAM_API_BASE", "https://api.telegram.org")
    app = bot_main.build()
    req = app.bot.request
    assert req.read_timeout == bot_main.READ_TIMEOUT
    assert app.bot.base_url.startswith("https://api.telegram.org/bot")


async def test_post_init_does_not_hang(monkeypatch):
    async def hang(app):
        await asyncio.sleep(30)
    monkeypatch.setattr(bot_main, "_setup_menus", hang)
    monkeypatch.setattr(bot_main, "POST_INIT_TIMEOUT", 0.1)

    class App:
        class bot:
            username = "x"
    await asyncio.wait_for(bot_main.post_init(App), 2)  # не висит и не падает
