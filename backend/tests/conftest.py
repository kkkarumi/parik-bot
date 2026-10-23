import os
import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# База для тестов: SQLite во временной папке, либо TEST_DATABASE_URL (например, Postgres)
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_tmp}")
os.environ["BOT_TOKEN"] = "test-token"

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import notify  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import upgrade_db  # noqa: E402
from app.models import (Base, Client, Master, MasterService, Service, Tenant,  # noqa: E402
                        WorkingHours)

TZ = ZoneInfo("Europe/Moscow")
ADMIN, M1, M2, STRANGER = 1000, 1001, 1002, 9999
KEY = "test-key"


@pytest_asyncio.fixture(autouse=True)
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await upgrade_db()
    yield
    await engine.dispose()


@pytest.fixture
def sent(monkeypatch):
    """Все сообщения, которые бэкенд отправил бы в Telegram."""
    out = []

    async def fake(method, payload):
        out.append({"method": method, **payload})
        return True
    monkeypatch.setattr(notify, "_call", fake)
    return out


@pytest_asyncio.fixture
async def api():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                                 headers={"X-Api-Key": KEY}) as c:
        yield c


@pytest_asyncio.fixture
async def salon():
    """Салон: админ, 2 мастера (оба работают каждый день 10–20), 3 услуги, 2 клиента."""
    async with SessionLocal() as s:
        t = Tenant(name="Парик", api_key=KEY, timezone="Europe/Moscow", admin_chat_id=ADMIN,
                   address="Нальчик", phone="+79990000000")
        s.add(t)
        await s.flush()
        cut = Service(tenant_id=t.id, name="Стрижка", price=800, duration_min=60, is_active=True)
        beard = Service(tenant_id=t.id, name="Борода", price=500, duration_min=30, is_active=True)
        combo = Service(tenant_id=t.id, name="Комбо", price=1200, duration_min=90, is_active=True)
        m1 = Master(tenant_id=t.id, name="Алим", telegram_chat_id=M1, is_active=True)
        m2 = Master(tenant_id=t.id, name="Тимур", telegram_chat_id=M2, is_active=True)
        s.add_all([cut, beard, combo, m1, m2])
        await s.flush()
        for sv in (cut, beard, combo):
            s.add(MasterService(master_id=m1.id, service_id=sv.id))
        s.add(MasterService(master_id=m2.id, service_id=cut.id))  # Тимур только стрижёт
        for m in (m1, m2):
            for wd in range(7):
                s.add(WorkingHours(master_id=m.id, weekday=wd, start_time=time(10), end_time=time(20)))
        c1 = Client(tenant_id=t.id, telegram_id=501, name="Иван", username="ivan", phone="+7 (928) 111-22-33")
        c2 = Client(tenant_id=t.id, telegram_id=502, name="Аслан", phone="+79282223344")
        s.add_all([c1, c2])
        await s.commit()
        return {"t": t.id, "cut": cut.id, "beard": beard.id, "combo": combo.id, "m1": m1.id, "m2": m2.id,
                "c1": c1.id, "c2": c2.id}


def tomorrow_at(h: int, m: int = 0) -> datetime:
    d = datetime.now(TZ).date() + timedelta(days=1)
    return datetime.combine(d, time(h, m), tzinfo=TZ)


def iso(dt: datetime) -> str:
    return dt.isoformat()


async def book(api, salon, *, client="c1", master="m1", service="cut", at=None):
    return await api.post("/bookings", json={
        "client_id": salon[client], "master_id": salon[master], "service_id": salon[service],
        "starts_at": iso(at or tomorrow_at(12))})


def to(sent, chat_id):
    return [m for m in sent if m.get("chat_id") == chat_id]


UTC = timezone.utc
