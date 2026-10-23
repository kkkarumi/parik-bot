"""Админка салона: всё, что владелец настраивает сам, без программиста."""
import secrets
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import bookings as bk, notify
from .db import get_session
from .deps import require_admin
from .models import (Booking, Client, Master, MasterService, MasterTimeOff, Payment, Review, Service,
                     Tenant, WorkingHours)
from .schemas import (ClientOut, DayHours, InviteOut, MasterAdminOut, MasterIn, MasterPatch, SalonAdminOut,
                      SalonPatch, ServiceAdminOut, ServiceIds, ServiceIn, ServicePatch, Stats, TimeOffIn)
from .slots import day_range, today

router = APIRouter(prefix="/admin")

DEFAULT_HOURS = [(wd, time(10), time(20)) for wd in range(6)]  # Пн–Сб 10–20, Вс выходной


def new_code() -> str:
    return secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")


# ---------- салон ----------
@router.get("/salon", response_model=SalonAdminOut)
async def get_salon(t: Tenant = Depends(require_admin)):
    return t


@router.patch("/salon", response_model=SalonAdminOut)
async def patch_salon(data: SalonPatch, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    for k, v in data.model_dump(exclude_unset=True).items():
        if isinstance(v, str):
            v = v.strip() or None
            if k == "name" and not v:
                continue
        setattr(t, k, v)
    if t.prepay_amount and not t.payment_details:
        raise HTTPException(422, "set payment_details before enabling prepayment")
    await s.commit()
    return t


@router.post("/salon/admin-invite", response_model=InviteOut)
async def admin_invite(t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    """Ссылка для передачи админки другому человеку (владельцу салона)."""
    t.admin_invite_code = new_code()
    await s.commit()
    return InviteOut(code=f"admin_{t.admin_invite_code}")


# ---------- услуги ----------
@router.get("/services", response_model=list[ServiceAdminOut])
async def list_services(t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    q = select(Service).where(Service.tenant_id == t.id).order_by(Service.is_active.desc(), Service.price)
    return (await s.scalars(q)).all()


@router.post("/services", response_model=ServiceAdminOut, status_code=201)
async def add_service(data: ServiceIn, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    sv = Service(tenant_id=t.id, is_active=True, **data.model_dump())
    s.add(sv)
    await s.flush()
    # по умолчанию новую услугу делают все активные мастера — потом можно поправить
    for m in (await s.scalars(select(Master).where(Master.tenant_id == t.id, Master.is_active))).all():
        s.add(MasterService(master_id=m.id, service_id=sv.id))
    await s.commit()
    return sv


async def _service(s: AsyncSession, t: Tenant, service_id: int) -> Service:
    sv = await s.scalar(select(Service).where(Service.id == service_id, Service.tenant_id == t.id))
    if not sv:
        raise HTTPException(404)
    return sv


@router.patch("/services/{service_id}", response_model=ServiceAdminOut)
async def patch_service(service_id: int, data: ServicePatch, t: Tenant = Depends(require_admin),
                        s: AsyncSession = Depends(get_session)):
    sv = await _service(s, t, service_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(sv, k, v.strip() if isinstance(v, str) else v)
    await s.commit()
    return sv


# ---------- мастера ----------
async def _master_out(s: AsyncSession, m: Master) -> MasterAdminOut:
    sids = (await s.scalars(select(MasterService.service_id).where(MasterService.master_id == m.id))).all()
    return MasterAdminOut(id=m.id, name=m.name, is_active=m.is_active, linked=m.telegram_chat_id is not None,
                          service_ids=sorted(sids))


async def _master(s: AsyncSession, t: Tenant, master_id: int) -> Master:
    m = await s.scalar(select(Master).where(Master.id == master_id, Master.tenant_id == t.id))
    if not m:
        raise HTTPException(404)
    return m


@router.get("/masters", response_model=list[MasterAdminOut])
async def list_masters(t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    ms = (await s.scalars(select(Master).where(Master.tenant_id == t.id)
                          .order_by(Master.is_active.desc(), Master.name))).all()
    return [await _master_out(s, m) for m in ms]


@router.get("/masters/{master_id}", response_model=MasterAdminOut)
async def get_master(master_id: int, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    return await _master_out(s, await _master(s, t, master_id))


@router.post("/masters", response_model=MasterAdminOut, status_code=201)
async def add_master(data: MasterIn, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    m = Master(tenant_id=t.id, name=data.name.strip(), is_active=True)
    s.add(m)
    await s.flush()
    for sv in (await s.scalars(select(Service).where(Service.tenant_id == t.id, Service.is_active))).all():
        s.add(MasterService(master_id=m.id, service_id=sv.id))
    for wd, a, b in DEFAULT_HOURS:
        s.add(WorkingHours(master_id=m.id, weekday=wd, start_time=a, end_time=b))
    await s.commit()
    return await _master_out(s, m)


@router.patch("/masters/{master_id}", response_model=MasterAdminOut)
async def patch_master(master_id: int, data: MasterPatch, t: Tenant = Depends(require_admin),
                       s: AsyncSession = Depends(get_session)):
    m = await _master(s, t, master_id)
    if data.name:
        m.name = data.name.strip()
    if data.is_active is not None:
        m.is_active = data.is_active
    await s.commit()
    return await _master_out(s, m)


@router.put("/masters/{master_id}/services", response_model=MasterAdminOut)
async def set_master_services(master_id: int, data: ServiceIds, t: Tenant = Depends(require_admin),
                              s: AsyncSession = Depends(get_session)):
    m = await _master(s, t, master_id)
    valid = set((await s.scalars(select(Service.id).where(
        Service.tenant_id == t.id, Service.id.in_(data.service_ids)))).all())
    await s.execute(delete(MasterService).where(MasterService.master_id == m.id))
    for sid in sorted(valid):
        s.add(MasterService(master_id=m.id, service_id=sid))
    await s.commit()
    return await _master_out(s, m)


@router.get("/masters/{master_id}/hours", response_model=list[DayHours])
async def get_hours(master_id: int, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    m = await _master(s, t, master_id)
    rows = (await s.scalars(select(WorkingHours).where(WorkingHours.master_id == m.id)
                            .order_by(WorkingHours.weekday, WorkingHours.start_time))).all()
    return [DayHours(weekday=wd, intervals=[
        {"start": f"{r.start_time:%H:%M}", "end": f"{r.end_time:%H:%M}"} for r in rows if r.weekday == wd])
        for wd in range(7)]


@router.put("/masters/{master_id}/hours", response_model=list[DayHours])
async def set_day_hours(master_id: int, data: DayHours, t: Tenant = Depends(require_admin),
                        s: AsyncSession = Depends(get_session)):
    m = await _master(s, t, master_id)
    parsed = sorted((time.fromisoformat(i.start), time.fromisoformat(i.end)) for i in data.intervals)
    for (a, b), nxt in zip(parsed, parsed[1:] + [None], strict=False):
        if a >= b or (nxt and nxt[0] < b):
            raise HTTPException(422, "intervals must be ordered and not overlap")
    await s.execute(delete(WorkingHours).where(WorkingHours.master_id == m.id,
                                               WorkingHours.weekday == data.weekday))
    for a, b in parsed:
        s.add(WorkingHours(master_id=m.id, weekday=data.weekday, start_time=a, end_time=b))
    await s.commit()
    return await get_hours(master_id, t, s)


@router.get("/masters/{master_id}/timeoff", response_model=list[date])
async def get_timeoff(master_id: int, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    m = await _master(s, t, master_id)
    return (await s.scalars(select(MasterTimeOff.day).where(
        MasterTimeOff.master_id == m.id, MasterTimeOff.day >= today(t)).order_by(MasterTimeOff.day))).all()


@router.post("/masters/{master_id}/timeoff")
async def add_timeoff(master_id: int, data: TimeOffIn, t: Tenant = Depends(require_admin),
                      s: AsyncSession = Depends(get_session)) -> dict:
    """Возвращает записи, которые уже стоят на этот день: их нужно перенести/отменить вручную."""
    m = await _master(s, t, master_id)
    if not await s.scalar(select(MasterTimeOff.id).where(MasterTimeOff.master_id == m.id,
                                                         MasterTimeOff.day == data.day)):
        s.add(MasterTimeOff(master_id=m.id, day=data.day))
        await s.commit()
    start, end = day_range(t, data.day)
    clash = (await s.scalars(select(Booking).where(
        Booking.master_id == m.id, Booking.status.in_(("pending_payment", "confirmed")),
        Booking.starts_at >= start, Booking.starts_at < end))).unique().all()
    return {"ok": True, "bookings": [bk.booking_out(b).model_dump(mode="json") for b in clash]}


@router.delete("/masters/{master_id}/timeoff/{day}")
async def del_timeoff(master_id: int, day: date, t: Tenant = Depends(require_admin),
                      s: AsyncSession = Depends(get_session)) -> dict:
    m = await _master(s, t, master_id)
    await s.execute(delete(MasterTimeOff).where(MasterTimeOff.master_id == m.id, MasterTimeOff.day == day))
    await s.commit()
    return {"ok": True}


@router.post("/masters/{master_id}/invite", response_model=InviteOut)
async def master_invite(master_id: int, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    m = await _master(s, t, master_id)
    m.invite_code = new_code()
    await s.commit()
    return InviteOut(code=f"m_{m.invite_code}")


@router.post("/masters/{master_id}/unlink", response_model=MasterAdminOut)
async def master_unlink(master_id: int, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    m = await _master(s, t, master_id)
    m.telegram_chat_id = m.invite_code = None
    await s.commit()
    return await _master_out(s, m)


# ---------- клиенты ----------
@router.get("/clients/search", response_model=list[ClientOut])
async def search_clients(q: str, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    # фильтруем в Python: SQLite не умеет lower() для кириллицы, а клиентов у салона — тысячи, не миллионы
    q = q.strip().lstrip("@").casefold()
    digits = "".join(ch for ch in q if ch.isdigit())
    if not q:
        return []

    def match(c: Client) -> bool:
        if q in (c.name or "").casefold() or q in (c.username or "").casefold():
            return True
        return len(digits) >= 4 and digits in "".join(ch for ch in (c.phone or "") if ch.isdigit())

    rows = (await s.scalars(select(Client).where(Client.tenant_id == t.id).order_by(Client.name))).all()
    return [c for c in rows if match(c)][:10]


@router.get("/clients/ids", response_model=list[int])
async def client_ids(t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    """Для рассылки: все незаблокированные клиенты."""
    return (await s.scalars(select(Client.telegram_id).where(Client.tenant_id == t.id, ~Client.is_blocked))).all()


# ---------- предоплата ----------
async def _payment(s: AsyncSession, t: Tenant, payment_id: int) -> Payment:
    p = await s.scalar(select(Payment).where(Payment.id == payment_id))
    if not p or p.booking.tenant_id != t.id:
        raise HTTPException(404)
    return p


@router.post("/payments/{payment_id}/approve")
async def approve_payment(payment_id: int, t: Tenant = Depends(require_admin),
                          s: AsyncSession = Depends(get_session)) -> dict:
    p = await _payment(s, t, payment_id)
    b = p.booking
    if p.status not in ("awaiting", "pending") or b.status != "pending_payment":
        return {"ok": False, "status": b.status, "payment": p.status}
    p.status, b.status = "approved", "confirmed"
    await s.commit()
    b = await bk.reload(s, b.id)
    await notify.send(b.client.telegram_id,
                      f"✅ <b>Предоплата получена — вы записаны!</b>\n\n💇 {notify.esc(b.master.name)}\n"
                      f"✂️ {notify.esc(b.service.name)}\n📅 {bk.when(b)}\n\nНапомню за 24 часа и за 2 часа до визита.")
    await bk.to_staff(b, bk.card(b, "✅ <b>Предоплата получена — запись подтверждена</b>"), admin=False)
    return {"ok": True, "status": b.status}


@router.post("/payments/{payment_id}/reject")
async def reject_payment(payment_id: int, t: Tenant = Depends(require_admin),
                         s: AsyncSession = Depends(get_session)) -> dict:
    p = await _payment(s, t, payment_id)
    b = p.booking
    if b.status != "pending_payment":
        return {"ok": False, "status": b.status, "payment": p.status}
    b.status, b.cancelled_by, p.status = "cancelled", "staff", "rejected"
    await s.commit()
    await bk.to_staff(b, bk.card(b, "🗑 <b>Бронь снята — оплата не подтверждена</b>"), admin=False)
    await notify.send(b.client.telegram_id,
                      f"❌ Оплата по записи на {bk.when(b)} не подтверждена, бронь снята.\n"
                      f"Если это ошибка — позвоните нам{': ' + notify.esc(t.phone) if t.phone else ''}.")
    return {"ok": True, "status": b.status}


# ---------- статистика ----------
@router.get("/stats", response_model=Stats)
async def stats(days: int = 30, t: Tenant = Depends(require_admin), s: AsyncSession = Depends(get_session)):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = (await s.scalars(select(Booking).where(
        Booking.tenant_id == t.id, Booking.starts_at >= since, Booking.starts_at <= now))).unique().all()
    done = [b for b in rows if b.status == "completed"]

    def top(key):
        acc: dict[str, dict] = {}
        for b in done:
            k = key(b)
            acc.setdefault(k, {"name": k, "visits": 0, "revenue": 0})
            acc[k]["visits"] += 1
            acc[k]["revenue"] += b.price
        return sorted(acc.values(), key=lambda x: -x["revenue"])[:5]

    rating = (await s.execute(select(func.avg(Review.rating), func.count(Review.id))
                              .join(Booking, Booking.id == Review.booking_id)
                              .where(Booking.tenant_id == t.id, Review.created_at >= since))).one()
    return Stats(
        days=days, bookings=len(rows), completed=len(done),
        cancelled=sum(b.status == "cancelled" for b in rows),
        no_show=sum(b.status == "no_show" for b in rows),
        revenue=sum(b.price for b in done),
        upcoming=await s.scalar(select(func.count(Booking.id)).where(
            Booking.tenant_id == t.id, Booking.status == "confirmed", Booking.starts_at > now)),
        new_clients=await s.scalar(select(func.count(Client.id)).where(
            Client.tenant_id == t.id, Client.created_at >= since)),
        avg_rating=round(float(rating[0]), 2) if rating[0] is not None else None,
        reviews=rating[1],
        by_master=top(lambda b: b.master.name), by_service=top(lambda b: b.service.name))
