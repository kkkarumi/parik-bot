"""Клиентская часть API: каталог, запись, отмена, отзывы, чеки предоплаты."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import bookings as bk, notify
from .config import settings
from .db import get_session
from .deps import get_tenant
from .models import (ACTIVE_STATUSES, Booking, Client, Master, MasterService, Payment, Review,
                     Service, Tenant)
from .notify import esc
from .schemas import (BookingIn, BookingOut, ClientIn, ClientOut, MasterOut, ReceiptIn, ReviewIn,
                      SalonOut, ServiceOut)
from .slots import available_days, free_slots

router = APIRouter()
_booking_lock = asyncio.Lock()  # SQLite / один процесс; в Postgres ещё лок строки и EXCLUDE


# ---------- каталог ----------
@router.get("/salon", response_model=SalonOut)
async def salon(t: Tenant = Depends(get_tenant)):
    return t


@router.get("/services", response_model=list[ServiceOut])
async def services(t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    """Только услуги, которые кто-то из активных мастеров реально делает."""
    q = (select(Service).where(Service.tenant_id == t.id, Service.is_active)
         .where(Service.id.in_(select(MasterService.service_id).join(Master, Master.id == MasterService.master_id)
                               .where(Master.is_active)))
         .order_by(Service.price, Service.name))
    return (await s.scalars(q)).all()


@router.get("/masters", response_model=list[MasterOut])
async def masters(service_id: int | None = None, t: Tenant = Depends(get_tenant),
                  s: AsyncSession = Depends(get_session)):
    q = select(Master).where(Master.tenant_id == t.id, Master.is_active)
    if service_id:
        q = q.join(MasterService, MasterService.master_id == Master.id).where(
            MasterService.service_id == service_id)
    return (await s.scalars(q.order_by(Master.name))).all()


async def _master_service(s: AsyncSession, t: Tenant, master_id: int, service_id: int):
    master = await s.scalar(select(Master).where(Master.id == master_id, Master.tenant_id == t.id))
    service = await s.scalar(select(Service).where(Service.id == service_id, Service.tenant_id == t.id))
    if not master or not service:
        raise HTTPException(404)
    return master, service


@router.get("/days")
async def days(master_id: int, service_id: int, t: Tenant = Depends(get_tenant),
               s: AsyncSession = Depends(get_session)) -> list[dict]:
    master, service = await _master_service(s, t, master_id, service_id)
    return await available_days(s, t, master, service)


@router.get("/slots", response_model=list[datetime])
async def slots(master_id: int, service_id: int, date: date, t: Tenant = Depends(get_tenant),
                s: AsyncSession = Depends(get_session)):
    master, service = await _master_service(s, t, master_id, service_id)
    return await free_slots(s, t, master, service, date)


# ---------- клиенты ----------
@router.put("/clients", response_model=ClientOut)
async def upsert_client(data: ClientIn, t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    c = await s.scalar(select(Client).where(Client.tenant_id == t.id, Client.telegram_id == data.telegram_id))
    if c:
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(c, k, v)
    else:
        c = Client(tenant_id=t.id, **data.model_dump())
        s.add(c)
    try:
        await s.commit()
    except IntegrityError:  # два параллельных /start одного человека
        await s.rollback()
        c = await s.scalar(select(Client).where(Client.tenant_id == t.id, Client.telegram_id == data.telegram_id))
    return c


# ---------- записи ----------
@router.post("/bookings", response_model=BookingOut, status_code=201)
async def create_booking(data: BookingIn, t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    async with _booking_lock:
        master = await s.scalar(select(Master).where(
            Master.id == data.master_id, Master.tenant_id == t.id, Master.is_active).with_for_update())
        service = await s.scalar(select(Service).where(
            Service.id == data.service_id, Service.tenant_id == t.id, Service.is_active))
        client = await s.scalar(select(Client).where(Client.id == data.client_id, Client.tenant_id == t.id))
        if not (master and service and client):
            raise HTTPException(404)
        if client.is_blocked:
            raise HTTPException(403, "client is blocked")
        if not await s.scalar(select(MasterService.master_id).where(
                MasterService.master_id == master.id, MasterService.service_id == service.id)):
            raise HTTPException(409, "master does not provide this service")

        active = await s.scalar(select(func.count(Booking.id)).where(
            Booking.client_id == client.id, Booking.status.in_(ACTIVE_STATUSES),
            Booking.starts_at > datetime.now(timezone.utc)))
        if active >= settings.max_active_bookings:
            raise HTTPException(429, "too many active bookings")

        day = data.starts_at.astimezone(ZoneInfo(t.timezone)).date()
        if data.starts_at not in await free_slots(s, t, master, service, day):
            raise HTTPException(409, "slot is not available")

        prepay = t.prepay_amount > 0
        b = Booking(tenant_id=t.id, master_id=master.id, service_id=service.id, client_id=client.id,
                    starts_at=data.starts_at,
                    ends_at=data.starts_at + timedelta(minutes=service.duration_min), price=service.price,
                    status="pending_payment" if prepay else "confirmed")
        s.add(b)
        try:
            await s.flush()
            if prepay:
                s.add(Payment(booking_id=b.id, amount=t.prepay_amount, status="awaiting"))
            await s.commit()
        except IntegrityError:  # Postgres EXCLUDE: интервал уже занят
            await s.rollback()
            raise HTTPException(409, "slot is not available")

    b = await bk.reload(s, b.id)
    await bk.announce_new(b)
    return bk.booking_out(b)


@router.get("/bookings", response_model=list[BookingOut])
async def my_bookings(telegram_id: int, t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    q = (select(Booking).join(Client, Client.id == Booking.client_id)
         .where(Booking.tenant_id == t.id, Client.telegram_id == telegram_id,
                Booking.status.in_(ACTIVE_STATUSES), Booking.ends_at > datetime.now(timezone.utc))
         .order_by(Booking.starts_at))
    return [bk.booking_out(b) for b in (await s.scalars(q)).unique().all()]


async def _own_booking(s: AsyncSession, t: Tenant, booking_id: int, telegram_id: int) -> Booking:
    b = await s.scalar(select(Booking).join(Client, Client.id == Booking.client_id).where(
        Booking.id == booking_id, Booking.tenant_id == t.id, Client.telegram_id == telegram_id))
    if not b:
        raise HTTPException(404)
    return b


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
async def cancel(booking_id: int, telegram_id: int, t: Tenant = Depends(get_tenant),
                 s: AsyncSession = Depends(get_session)):
    b = await _own_booking(s, t, booking_id, telegram_id)
    if b.status not in ACTIVE_STATUSES or b.ends_at <= datetime.now(timezone.utc):
        raise HTTPException(409, "already " + b.status)
    await bk.cancel(s, b, "client")
    return bk.booking_out(b)


@router.post("/bookings/{booking_id}/confirm", response_model=BookingOut)
async def client_confirm(booking_id: int, telegram_id: int, t: Tenant = Depends(get_tenant),
                         s: AsyncSession = Depends(get_session)):
    """Кнопка «Приду» из напоминания."""
    b = await _own_booking(s, t, booking_id, telegram_id)
    if b.status != "confirmed":
        raise HTTPException(409, "booking is " + b.status)
    b.client_confirmed = True
    await s.commit()
    return bk.booking_out(b)


@router.post("/bookings/{booking_id}/review", status_code=201)
async def review(booking_id: int, telegram_id: int, data: ReviewIn, t: Tenant = Depends(get_tenant),
                 s: AsyncSession = Depends(get_session)):
    b = await _own_booking(s, t, booking_id, telegram_id)
    if b.status != "completed":
        raise HTTPException(409, "visit not completed")
    if await s.scalar(select(Review).where(Review.booking_id == b.id)):
        raise HTTPException(409, "already reviewed")
    s.add(Review(booking_id=b.id, rating=data.rating, text=data.text))
    await s.commit()
    stars = "⭐" * data.rating
    extra = f"\n💬 {esc(data.text)}" if data.text else ""
    await bk.to_staff(b, f"{stars} <b>Отзыв {data.rating}/5</b>\n\n💇 {esc(b.master.name)} · "
                         f"✂️ {esc(b.service.name)}\n👤 {esc(b.client.name)} · {bk.when(b)}{extra}")
    return {"ok": True}


@router.post("/bookings/{booking_id}/receipt", status_code=201)
async def receipt(booking_id: int, telegram_id: int, data: ReceiptIn, t: Tenant = Depends(get_tenant),
                  s: AsyncSession = Depends(get_session)):
    """Клиент прислал чек о предоплате — пересылаем админу с кнопками подтвердить/отклонить."""
    b = await _own_booking(s, t, booking_id, telegram_id)
    if b.status != "pending_payment":
        raise HTTPException(409, "booking is " + b.status)
    p = await s.scalar(select(Payment).where(Payment.booking_id == b.id,
                                             Payment.status.in_(("awaiting", "pending"))))
    if not p:
        raise HTTPException(409, "no payment expected")
    p.receipt_file_id, p.status = data.file_id, "pending"
    await s.commit()
    kb = {"inline_keyboard": [[{"text": "✅ Оплата пришла", "callback_data": f"pay_ok:{p.id}"},
                               {"text": "❌ Отклонить", "callback_data": f"pay_no:{p.id}"}]]}
    sent = await notify.send_file(t.admin_chat_id, data.file_id, data.kind,
                                  bk.card(b, f"💳 <b>Чек о предоплате {p.amount}₽</b>"), kb)
    return {"ok": True, "delivered": sent}
