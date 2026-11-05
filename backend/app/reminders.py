"""Фоновая работа раз в минуту. Состояние живёт в БД (флаги reminded_*, статусы),
поэтому рестарт бэкенда ничего не теряет и ничего не шлёт дважды.

Напоминание считается отправленным, только если Telegram его принял. Если Telegram или релей
недоступны (notify.send вернул False), флаг не ставится и на следующем тике будет новая попытка —
пока напоминание не потеряло смысл: «за 24 ч» повторяем до начала окна «за 2 ч» (дальше его заменяет
напоминание за 2 ч), «за 2 ч» — до начала визита."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select

from . import bookings as bk, notify
from .config import settings
from .db import SessionLocal
from .models import Booking, Payment
from .notify import esc


def _relative(b: Booking, now: datetime) -> str:
    """«сегодня в 15:00» / «завтра в 12:00»: текст верен, даже если напоминание ушло с опозданием."""
    tz = ZoneInfo(b.tenant.timezone)
    start = b.starts_at.astimezone(tz)
    days = (start.date() - now.astimezone(tz).date()).days
    if days == 0:
        return f"сегодня в {start:%H:%M}"
    if days == 1:
        return f"завтра в {start:%H:%M}"
    return bk.when(b)


async def _reminders(s, now: datetime) -> int:
    upcoming = (await s.scalars(select(Booking).where(
        Booking.status == "confirmed", Booking.starts_at > now,
        Booking.starts_at <= now + timedelta(hours=24)))).unique().all()
    sent = 0
    for b in upcoming:
        left = b.starts_at - now
        kind = None  # какое напоминание отправить: "2h" | "24h"
        if left <= timedelta(hours=2):
            b.reminded_24h = True  # «за 24 ч» уже не актуально — дальше только «за 2 ч»
            if not b.reminded_2h:
                if b.created_at < b.starts_at - timedelta(hours=2):
                    kind = "2h"
                else:
                    b.reminded_2h = True  # записался меньше чем за 2 ч — напоминать незачем
        elif not b.reminded_24h:
            if b.created_at < b.starts_at - timedelta(hours=24):
                kind = "24h"
            else:
                b.reminded_24h = True
        if kind:
            # отменить самому уже нельзя (CANCEL_BEFORE_MIN) — кнопку не показываем, даём телефон
            can_cancel = not settings.cancel_before_min or left >= timedelta(minutes=settings.cancel_before_min)
            buttons = [{"text": "✅ Приду", "callback_data": f"rem_ok:{b.id}"}]
            if can_cancel:
                buttons.append({"text": "❌ Отменить", "callback_data": f"rem_cancel:{b.id}"})
            kb = None if b.client_confirmed else {"inline_keyboard": [buttons]}
            addr = f"\n📍 {esc(b.tenant.address)}" if b.tenant.address else ""
            late = "" if can_cancel else (
                "\n\nЕсли планы изменились, позвоните нам" + (f": {esc(b.tenant.phone)}" if b.tenant.phone else "."))
            ok = await notify.send(b.client.telegram_id,
                                   f"⏰ <b>Напоминание: запись {_relative(b, now)}</b>\n\n💇 {esc(b.master.name)}\n"
                                   f"✂️ {esc(b.service.name)}\n📅 {bk.when(b)}{addr}{late}", kb)
            if ok is not False:  # доставлено или повторять бессмысленно (клиент заблокировал бота)
                if kind == "2h":
                    b.reminded_2h = True
                else:
                    b.reminded_24h = True
                sent += bool(ok)
        await s.commit()  # фиксируем флаг сразу, чтобы падение на следующей записи не дало дубль
    return sent


async def _finish_visits(s, now: datetime) -> int:
    finished = (await s.scalars(select(Booking).where(
        Booking.status == "confirmed", Booking.ends_at <= now))).unique().all()
    for b in finished:
        b.status = "completed"
        await s.commit()
        if b.client.erased_at is None and b.ends_at > now - timedelta(hours=settings.review_window_hours):
            # после простоя не спамим; клиенту, удалившему данные, не пишем
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
