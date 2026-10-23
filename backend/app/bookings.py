"""Общая логика записей: форматирование, уведомления, смена статусов."""
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notify
from .models import Booking, Payment
from .notify import esc
from .schemas import BookingOut


WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def when(b: Booking) -> str:
    d = b.starts_at.astimezone(ZoneInfo(b.tenant.timezone))
    return f"{d:%d.%m} ({WD[d.weekday()]}) в {d:%H:%M}"


def booking_out(b: Booking) -> BookingOut:
    pending = b.status == "pending_payment"
    return BookingOut(
        id=b.id, starts_at=b.starts_at, ends_at=b.ends_at, price=b.price, status=b.status,
        master_id=b.master_id, master_name=b.master.name, service_name=b.service.name,
        client_id=b.client_id, client_name=b.client.name, client_phone=b.client.phone,
        client_username=b.client.username,
        prepay_amount=b.tenant.prepay_amount if pending else 0,
        payment_details=b.tenant.payment_details if pending else None)


async def reload(s: AsyncSession, booking_id: int) -> Booking:
    return await s.scalar(select(Booking).where(Booking.id == booking_id)
                          .execution_options(populate_existing=True))


def card(b: Booking, title: str) -> str:
    c = b.client
    who = esc(c.name or "Без имени") + (f" (@{esc(c.username)})" if c.username else "")
    return (f"{title}\n\n💇 {esc(b.master.name)}\n✂️ {esc(b.service.name)} ({b.price}₽)\n"
            f"📅 {when(b)}\n👤 {who}\n📞 <code>{esc(c.phone or '—')}</code>")


async def to_staff(b: Booking, text: str, *, master: bool = True, admin: bool = True,
                   skip: int | None = None) -> None:
    """Сообщение мастеру записи и/или админу салона (без дублей, если это один человек)."""
    sent = {skip} if skip else set()
    for chat_id, on in ((b.master.telegram_chat_id, master), (b.tenant.admin_chat_id, admin)):
        if on and chat_id and chat_id not in sent:
            sent.add(chat_id)
            await notify.send(chat_id, text)


async def announce_new(b: Booking) -> None:
    if b.status == "pending_payment":
        await to_staff(b, card(b, f"🕓 <b>Новая запись — ждёт предоплату {b.tenant.prepay_amount}₽</b>"),
                       master=False)
    else:
        await to_staff(b, card(b, "🔔 <b>Новая запись</b>"))


async def cancel(s: AsyncSession, b: Booking, by: str, actor_chat_id: int | None = None) -> None:
    """by: client | staff | system. Уведомляет «другую сторону»."""
    was_pending = b.status == "pending_payment"
    b.status, b.cancelled_by = "cancelled", by
    for p in (await s.scalars(select(Payment).where(
            Payment.booking_id == b.id, Payment.status.in_(("awaiting", "pending"))))).all():
        p.status = "expired" if by == "system" else "rejected"
    await s.commit()

    if by == "client":
        await to_staff(b, card(b, "❌ <b>Клиент отменил запись</b>"), master=not was_pending)
    elif by == "staff":
        await notify.send(b.client.telegram_id,
                          f"⚠️ <b>Ваша запись отменена салоном</b>\n\n💇 {esc(b.master.name)}\n"
                          f"✂️ {esc(b.service.name)}\n📅 {when(b)}\n\n"
                          "Извините за неудобства. Выберите другое время: /start")
        await to_staff(b, card(b, "🗑 <b>Запись отменена</b>"), master=not was_pending, skip=actor_chat_id)
    else:  # system — не дождались предоплаты
        await notify.send(b.client.telegram_id,
                          f"⌛️ Бронь на {when(b)} снята: не получили подтверждение предоплаты.\n"
                          "Можно записаться заново: /start")
        await to_staff(b, card(b, "⌛️ <b>Бронь снята — нет предоплаты</b>"), master=False)
