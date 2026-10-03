"""Напоминания без хранения задач в памяти: раз в минуту смотрим в БД, кому что пора слать.
Состояние лежит в флагах bookings.reminded_*, поэтому рестарт ничего не теряет."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select

from . import notify
from .db import SessionLocal
from .models import Booking


def _fmt(b: Booking) -> str:
    return b.starts_at.astimezone(ZoneInfo(b.tenant.timezone)).strftime("%d.%m в %H:%M")


async def tick() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as s:
        upcoming = (await s.scalars(select(Booking).where(
            Booking.status == "confirmed", Booking.starts_at > now,
            Booking.starts_at <= now + timedelta(hours=24)))).unique().all()
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
                kb = {"inline_keyboard": [[
                    {"text": "✅ Приду", "callback_data": f"rem_ok:{b.id}"},
                    {"text": "❌ Отменить", "callback_data": f"rem_cancel:{b.id}"}]]}
                await notify.send(b.client.telegram_id,
                                  f"⏰ Напоминание: запись через {hours} ч.\n\n💇 {notify.esc(b.master.name)}\n"
                                  f"✂️ {notify.esc(b.service.name)}\n📅 {_fmt(b)}", kb)

        finished = (await s.scalars(select(Booking).where(
            Booking.status == "confirmed", Booking.ends_at <= now))).unique().all()
        for b in finished:
            b.status = "completed"
            if b.ends_at > now - timedelta(days=1):  # старьё после простоя не спамим отзывами
                kb = {"inline_keyboard": [[{"text": "⭐" * n, "callback_data": f"rev:{b.id}:{n}"}
                                           for n in (1, 2, 3, 4, 5)]]}
                await notify.send(b.client.telegram_id, "Как прошёл визит? Оцените, пожалуйста 🙏", kb)
        await s.commit()
    if upcoming or finished:
        logger.info(f"reminders tick: upcoming={len(upcoming)} finished={len(finished)}")
