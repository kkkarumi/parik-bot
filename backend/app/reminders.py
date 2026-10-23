"""Фоновая работа раз в минуту. Состояние живёт в БД (флаги reminded_*, статусы),
поэтому рестарт бэкенда ничего не теряет и ничего не шлёт дважды."""
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

from . import bookings as bk, notify
from .config import settings
from .db import SessionLocal
from .models import Booking, Payment
from .notify import esc


async def _reminders(s, now: datetime) -> int:
    upcoming = (await s.scalars(select(Booking).where(
        Booking.status == "confirmed", Booking.starts_at > now,
        Booking.starts_at <= now + timedelta(hours=24)))).unique().all()
    sent = 0
    for b in upcoming:
        left = b.starts_at - now
        hours = None
        if left <= timedelta(hours=2):
            if not b.reminded_2h and b.created_at < b.starts_at - timedelta(hours=2):
                hours = 2
            b.reminded_24h = b.reminded_2h = True
        elif not b.reminded_24h:
            if b.created_at < b.starts_at - timedelta(hours=24):
                hours = 24
            b.reminded_24h = True
        if hours:
            kb = None if b.client_confirmed else {"inline_keyboard": [[
                {"text": "✅ Приду", "callback_data": f"rem_ok:{b.id}"},
                {"text": "❌ Отменить", "callback_data": f"rem_cancel:{b.id}"}]]}
            addr = f"\n📍 {esc(b.tenant.address)}" if b.tenant.address else ""
            await notify.send(b.client.telegram_id,
                              f"⏰ <b>Напоминание: запись через {hours} ч.</b>\n\n💇 {esc(b.master.name)}\n"
                              f"✂️ {esc(b.service.name)}\n📅 {bk.when(b)}{addr}", kb)
            sent += 1
        await s.commit()  # фиксируем флаг сразу, чтобы падение на следующей записи не дало дубль
    return sent


async def _finish_visits(s, now: datetime) -> int:
    finished = (await s.scalars(select(Booking).where(
        Booking.status == "confirmed", Booking.ends_at <= now))).unique().all()
    for b in finished:
        b.status = "completed"
        await s.commit()
        if b.ends_at > now - timedelta(hours=settings.review_window_hours):  # после простоя не спамим
            kb = {"inline_keyboard": [[{"text": "⭐" * n, "callback_data": f"rev:{b.id}:{n}"}]
                                      for n in (5, 4, 3, 2, 1)]}
            await notify.send(b.client.telegram_id,
                              f"Спасибо, что выбрали «{esc(b.tenant.name)}»! 🙏\n"
                              f"Как прошёл визит к мастеру {esc(b.master.name)}? Оцените, пожалуйста:", kb)
    return len(finished)


async def _expire_unpaid(s, now: datetime) -> int:
    """Чек не прислали вовремя — снимаем бронь. Если чек прислан и ждёт админа — не трогаем,
    пока визит не прошёл."""
    deadline = now - timedelta(minutes=settings.prepay_timeout_min)
    rows = (await s.scalars(select(Booking).where(Booking.status == "pending_payment"))).unique().all()
    n = 0
    for b in rows:
        p = await s.scalar(select(Payment).where(Payment.booking_id == b.id).order_by(Payment.id.desc()))
        waiting_receipt = p is None or p.status == "awaiting"
        if (waiting_receipt and b.created_at < deadline) or b.starts_at <= now:
            await bk.cancel(s, b, "system")
            n += 1
    return n


async def tick() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as s:
        stats = {}
        for name, job in (("reminders", _reminders), ("finished", _finish_visits), ("expired", _expire_unpaid)):
            try:
                stats[name] = await job(s, now)
            except Exception:
                logger.exception(f"background job {name} failed")
                await s.rollback()
    if any(stats.values()):
        logger.info(f"tick: {stats}")
