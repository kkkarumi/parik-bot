import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import notify
from .db import get_session
from .deps import get_tenant
from .models import Booking, Client, Master, MasterService, Review, Service, Tenant
from .schemas import (BookingIn, BookingOut, ClientIn, ClientOut, MasterOut,
                      ReviewIn, SalonOut, ServiceOut)
from .slots import free_slots

router = APIRouter()
_booking_lock = asyncio.Lock()  # страховка для SQLite / одного процесса


def booking_out(b: Booking) -> BookingOut:
    return BookingOut(
        id=b.id, starts_at=b.starts_at, ends_at=b.ends_at, price=b.price, status=b.status,
        master_name=b.master.name, service_name=b.service.name,
        client_name=b.client.name, client_phone=b.client.phone)


def local(b: Booking) -> str:
    return b.starts_at.astimezone(ZoneInfo(b.tenant.timezone)).strftime("%d.%m в %H:%M")


# ---------- каталог ----------
@router.get("/salon", response_model=SalonOut)
async def salon(t: Tenant = Depends(get_tenant)):
    return t


@router.get("/services", response_model=list[ServiceOut])
async def services(t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    q = select(Service).where(Service.tenant_id == t.id, Service.is_active).order_by(Service.price)
    return (await s.scalars(q)).all()


@router.get("/masters", response_model=list[MasterOut])
async def masters(service_id: int | None = None, t: Tenant = Depends(get_tenant),
                  s: AsyncSession = Depends(get_session)):
    q = select(Master).where(Master.tenant_id == t.id, Master.is_active)
    if service_id:
        q = q.join(MasterService, MasterService.master_id == Master.id).where(
            MasterService.service_id == service_id)
    return (await s.scalars(q.order_by(Master.name))).all()


@router.get("/slots", response_model=list[datetime])
async def slots(master_id: int, service_id: int, date: date, t: Tenant = Depends(get_tenant),
                s: AsyncSession = Depends(get_session)):
    master = await s.scalar(select(Master).where(Master.id == master_id, Master.tenant_id == t.id))
    service = await s.scalar(select(Service).where(Service.id == service_id, Service.tenant_id == t.id))
    if not master or not service:
        raise HTTPException(404)
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
    await s.commit()
    return c


# ---------- записи ----------
@router.post("/bookings", response_model=BookingOut, status_code=201)
async def create_booking(data: BookingIn, t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    async with _booking_lock:
        # Postgres: плюс лок строки мастера и EXCLUDE-констрейнт в БД
        master = await s.scalar(select(Master).where(
            Master.id == data.master_id, Master.tenant_id == t.id, Master.is_active).with_for_update())
        service = await s.scalar(select(Service).where(Service.id == data.service_id, Service.tenant_id == t.id))
        client = await s.scalar(select(Client).where(Client.id == data.client_id, Client.tenant_id == t.id))
        if not (master and service and client):
            raise HTTPException(404)

        day = data.starts_at.astimezone(ZoneInfo(t.timezone)).date()
        if data.starts_at not in await free_slots(s, t, master, service, day):
            raise HTTPException(409, "slot is not available")

        b = Booking(tenant_id=t.id, master_id=master.id, service_id=service.id, client_id=client.id,
                    starts_at=data.starts_at,
                    ends_at=data.starts_at + timedelta(minutes=service.duration_min), price=service.price)
        s.add(b)
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
            raise HTTPException(409, "slot is not available")

    b = await s.scalar(select(Booking).where(Booking.id == b.id).execution_options(populate_existing=True))
    text = (f"🔔 <b>Новая запись</b>\n\n💇 {notify.esc(b.master.name)}\n✂️ {notify.esc(b.service.name)} ({b.price}₽)\n"
            f"📅 {local(b)}\n👤 {notify.esc(client.name)} (@{notify.esc(client.username or 'нет')})\n"
            f"📞 <code>{notify.esc(client.phone)}</code>")
    await notify.send(master.telegram_chat_id, text)
    if t.admin_chat_id != master.telegram_chat_id:
        await notify.send(t.admin_chat_id, text)
    return booking_out(b)


@router.get("/bookings", response_model=list[BookingOut])
async def my_bookings(telegram_id: int, t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    q = (select(Booking).join(Client, Client.id == Booking.client_id)
         .where(Booking.tenant_id == t.id, Client.telegram_id == telegram_id,
                Booking.status == "confirmed", Booking.ends_at > datetime.now(timezone.utc))
         .order_by(Booking.starts_at))
    return [booking_out(b) for b in (await s.scalars(q)).unique().all()]


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
    if b.status != "confirmed":
        raise HTTPException(409, "already " + b.status)
    b.status = "cancelled"
    await s.commit()
    text = f"❌ <b>Клиент отменил запись</b>\n\n💇 {notify.esc(b.master.name)}\n📅 {local(b)}\n👤 {notify.esc(b.client.name)}"
    await notify.send(b.master.telegram_chat_id, text)
    if t.admin_chat_id != b.master.telegram_chat_id:
        await notify.send(t.admin_chat_id, text)
    return booking_out(b)


@router.post("/bookings/{booking_id}/confirm", response_model=BookingOut)
async def client_confirm(booking_id: int, telegram_id: int, t: Tenant = Depends(get_tenant),
                         s: AsyncSession = Depends(get_session)):
    b = await _own_booking(s, t, booking_id, telegram_id)
    b.client_confirmed = True
    await s.commit()
    return booking_out(b)


@router.post("/bookings/{booking_id}/review", status_code=201)
async def review(booking_id: int, telegram_id: int, data: ReviewIn, t: Tenant = Depends(get_tenant),
                 s: AsyncSession = Depends(get_session)):
    b = await _own_booking(s, t, booking_id, telegram_id)
    if await s.scalar(select(Review).where(Review.booking_id == b.id)):
        raise HTTPException(409, "already reviewed")
    s.add(Review(booking_id=b.id, rating=data.rating, text=data.text))
    await s.commit()
    return {"ok": True}


# ---------- админка (под будущую веб-панель) ----------
@router.get("/admin/schedule", response_model=list[BookingOut])
async def schedule(day: date, master_id: int | None = None, t: Tenant = Depends(get_tenant),
                   s: AsyncSession = Depends(get_session)):
    tz = ZoneInfo(t.timezone)
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    q = select(Booking).where(Booking.tenant_id == t.id, Booking.status != "cancelled",
                              Booking.starts_at >= start, Booking.starts_at < start + timedelta(days=1))
    if master_id:
        q = q.where(Booking.master_id == master_id)
    return [booking_out(b) for b in (await s.scalars(q.order_by(Booking.starts_at))).unique().all()]


# ---------- для мастеров и админа в боте ----------
@router.get("/staff/schedule", response_model=list[BookingOut])
async def staff_schedule(telegram_id: int, day: date, t: Tenant = Depends(get_tenant),
                         s: AsyncSession = Depends(get_session)):
    """Админ салона (tenants.admin_chat_id) видит всех, мастер (masters.telegram_chat_id) — только себя."""
    tz = ZoneInfo(t.timezone)
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    q = select(Booking).where(Booking.tenant_id == t.id, Booking.status != "cancelled",
                              Booking.starts_at >= start, Booking.starts_at < start + timedelta(days=1))
    if telegram_id != t.admin_chat_id:
        m = await s.scalar(select(Master).where(Master.tenant_id == t.id, Master.telegram_chat_id == telegram_id))
        if not m:
            raise HTTPException(403, "not staff")
        q = q.where(Booking.master_id == m.id)
    return [booking_out(b) for b in (await s.scalars(q.order_by(Booking.starts_at))).unique().all()]
