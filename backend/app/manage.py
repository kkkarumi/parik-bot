"""Служебные команды (в докере: docker compose exec backend python -m app.manage <команда>).

  init        создать салон (берёт SALON_NAME, TENANT_API_KEY, TZ, ADMIN_CHAT_ID из .env)
              и выдать ссылку, по которой владелец станет админом
  demo        добавить демо-услуги и демо-мастеров (если их ещё нет)
  admin-link  выдать новую ссылку для входа админа (старый админ остаётся до перехода по ссылке)
  status      что сейчас в базе
"""
import asyncio
import os
import sys
import httpx
from dotenv import load_dotenv
from sqlalchemy import func, select

from .admin_api import DEFAULT_HOURS, new_code
from .config import ROOT, settings
from .db import SessionLocal, engine
from .migrate import upgrade_db
from .models import Booking, Client, Master, MasterService, Service, Tenant, WorkingHours

load_dotenv(ROOT / ".env")


def bot_link(code: str) -> str:
    username = None
    if settings.bot_token:
        try:
            r = httpx.get(f"https://api.telegram.org/bot{settings.bot_token}/getMe", timeout=10)
            username = r.json()["result"]["username"]
        except Exception:
            pass
    if username:
        return f"https://t.me/{username}?start={code}"
    return f"откройте бота и отправьте: /start {code}"


async def tenant(s) -> Tenant | None:
    return await s.scalar(select(Tenant).where(Tenant.api_key == os.environ["TENANT_API_KEY"]))


async def init():
    async with SessionLocal() as s:
        t = await tenant(s)
        if t:
            print(f"Салон «{t.name}» уже создан.")
        else:
            admin = os.environ.get("ADMIN_CHAT_ID", "").strip()
            t = Tenant(name=os.environ.get("SALON_NAME", "").strip() or "Мой салон",
                       api_key=os.environ["TENANT_API_KEY"], timezone=os.environ.get("TZ", "Europe/Moscow"),
                       admin_chat_id=int(admin) if admin else None)
            s.add(t)
            print(f"Салон «{t.name}» создан.")
        if t.admin_chat_id is None:
            t.admin_invite_code = new_code()
            print("\nСсылка для владельца — кто откроет её первым, тот станет админом:\n  "
                  + bot_link(f"admin_{t.admin_invite_code}"))
        else:
            print(f"Админ: {t.admin_chat_id}")
        await s.commit()


async def demo():
    async with SessionLocal() as s:
        t = await tenant(s)
        if not t:
            return print("Сначала: python -m app.manage init")
        if await s.scalar(select(func.count(Service.id)).where(Service.tenant_id == t.id)):
            return print("Услуги уже есть — демо не добавляю.")
        svcs = [Service(tenant_id=t.id, name=n, price=p, duration_min=d, is_active=True)
                for n, p, d in [("Мужская стрижка", 800, 60), ("Стрижка бороды", 500, 30),
                                ("Стрижка + борода", 1200, 90), ("Детская стрижка", 600, 45)]]
        masters = [Master(tenant_id=t.id, name=n, is_active=True) for n in ("Алим", "Тимур")]
        s.add_all(svcs + masters)
        await s.flush()
        for m in masters:
            for sv in svcs:
                s.add(MasterService(master_id=m.id, service_id=sv.id))
            for wd, a, b in DEFAULT_HOURS:
                s.add(WorkingHours(master_id=m.id, weekday=wd, start_time=a, end_time=b))
        t.address = t.address or "г. Нальчик, ул. Примерная, 1"
        t.work_hours_text = t.work_hours_text or "Пн–Сб 10:00–20:00"
        await s.commit()
        print("Демо-данные добавлены: 4 услуги, 2 мастера (Пн–Сб 10–20). Поменять — /admin в боте.")


async def admin_link():
    async with SessionLocal() as s:
        t = await tenant(s)
        if not t:
            return print("Сначала: python -m app.manage init")
        t.admin_invite_code = new_code()
        await s.commit()
        print(bot_link(f"admin_{t.admin_invite_code}"))


async def status():
    async with SessionLocal() as s:
        t = await tenant(s)
        if not t:
            return print("Салон не создан. Запустите: python -m app.manage init")
        print(f"Салон: {t.name} · tz={t.timezone} · админ={t.admin_chat_id} · предоплата={t.prepay_amount}₽")
        for m in (await s.scalars(select(Master).where(Master.tenant_id == t.id))).all():
            print(f"  мастер {m.name!r}: telegram={m.telegram_chat_id} active={m.is_active}")
        for sv in (await s.scalars(select(Service).where(Service.tenant_id == t.id))).all():
            print(f"  услуга {sv.name!r}: {sv.price}₽ / {sv.duration_min} мин active={sv.is_active}")
        print("Клиентов:", await s.scalar(select(func.count(Client.id)).where(Client.tenant_id == t.id)),
              "· записей:", await s.scalar(select(func.count(Booking.id)).where(Booking.tenant_id == t.id)))


async def main(cmd: str):
    await upgrade_db()
    await {"init": init, "demo": demo, "admin-link": admin_link, "status": status}[cmd]()
    await engine.dispose()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("init", "demo", "admin-link", "status"):
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(cmd))
