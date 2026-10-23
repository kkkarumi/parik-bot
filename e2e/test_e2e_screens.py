"""Каждый экран админки/мастера открывается без ошибок."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import Booking, Master, Service
from e2e.conftest import ADMIN, CLIENT, MASTER1, tomorrow
from e2e.test_e2e_client import _book

BROKEN = ("Что-то пошло не так", "временно недоступен")


def ok(chat):
    texts = chat.texts()
    assert texts, "бот ничего не ответил"
    assert not any(b in t for t in texts for b in BROKEN), texts


async def test_every_admin_screen(h):
    c = h.chat(CLIENT, "Иван")
    await _book(c)
    async with SessionLocal() as s:
        mid = (await s.scalar(select(Master).where(Master.name == "Тимур"))).id
        sid = (await s.scalar(select(Service).where(Service.name == "Борода"))).id
        bid = (await s.scalar(select(Booking))).id
    a = h.chat(ADMIN, "Админ")
    screens = ["a:menu", "a:msts", f"a:mst:{mid}", f"a:ms:{mid}", f"a:mst_s:{mid}:{sid}", f"a:mst_s:{mid}:{sid}",
               f"a:mh:{mid}", f"a:mo:{mid}", f"a:moa:{mid}:0", f"a:moa:{mid}:1", f"a:moad:{mid}:{tomorrow()}",
               f"a:mod:{mid}:{tomorrow()}", f"a:mtog:{mid}", f"a:mtog:{mid}", f"a:minv:{mid}", f"a:munl:{mid}",
               "a:svcs", f"a:svc:{sid}", "a:salon", "a:prepay", "a:stats:7", "a:stats:90",
               "sch:today", f"sch:{tomorrow()}", f"bk:{bid}", f"bkc:{bid}", f"cl:{c.id}:{bid}",
               "a:svc:999999", "bk:999999", "cl:999999:"]
    for data in screens:
        await a.press(data)
        ok(a)
    # имя мастера и добавление мастера через диалог
    await a.press(f"a:mname:{mid}")
    await a.send("Тимур Б.")
    assert "Тимур Б." in a.last_text()
    await a.press("a:mst_add")
    await a.send("Мурат")
    assert any("Мурат добавлен" in t for t in a.texts())
    # выключение предоплаты
    await a.press("a:pp:details")
    await a.send("Карта 2202")
    await a.press("a:pp:amount")
    await a.send("200")
    assert "включена, 200₽" in a.last_text()
    await a.press("a:pp_off")
    assert "выключена" in a.last_text()


async def test_master_no_show_and_foreign_booking(h):
    c = h.chat(CLIENT, "Иван")
    await _book(c)
    async with SessionLocal() as s:
        b = await s.scalar(select(Booking))
        now = datetime.now(timezone.utc)
        await s.execute(update(Booking).values(starts_at=now - timedelta(minutes=20), ends_at=now + timedelta(minutes=40)))
        await s.commit()
    m = h.chat(MASTER1, "Алим")
    await m.press(f"bk:{b.id}")
    await m.press(m.button("не пришёл"))
    assert "не пришёл" in m.last_text()
    # чужой мастер не видит запись
    t = h.chat(2002, "Тимур")
    async with SessionLocal() as s:
        timur = await s.scalar(select(Master).where(Master.name == "Тимур"))
        timur.telegram_chat_id = 2002
        await s.commit()
    await t.press(f"bk:{b.id}")
    assert "не найдена" in t.last_text()
    await t.send("/admin")
    assert "только администратору" in t.last_text()
