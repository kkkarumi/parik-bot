from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app import reminders
from app.db import SessionLocal
from app.models import Booking, Payment
from tests.conftest import ADMIN, M1, to

UTC = timezone.utc


async def _insert(salon, starts_in: timedelta, created_ago: timedelta, status="confirmed", minutes=60):
    now = datetime.now(UTC)
    async with SessionLocal() as s:
        b = Booking(tenant_id=salon["t"], master_id=salon["m1"], service_id=salon["cut"], client_id=salon["c1"],
                    starts_at=now + starts_in, ends_at=now + starts_in + timedelta(minutes=minutes), price=800,
                    status=status)
        s.add(b)
        await s.flush()
        await s.execute(update(Booking).where(Booking.id == b.id).values(created_at=now - created_ago))
        await s.commit()
        return b.id


async def _status(bid):
    async with SessionLocal() as s:
        return (await s.get(Booking, bid)).status


async def test_24h_reminder_once(salon, sent):
    await _insert(salon, timedelta(hours=23), timedelta(days=2))
    await reminders.tick()
    msgs = to(sent, 501)
    assert len(msgs) == 1 and "через 24 ч" in msgs[0]["text"]
    assert msgs[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("rem_ok:")
    await reminders.tick()
    assert len(to(sent, 501)) == 1


async def test_2h_reminder(salon, sent):
    await _insert(salon, timedelta(minutes=90), timedelta(days=2))
    await reminders.tick()
    msgs = to(sent, 501)
    assert len(msgs) == 1 and "через 2 ч" in msgs[0]["text"]


async def test_no_reminder_for_fresh_booking(salon, sent):
    await _insert(salon, timedelta(minutes=90), timedelta(minutes=5))  # записался за 1.5 часа
    await reminders.tick()
    assert to(sent, 501) == []


async def test_complete_and_review(api, salon, sent):
    bid = await _insert(salon, timedelta(hours=-2), timedelta(days=1))
    await reminders.tick()
    assert await _status(bid) == "completed"
    assert "Оцените" in to(sent, 501)[0]["text"]
    sent.clear()
    r = await api.post(f"/bookings/{bid}/review", params={"telegram_id": 501}, json={"rating": 2})
    assert r.status_code == 201
    assert "Отзыв 2/5" in to(sent, ADMIN)[0]["text"] and to(sent, M1)
    r = await api.post(f"/bookings/{bid}/review", params={"telegram_id": 501}, json={"rating": 5})
    assert r.status_code == 409


async def test_old_visits_completed_silently(salon, sent):
    bid = await _insert(salon, timedelta(days=-3), timedelta(days=5))
    await reminders.tick()
    assert await _status(bid) == "completed" and to(sent, 501) == []


async def test_review_requires_completed(api, salon):
    bid = await _insert(salon, timedelta(days=1), timedelta(days=1))
    r = await api.post(f"/bookings/{bid}/review", params={"telegram_id": 501}, json={"rating": 5})
    assert r.status_code == 409


async def test_unpaid_booking_expires(salon, sent):
    bid = await _insert(salon, timedelta(days=1), timedelta(minutes=31), status="pending_payment")
    async with SessionLocal() as s:
        s.add(Payment(booking_id=bid, amount=300, status="awaiting"))
        await s.commit()
    await reminders.tick()
    assert await _status(bid) == "cancelled"
    assert "снята" in to(sent, 501)[0]["text"]
    async with SessionLocal() as s:
        assert (await s.scalar(select(Payment.status).where(Payment.booking_id == bid))) == "expired"


async def test_pending_receipt_not_expired(salon, sent):
    bid = await _insert(salon, timedelta(days=1), timedelta(hours=2), status="pending_payment")
    async with SessionLocal() as s:
        s.add(Payment(booking_id=bid, amount=300, status="pending", receipt_file_id="f"))
        await s.commit()
    await reminders.tick()
    assert await _status(bid) == "pending_payment"


async def test_tick_survives_telegram_errors(salon, monkeypatch):
    from app import notify

    async def boom(*a, **k):
        raise RuntimeError("telegram down")
    monkeypatch.setattr(notify, "send", boom)
    bid = await _insert(salon, timedelta(hours=-2), timedelta(days=1))
    await reminders.tick()  # не должен упасть
    assert await _status(bid) == "completed"
