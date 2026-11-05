"""manage reset-demo (только при DEMO_MODE=1) и отключённая рассылка в демо-режиме."""
import pytest
from sqlalchemy import func, select

from app import manage
from app.config import settings
from app.db import SessionLocal
from app.models import Booking, Client, Master, Service, Tenant
from tests.conftest import ADMIN, KEY, M1, M2, book


async def _count(model):
    async with SessionLocal() as s:
        return await s.scalar(select(func.count(model.id)))


async def test_reset_demo_refuses_without_demo_mode(api, salon, sent, monkeypatch, capsys):
    monkeypatch.setenv("TENANT_API_KEY", KEY)
    monkeypatch.setattr(settings, "demo_mode", False)
    await book(api, salon)
    with pytest.raises(SystemExit):
        await manage.reset_demo()
    assert "Отказ" in capsys.readouterr().out
    assert await _count(Booking) == 1 and await _count(Client) == 2 and await _count(Service) == 3


async def test_reset_demo(api, salon, sent, monkeypatch, capsys):
    monkeypatch.setenv("TENANT_API_KEY", KEY)
    monkeypatch.setattr(settings, "demo_mode", True)
    await book(api, salon)
    await manage.reset_demo()
    assert "Демо сброшено" in capsys.readouterr().out
    assert await _count(Booking) == 0 and await _count(Client) == 0
    async with SessionLocal() as s:
        assert sorted((await s.scalars(select(Service.name))).all()) == sorted(
            ["Мужская стрижка", "Стрижка бороды", "Стрижка + борода", "Детская стрижка"])
        links = {m.name: m.telegram_chat_id for m in (await s.scalars(select(Master))).all()}
        assert links == {"Алим": M1, "Тимур": M2}  # подключённые мастера остались подключены
        t = await s.scalar(select(Tenant))
        assert t.admin_chat_id == ADMIN and t.name == "Парик"
    # после сброса демо-бот снова принимает записи
    async with SessionLocal() as s:
        sid = await s.scalar(select(Service.id).where(Service.name == "Мужская стрижка"))
        mid = await s.scalar(select(Master.id).where(Master.name == "Алим"))
    c = (await api.put("/clients", json={"telegram_id": 777, "name": "Гость"})).json()
    await api.post("/clients/consent", params={"telegram_id": 777})
    r = await book(api, {"c1": c["id"], "m1": mid, "cut": sid})
    assert r.status_code == 201


async def test_broadcast_disabled_in_demo(api, salon, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    r = await api.get("/admin/clients/ids", params={"telegram_id": ADMIN})
    assert r.status_code == 403 and "demo" in r.json()["detail"]
    monkeypatch.setattr(settings, "demo_mode", False)
    assert (await api.get("/admin/clients/ids", params={"telegram_id": ADMIN})).status_code == 200
