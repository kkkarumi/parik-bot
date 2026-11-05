"""Политика отмены и минимальный срок записи — как это видит клиент в боте."""
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app import api as api_module
from app.config import settings
from app.db import SessionLocal
from app.models import Booking
from e2e.conftest import CLIENT, TZ, tomorrow
from e2e.test_e2e_client import _book
from ui import duration


def test_duration_text():
    assert [duration(m) for m in (120, 90, 45, 60)] == ["2 ч", "1 ч 30 мин", "45 мин", "1 ч"]


async def test_cancel_policy_texts(h, monkeypatch):
    monkeypatch.setattr(settings, "cancel_before_min", 120)
    c = h.chat(CLIENT, "Иван")
    await c.send("/start")
    await c.open_booking()
    await c.press(c.button("Стрижка"))
    await c.press(c.button("Алим"))
    await c.press(f"day:{tomorrow()}")
    await c.press(c.button("12:00"))
    await c.send_contact("+79281112233")
    assert "не позже чем за 2 ч до визита" in c.last_text()
    await c.press("confirm_yes")
    assert "Вы записаны" in c.last_text() and "не позже чем за 2 ч" in c.last_text()

    async with SessionLocal() as s:
        bid = (await s.scalar(select(Booking))).id
    start = datetime.combine(datetime.fromisoformat(tomorrow()).date(), time(12), tzinfo=TZ)
    monkeypatch.setattr(api_module, "utcnow", lambda: (start - timedelta(minutes=30)).astimezone(timezone.utc))
    await c.press(f"cancel_yes:{bid}")
    assert "Отмена так близко к визиту невозможна, позвоните: +79280000000" in c.last_text()
    async with SessionLocal() as s:
        assert (await s.get(Booking, bid)).status == "confirmed"


async def test_no_policy_no_extra_text(h, monkeypatch):
    monkeypatch.setattr(settings, "cancel_before_min", 0)
    c = h.chat(CLIENT, "Иван")
    await _book(c)
    assert "Вы записаны" in c.last_text() and "не позже" not in c.last_text()
