from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Booking, Master, MasterTimeOff, Service, Tenant, WorkingHours


def today(tenant: Tenant) -> date:
    return datetime.now(ZoneInfo(tenant.timezone)).date()


def day_range(tenant: Tenant, day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(tenant.timezone))
    return start, start + timedelta(days=1)


async def free_slots(session: AsyncSession, tenant: Tenant, master: Master,
                     service: Service, day: date) -> list[datetime]:
    if not (master.is_active and service.is_active):
        return []
    if not (today(tenant) <= day <= today(tenant) + timedelta(days=settings.booking_horizon_days)):
        return []
    if await session.scalar(select(MasterTimeOff.id).where(
            MasterTimeOff.master_id == master.id, MasterTimeOff.day == day)):
        return []
    hours = (await session.scalars(
        select(WorkingHours).where(WorkingHours.master_id == master.id,
                                   WorkingHours.weekday == day.weekday()))).all()
    if not hours:
        return []

    tz = ZoneInfo(tenant.timezone)
    day_start, day_end = day_range(tenant, day)
    busy = (await session.execute(
        select(Booking.starts_at, Booking.ends_at).where(
            Booking.master_id == master.id,
            Booking.status != "cancelled",
            Booking.starts_at < day_end,
            Booking.ends_at > day_start))).all()

    dur = timedelta(minutes=service.duration_min)
    step = timedelta(minutes=settings.slot_step_min)
    now = datetime.now(tz)
    out: set[datetime] = set()
    for h in hours:
        cur = datetime.combine(day, h.start_time, tzinfo=tz)
        end = datetime.combine(day, h.end_time, tzinfo=tz)
        while cur + dur <= end:
            if cur > now and not any(cur < b_end and cur + dur > b_start for b_start, b_end in busy):
                out.add(cur)
            cur += step
    return sorted(out)


async def available_days(session: AsyncSession, tenant: Tenant, master: Master,
                         service: Service) -> list[dict]:
    """Ближайшие дни, где у мастера есть хоть одно окно под эту услугу."""
    out = []
    start = today(tenant)
    for i in range(settings.booking_horizon_days + 1):
        d = start + timedelta(days=i)
        n = len(await free_slots(session, tenant, master, service, d))
        if n:
            out.append({"day": d, "free": n})
    return out
