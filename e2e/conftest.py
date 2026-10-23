"""Сквозные тесты: настоящий бот (python-telegram-bot) + настоящий бэкенд (FastAPI + БД),
вместо Telegram — фейковый транспорт, который записывает все вызовы Bot API."""
import itertools
import json
import os
import sys
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "bot")]
_tmp = Path(tempfile.mkdtemp()) / "e2e.db"
os.environ.update(DATABASE_URL=os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_tmp}"),
                  BOT_TOKEN="123:TEST", TENANT_API_KEY="e2e-key", TZ="Europe/Moscow")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402
from telegram import Update  # noqa: E402
from telegram.request import BaseRequest  # noqa: E402

from app import notify  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.migrate import upgrade_db  # noqa: E402
from app.models import Base, Master, MasterService, Service, Tenant, WorkingHours  # noqa: E402

TZ = ZoneInfo("Europe/Moscow")
ADMIN, MASTER1, CLIENT = 1000, 1001, 501
BOT_USER = {"id": 123, "is_bot": True, "first_name": "Парик", "username": "parik_test_bot"}


class FakeTelegram(BaseRequest):
    """Отвечает как Bot API и записывает все вызовы."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._ids = itertools.count(10_000)

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    @property
    def read_timeout(self):
        return 1

    async def do_request(self, url, method, request_data=None, **_):
        name = url.rsplit("/", 1)[-1]
        params = dict(request_data.parameters) if request_data else {}
        for k, v in list(params.items()):
            if isinstance(v, str) and v[:1] in "[{":
                try:
                    params[k] = json.loads(v)
                except ValueError:
                    pass
        self.calls.append((name, params))
        if name == "getMe":
            result = BOT_USER
        elif name in ("sendMessage", "sendPhoto", "sendDocument", "editMessageText", "editMessageCaption",
                      "editMessageReplyMarkup"):
            chat_id = params.get("chat_id") or 0
            result = {"message_id": params.get("message_id") or next(self._ids), "date": 0,
                      "chat": {"id": chat_id, "type": "private"}, "text": params.get("text", ""),
                      "from": BOT_USER}
            if name == "editMessageCaption":
                result["caption"] = params.get("caption", "")
        else:
            result = True
        return 200, json.dumps({"ok": True, "result": result}).encode()


class Chat:
    """Пользователь Telegram: шлёт сообщения и жмёт кнопки, смотрит, что ответил бот."""

    def __init__(self, harness, user_id: int, name: str, username: str | None = None):
        self.h, self.id, self.name, self.username = harness, user_id, name, username

    def _user(self):
        u = {"id": self.id, "is_bot": False, "first_name": self.name}
        if self.username:
            u["username"] = self.username
        return u

    async def _process(self, payload: dict):
        self.h.tg.calls.clear()
        upd = Update.de_json({"update_id": next(self.h.update_ids), **payload}, self.h.app.bot)
        await self.h.app.process_update(upd)
        return self.h.tg.calls

    async def send(self, text: str):
        msg = {"message_id": next(self.h.msg_ids), "date": 0, "chat": {"id": self.id, "type": "private"},
               "from": self._user(), "text": text}
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        return await self._process({"message": msg})

    async def send_contact(self, phone: str):
        msg = {"message_id": next(self.h.msg_ids), "date": 0, "chat": {"id": self.id, "type": "private"},
               "from": self._user(), "contact": {"phone_number": phone, "first_name": self.name, "user_id": self.id}}
        return await self._process({"message": msg})

    async def send_photo(self, file_id: str = "PHOTO_FILE"):
        msg = {"message_id": next(self.h.msg_ids), "date": 0, "chat": {"id": self.id, "type": "private"},
               "from": self._user(),
               "photo": [{"file_id": file_id, "file_unique_id": "u" + file_id, "width": 800, "height": 600}]}
        return await self._process({"message": msg})

    async def press(self, data: str, *, caption: str | None = None):
        msg = {"message_id": 1, "date": 0, "chat": {"id": self.id, "type": "private"}, "from": BOT_USER}
        if caption is not None:
            msg["caption"] = caption
            msg["photo"] = [{"file_id": "X", "file_unique_id": "X", "width": 1, "height": 1}]
        else:
            msg["text"] = "…"
        cq = {"id": str(next(self.h.msg_ids)), "from": self._user(), "chat_instance": "ci", "data": data,
              "message": msg}
        return await self._process({"callback_query": cq})

    # --- что ответил бот ---
    def texts(self) -> list[str]:
        return [p.get("text") or p.get("caption") or "" for n, p in self.h.tg.calls
                if n in ("sendMessage", "editMessageText", "sendPhoto", "editMessageCaption")]

    def last_text(self) -> str:
        t = self.texts()
        return t[-1] if t else ""

    def buttons(self) -> list[tuple[str, str]]:
        """(текст, callback_data|url) последней клавиатуры."""
        for _n, p in reversed(self.h.tg.calls):
            rm = p.get("reply_markup")
            if isinstance(rm, dict) and "inline_keyboard" in rm:
                return [(b["text"], b.get("callback_data") or b.get("url")) for row in rm["inline_keyboard"] for b in row]
        return []

    def button(self, contains: str) -> str:
        for t, d in self.buttons():
            if contains in t:
                return d
        raise AssertionError(f"нет кнопки «{contains}» среди {self.buttons()}")


class Harness:
    def __init__(self, app, tg):
        self.app, self.tg = app, tg
        self.update_ids, self.msg_ids = itertools.count(1), itertools.count(100)
        self.backend_sent: list[dict] = []

    def chat(self, user_id: int, name: str, username: str | None = None) -> Chat:
        return Chat(self, user_id, name, username)

    def notified(self, chat_id: int) -> list[str]:
        return [m.get("text") or m.get("caption") or "" for m in self.backend_sent if m.get("chat_id") == chat_id]


@pytest_asyncio.fixture
async def h(monkeypatch):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await upgrade_db()
    async with SessionLocal() as s:
        t = Tenant(name="Парик", api_key="e2e-key", timezone="Europe/Moscow", admin_chat_id=ADMIN,
                   address="Нальчик, Кабардинская 1", phone="+79280000000")
        s.add(t)
        await s.flush()
        cut = Service(tenant_id=t.id, name="Стрижка", price=800, duration_min=60, is_active=True)
        beard = Service(tenant_id=t.id, name="Борода", price=500, duration_min=30, is_active=True)
        m1 = Master(tenant_id=t.id, name="Алим", telegram_chat_id=MASTER1, is_active=True)
        m2 = Master(tenant_id=t.id, name="Тимур", is_active=True)
        s.add_all([cut, beard, m1, m2])
        await s.flush()
        for m in (m1, m2):
            for sv in (cut, beard):
                s.add(MasterService(master_id=m.id, service_id=sv.id))
            for wd in range(7):
                s.add(WorkingHours(master_id=m.id, weekday=wd, start_time=time(10), end_time=time(20)))
        await s.commit()

    harness_sent = []

    async def fake_call(method, payload):
        harness_sent.append({"method": method, **payload})
        return True
    monkeypatch.setattr(notify, "_call", fake_call)

    import api_client
    import main as bot_main
    monkeypatch.setattr(api_client.api, "c", httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app), base_url="http://backend", headers={"X-Api-Key": "e2e-key"}))
    tg = FakeTelegram()
    import config as bot_config
    monkeypatch.setattr(bot_config, "STATE_FILE", "")
    from telegram.ext import Application
    orig = Application.builder

    def builder():
        return orig().request(tg).get_updates_request(FakeTelegram())
    monkeypatch.setattr(Application, "builder", staticmethod(builder))
    app = bot_main.build()
    await app.initialize()
    hs = Harness(app, tg)
    hs.backend_sent = harness_sent
    yield hs
    await app.shutdown()
    await engine.dispose()


def tomorrow() -> str:
    return (datetime.now(TZ).date() + timedelta(days=1)).isoformat()
