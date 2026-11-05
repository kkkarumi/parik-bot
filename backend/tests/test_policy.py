"""MIN_LEAD_MIN (запись закрывается за N минут) и CANCEL_BEFORE_MIN (клиент отменяет сам не позже чем за N минут).
Часы подменяем, чтобы проверить границы с точностью до минуты."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app import api as api_module, reminders, slots
from app.config import settings
from app.db import SessionLocal
from app.models import Booking
from tests.conftest import ADMIN, M1, book, to, tomorrow_at

T = tomorrow_at(12)  # начало проверяемого слота


def clock(monkeypatch, at: datetime):
    fixed = at.astimezone(timezone.utc)
    monkeypatch.setattr(slots, "utcnow", lambda: fixed)
    monkeypatch.setattr(api_module, "utcnow", lambda: fixed)


async def _slots(api, salon):
    r = await api.get("/slots", params={"master_id": salon["m1"], "service_id": salon["cut"], "date": T.date().isoformat()})
    return [datetime.fromisoformat(x) for x in r.json()]


# ---------- MIN_LEAD_MIN ----------
@pytest.mark.parametrize("before,open_", [(61, True), (60, False), (59, False)])
async def test_min_lead_boundary(api, salon, sent, monkeypatch, before, open_):
    monkeypatch.setattr(settings, "min_lead_min", 60)
    clock(monkeypatch, T - timedelta(minutes=before))
    assert (T in await _slots(api, salon)) is open_
    r = await book(api, salon, at=T)
    assert r.status_code == (201 if open_ else 409)  # API проверяет сам, не только бот


async def test_min_lead_default_is_old_behaviour(api, salon, sent, monkeypatch):
    monkeypatch.setattr(settings, "min_lead_min", 0)
    clock(monkeypatch, T - timedelta(minutes=1))
    assert T in await _slots(api, salon)
    clock(monkeypatch, T)
    assert T not in await _slots(api, salon)  # начавшийся слот закрыт, как и раньше


# ---------- CANCEL_BEFORE_MIN ----------
async def _booked(api, salon, monkeypatch):
    clock(monkeypatch, T - timedelta(days=1))
    r = await book(api, salon, at=T)
    assert r.status_code == 201
    return r.json()["id"]


@pytest.mark.parametrize("before,code", [(121, 200), (120, 200), (119, 403)])
async def test_client_cancel_boundary(api, salon, sent, monkeypatch, before, code):
    monkeypatch.setattr(settings, "cancel_before_min", 120)
    bid = await _booked(api, salon, monkeypatch)
    clock(monkeypatch, T - timedelta(minutes=before))
    r = await api.post(f"/bookings/{bid}/cancel", params={"telegram_id": 501})
    assert r.status_code == code
    if code == 403:
        assert r.json()["detail"] == "too late to cancel"


async def test_staff_and_admin_cancel_not_limited(api, salon, sent, monkeypatch):
    monkeypatch.setattr(settings, "cancel_before_min", 120)
    b1 = await _booked(api, salon, monkeypatch)
    clock(monkeypatch, T - timedelta(days=1))
    b2 = (await book(api, salon, at=T, master="m2")).json()["id"]
    clock(monkeypatch, T - timedelta(minutes=10))
    assert (await api.post(f"/staff/bookings/{b1}/cancel", params={"telegram_id": M1})).status_code == 200
    assert (await api.post(f"/staff/bookings/{b2}/cancel", params={"telegram_id": ADMIN})).status_code == 200


async def test_cancel_default_is_old_behaviour(api, salon, sent, monkeypatch):
    monkeypatch.setattr(settings, "cancel_before_min", 0)
    bid = await _booked(api, salon, monkeypatch)
    clock(monkeypatch, T - timedelta(minutes=1))
    assert (await api.post(f"/bookings/{bid}/cancel", params={"telegram_id": 501})).status_code == 200


async def test_unpaid_hold_can_always_be_released(api, salon, sent, monkeypatch):
    monkeypatch.setattr(settings, "cancel_before_min", 120)
    bid = await _booked(api, salon, monkeypatch)
    async with SessionLocal() as s:
        await s.execute(update(Booking).where(Booking.id == bid).values(status="pending_payment"))
        await s.commit()
    clock(monkeypatch, T - timedelta(minutes=10))
    assert (await api.post(f"/bookings/{bid}/cancel", params={"telegram_id": 501})).status_code == 200


async def test_salon_exposes_cancel_policy(api, salon, monkeypatch):
    monkeypatch.setattr(settings, "cancel_before_min", 120)
    assert (await api.get("/salon")).json()["cancel_before_min"] == 120


async def test_late_reminder_has_no_cancel_button(salon, sent, monkeypatch):
    monkeypatch.setattr(settings, "cancel_before_min", 120)
    now = datetime.now(timezone.utc)
    async with SessionLocal() as s:
        s.add(Booking(tenant_id=salon["t"], master_id=salon["m1"], service_id=salon["cut"], client_id=salon["c1"],
                      starts_at=now + timedelta(minutes=90), ends_at=now + timedelta(minutes=150), price=800,
                      status="confirmed", created_at=now - timedelta(days=2)))
        await s.commit()
    await reminders.tick()
    msg = to(sent, 501)[0]
    labels = [b["text"] for b in msg["reply_markup"]["inline_keyboard"][0]]
    assert labels == ["✅ Приду"] and "+79990000000" in msg["text"]
