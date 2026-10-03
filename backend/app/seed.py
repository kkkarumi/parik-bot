"""python -m app.seed  — создаёт салон + демо-данные. Ключ берёт из TENANT_API_KEY."""
import asyncio
import os
from datetime import time

from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select, text

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .db import SessionLocal, engine
from .models import Base, Master, MasterService, Service, Tenant, WorkingHours


async def main():
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        key = os.environ["TENANT_API_KEY"]
        if await s.scalar(select(Tenant).where(Tenant.api_key == key)):
            print("tenant already exists")
            return
        admin = os.environ.get("ADMIN_CHAT_ID")
        t = Tenant(name="Парик", api_key=key, timezone=os.environ.get("TZ", "Europe/Moscow"),
                   admin_chat_id=int(admin) if admin else None,
                   address="г. Нальчик, ул. Пушкина, 10", phone="+7 (999) 123-45-67",
                   work_hours_text="Пн-Вс 9:00–21:00", instagram_url="https://instagram.com/")
        s.add(t)
        await s.flush()
        svcs = [Service(tenant_id=t.id, name=n, price=p, duration_min=d)
                for n, p, d in [("Стрижка", 800, 60), ("Борода", 500, 30), ("Стрижка + борода", 1200, 90)]]
        masters = [Master(tenant_id=t.id, name=n) for n in ("Мастер 1", "Мастер 2")]
        s.add_all(svcs + masters)
        await s.flush()
        for m in masters:
            for sv in svcs:
                s.add(MasterService(master_id=m.id, service_id=sv.id))
            for wd in range(7):
                s.add(WorkingHours(master_id=m.id, weekday=wd, start_time=time(9), end_time=time(21)))
        await s.commit()
        print("seeded")


asyncio.run(main())
