"""152-ФЗ: согласие перед записью, отзыв согласия (/forget), миграция 0003 без потери данных."""
from datetime import timedelta

from alembic import command
from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.migrate import _config
from app.models import Base, Booking, Client, Payment
from tests.conftest import ADMIN, KEY, M1, book, to, tomorrow_at


async def _new_client(api, tg=777, name="Мурат"):
    r = await api.put("/clients", json={"telegram_id": tg, "name": name, "username": "murat", "phone": "+79280001122"})
    assert r.status_code == 200 and r.json()["consent_at"] is None
    return r.json()


async def test_booking_requires_consent(api, salon, sent):
    c = await _new_client(api)
    r = await api.post("/bookings", json={"client_id": c["id"], "master_id": salon["m1"], "service_id": salon["cut"],
                                          "starts_at": tomorrow_at(12).isoformat()})
    assert r.status_code == 428
    assert sent == []  # салон не получил «новую запись»

    r = await api.post("/clients/consent", params={"telegram_id": 777})
    first = r.json()["consent_at"]
    assert r.status_code == 200 and first
    r = await api.post("/clients/consent", params={"telegram_id": 777})
    assert r.json()["consent_at"] == first  # повторное нажатие не меняет дату
    r = await api.post("/bookings", json={"client_id": c["id"], "master_id": salon["m1"], "service_id": salon["cut"],
                                          "starts_at": tomorrow_at(12).isoformat()})
    assert r.status_code == 201


async def test_client_me(api, salon):
    r = await api.get("/clients/me", params={"telegram_id": 501})
    assert r.status_code == 200 and r.json()["consent_at"]
    assert (await api.get("/clients/me", params={"telegram_id": 424242})).status_code == 404
    assert (await api.post("/clients/consent", params={"telegram_id": 424242})).status_code == 404


async def test_forget_anonymizes_and_cancels_future(api, salon, sent):
    future = (await book(api, salon)).json()
    async with SessionLocal() as s:  # прошедший визит с чеком и заметкой мастера
        now = tomorrow_at(12) - timedelta(days=3)
        past = Booking(tenant_id=salon["t"], master_id=salon["m1"], service_id=salon["cut"], client_id=salon["c1"],
                       starts_at=now, ends_at=now + timedelta(hours=1), price=800, status="completed")
        s.add(past)
        await s.flush()
        s.add(Payment(booking_id=past.id, amount=300, status="approved", receipt_file_id="RECEIPT"))
        (await s.get(Client, salon["c1"])).notes = "любит покороче"
        await s.commit()
        past_id = past.id
    sent.clear()

    r = await api.post("/clients/forget", params={"telegram_id": 501})
    assert r.json() == {"ok": True, "cancelled": 1}

    async with SessionLocal() as s:
        c = await s.get(Client, salon["c1"])
        assert (c.name, c.username, c.phone, c.notes, c.consent_at) == ("Удалён", None, None, None, None)
        assert c.telegram_id < 0 and c.erased_at is not None
        assert (await s.get(Booking, future["id"])).status == "cancelled"
        assert (await s.get(Booking, past_id)).status == "completed"  # история для статистики осталась
        assert await s.scalar(select(Payment.receipt_file_id).where(Payment.booking_id == past_id)) is None
    # салон предупреждён, в уведомлении нет ни имени, ни телефона
    for chat in (M1, ADMIN):
        msg = to(sent, chat)[0]["text"]
        assert "удалил свои данные" in msg and "Иван" not in msg and "111-22-33" not in msg
    assert to(sent, 501) == []
    # клиента больше не найти по старым данным, рассылка его не видит
    assert (await api.get("/clients/me", params={"telegram_id": 501})).status_code == 404
    ids = (await api.get("/admin/clients/ids", params={"telegram_id": ADMIN})).json()
    assert 501 not in ids and all(i > 0 for i in ids)
    # статистика по-прежнему считает прошедший визит
    st = (await api.get("/admin/stats", params={"telegram_id": ADMIN, "days": 30})).json()
    assert st["completed"] == 1
    # вернулся и снова записывается — это новый клиент, согласие спросят заново
    again = (await api.put("/clients", json={"telegram_id": 501, "name": "Иван"})).json()
    assert again["id"] != salon["c1"] and again["consent_at"] is None


async def test_forget_unknown_client_is_noop(api, salon):
    r = await api.post("/clients/forget", params={"telegram_id": 31337})
    assert r.json() == {"ok": True, "cancelled": 0}


async def test_migration_0003_keeps_data():
    """Старая база (0002) с клиентами → upgrade head: данные на месте, согласия нет (спросим при записи)."""
    def to_0002(conn):
        command.upgrade(_config(conn), "0002")

    def to_head(conn):
        command.upgrade(_config(conn), "head")

    def down_up(conn):
        command.downgrade(_config(conn), "0002")
        command.upgrade(_config(conn), "head")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await conn.run_sync(to_0002)
        await conn.execute(text("INSERT INTO tenants (id, name, api_key, timezone, prepay_amount) "
                                f"VALUES (1, 'Парик', '{KEY}', 'Europe/Moscow', 0)"))
        await conn.execute(text("INSERT INTO clients (id, tenant_id, telegram_id, name, phone, is_blocked) "
                                "VALUES (1, 1, 501, 'Иван', '+79281112233', false)"))
        await conn.run_sync(to_head)
        row = (await conn.execute(text("SELECT name, phone, consent_at, erased_at FROM clients"))).one()
        assert tuple(row) == ("Иван", "+79281112233", None, None)
        await conn.run_sync(down_up)  # откат и повторный накат тоже не теряют данные
        assert (await conn.execute(text("SELECT name FROM clients"))).scalar() == "Иван"
