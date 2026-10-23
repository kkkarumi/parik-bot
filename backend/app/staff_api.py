"""API для мастеров и админа: расписание, действия с записями, карточки клиентов, привязка аккаунтов."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import bookings as bk
from .db import get_session
from .deps import Staff, get_staff, get_tenant, resolve_role
from .models import ACTIVE_STATUSES, Booking, Client, Master, Tenant
from .slots import day_range
from .schemas import BookingOut, ClientCard, ClientPatch, LinkIn, RoleOut, StaffIds

router = APIRouter(prefix="/staff")


@router.get("/role", response_model=RoleOut)
async def role(telegram_id: int, t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    st = await resolve_role(s, t, telegram_id)
    if st.is_admin:
        return RoleOut(role="admin", master_id=st.master.id if st.master else None, name=t.name)
    if st.master:
        return RoleOut(role="master", master_id=st.master.id, name=st.master.name)
    return RoleOut(role=None)


@router.get("/ids", response_model=StaffIds)
async def ids(t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    """Для бота: кому показывать служебные команды в меню."""
    ms = (await s.scalars(select(Master.telegram_chat_id).where(
        Master.tenant_id == t.id, Master.is_active, Master.telegram_chat_id.is_not(None)))).all()
    return StaffIds(admin=t.admin_chat_id, masters=list(ms))


@router.post("/link", response_model=RoleOut)
async def link(data: LinkIn, t: Tenant = Depends(get_tenant), s: AsyncSession = Depends(get_session)):
    """Одноразовые ссылки-приглашения: admin_<код> делает админом, m_<код> — привязывает мастера."""
    kind, _, code = data.code.partition("_")
    if kind == "admin" and code and t.admin_invite_code and code == t.admin_invite_code:
        t.admin_chat_id, t.admin_invite_code = data.telegram_id, None
        await s.commit()
        return RoleOut(role="admin", name=t.name)
    if kind == "m" and code:
        m = await s.scalar(select(Master).where(Master.tenant_id == t.id, Master.invite_code == code))
        if m:
            # один telegram — один мастер
            for other in (await s.scalars(select(Master).where(
                    Master.tenant_id == t.id, Master.telegram_chat_id == data.telegram_id))).all():
                other.telegram_chat_id = None
            m.telegram_chat_id, m.invite_code = data.telegram_id, None
            await s.commit()
            return RoleOut(role="master", master_id=m.id, name=m.name)
    raise HTTPException(404, "invite not found")


@router.get("/schedule", response_model=list[BookingOut])
async def schedule(day: date, st: Staff = Depends(get_staff), s: AsyncSession = Depends(get_session)):
    """Админ видит всех мастеров, мастер — только себя."""
    start, end = day_range(st.tenant, day)
    q = select(Booking).where(Booking.tenant_id == st.tenant.id, Booking.status != "cancelled",
                              Booking.starts_at >= start, Booking.starts_at < end)
    if not st.is_admin:
        q = q.where(Booking.master_id == st.master.id)
    return [bk.booking_out(b) for b in (await s.scalars(q.order_by(Booking.starts_at, Booking.master_id))).unique().all()]


@router.get("/upcoming", response_model=list[BookingOut])
async def upcoming(limit: int = 40, master_id: int | None = None, st: Staff = Depends(get_staff),
                   s: AsyncSession = Depends(get_session)):
    """Все будущие активные записи одним списком (по времени). Мастер — только свои."""
    q = select(Booking).where(Booking.tenant_id == st.tenant.id, Booking.status.in_(ACTIVE_STATUSES),
                              Booking.ends_at > datetime.now(timezone.utc))
    if not st.is_admin:
        q = q.where(Booking.master_id == st.master.id)
    elif master_id:
        q = q.where(Booking.master_id == master_id)
    q = q.order_by(Booking.starts_at, Booking.master_id).limit(min(max(limit, 1), 100))
    return [bk.booking_out(b) for b in (await s.scalars(q)).unique().all()]


async def _staff_booking(s: AsyncSession, st: Staff, booking_id: int) -> Booking:
    b = await s.scalar(select(Booking).where(Booking.id == booking_id, Booking.tenant_id == st.tenant.id))
    if not b or not st.can_manage(b.master_id):
        raise HTTPException(404)
    return b


@router.get("/bookings/{booking_id}", response_model=BookingOut)
async def get_booking(booking_id: int, st: Staff = Depends(get_staff), s: AsyncSession = Depends(get_session)):
    return bk.booking_out(await _staff_booking(s, st, booking_id))


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
async def staff_cancel(booking_id: int, st: Staff = Depends(get_staff), s: AsyncSession = Depends(get_session)):
    b = await _staff_booking(s, st, booking_id)
    if b.status not in ACTIVE_STATUSES:
        raise HTTPException(409, "booking is " + b.status)
    await bk.cancel(s, b, "staff", actor_chat_id=st.telegram_id)
    return bk.booking_out(b)


@router.post("/bookings/{booking_id}/no_show", response_model=BookingOut)
async def no_show(booking_id: int, st: Staff = Depends(get_staff), s: AsyncSession = Depends(get_session)):
    b = await _staff_booking(s, st, booking_id)
    if b.status not in ("confirmed", "completed") or b.starts_at > datetime.now(timezone.utc):
        raise HTTPException(409, "can mark no-show only after start")
    b.status = "no_show"
    await s.commit()
    return bk.booking_out(b)


async def _client_card(s: AsyncSession, st: Staff, client_id: int) -> ClientCard:
    c = await s.scalar(select(Client).where(Client.id == client_id, Client.tenant_id == st.tenant.id))
    if not c:
        raise HTTPException(404)
    q = select(Booking).where(Booking.client_id == c.id)
    if not st.is_admin:  # мастер видит клиента, только если тот к нему записывался
        q = q.where(Booking.master_id == st.master.id)
    hist = (await s.scalars(q.order_by(Booking.starts_at.desc()))).unique().all()
    if not st.is_admin and not hist:
        raise HTTPException(404)
    return ClientCard(
        id=c.id, telegram_id=c.telegram_id, username=c.username, name=c.name, phone=c.phone,
        is_blocked=c.is_blocked, notes=c.notes,
        visits=sum(b.status == "completed" for b in hist),
        no_shows=sum(b.status == "no_show" for b in hist),
        cancelled=sum(b.status == "cancelled" for b in hist),
        spent=sum(b.price for b in hist if b.status == "completed"),
        history=[bk.booking_out(b) for b in hist[:10]])


@router.get("/clients/{client_id}", response_model=ClientCard)
async def client_card(client_id: int, st: Staff = Depends(get_staff), s: AsyncSession = Depends(get_session)):
    return await _client_card(s, st, client_id)


@router.patch("/clients/{client_id}", response_model=ClientCard)
async def patch_client(client_id: int, data: ClientPatch, st: Staff = Depends(get_staff),
                       s: AsyncSession = Depends(get_session)):
    await _client_card(s, st, client_id)  # проверка доступа
    c = await s.get(Client, client_id)
    if data.notes is not None:
        c.notes = data.notes.strip() or None
    if data.is_blocked is not None:
        if not st.is_admin:
            raise HTTPException(403, "admin only")
        c.is_blocked = data.is_blocked
    await s.commit()
    return await _client_card(s, st, client_id)
