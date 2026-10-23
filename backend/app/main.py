from contextlib import asynccontextmanager

import sentry_sdk
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from sqlalchemy import text

from .admin_api import router as admin_router
from .api import router
from .config import settings
from .db import engine
from .migrate import upgrade_db
from .reminders import tick
from .staff_api import router as staff_router

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await upgrade_db()
    sched = AsyncIOScheduler()
    sched.add_job(tick, "interval", seconds=60, max_instances=1, coalesce=True)
    sched.start()
    yield
    sched.shutdown(wait=False)
    await engine.dispose()


app = FastAPI(title="Booking API", lifespan=lifespan)
app.include_router(router)
app.include_router(staff_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"ok": True}
