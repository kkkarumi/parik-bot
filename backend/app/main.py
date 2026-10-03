from contextlib import asynccontextmanager

import sentry_sdk
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from sqlalchemy import text

from .api import router
from .config import settings
from .db import engine
from .models import Base
from .reminders import tick

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.run_sync(Base.metadata.create_all)  # TODO: заменить на Alembic до первого продакшена
    sched = AsyncIOScheduler()
    sched.add_job(tick, "interval", seconds=60, max_instances=1, coalesce=True)
    sched.start()
    yield
    sched.shutdown(wait=False)


app = FastAPI(title="Booking API", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health():
    return {"ok": True}
