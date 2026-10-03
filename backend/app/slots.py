from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Booking, Master, Service, Tenant, WorkingHours


async def free_slots(session: AsyncSession, tenant: Tenant, master: Master,
                     service: Service, day: date) -> list[datetime]:
    tz = ZoneInfo(tenant.timezone)
    hours = (await session.scalars(
        select(WorkingHours).where(WorkingHours.master_id == master.id,
                                   WorkingHours.weekday == day.weekday()))).all()
    if not hours:
        return []

    day_start = datetime.combine(day, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    busy = (await session.execute(
        select(Booking.starts_at, Booking.ends_at).where(
            Booking.master_id == master.id,
            Booking.status != "cancelled",
            Booking.starts_at < day_end,
            Booking.ends_at > day_start))).all()

    dur = timedelta(minutes=service.duration_min)
    step = timedelta(minutes=settings.slot_step_min)
    now = datetime.now(tz)
    out: list[datetime] = []
    for h in hours:
        cur = datetime.combine(day, h.start_time, tzinfo=tz)
        end = datetime.combine(day, h.end_time, tzinfo=tz)
        while cur + dur <= end:
            if cur > now and not any(cur < b_end and cur + dur > b_start for b_start, b_end in busy):
                out.append(cur)
            cur += step
    return sorted(out)
