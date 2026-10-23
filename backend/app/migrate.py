"""Применение миграций при старте. Базы, созданные старой версией через create_all
(без таблицы alembic_version), сначала помечаются как 0001, потом догоняются до head."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from loguru import logger
from sqlalchemy import inspect

from .db import engine

BACKEND = Path(__file__).resolve().parents[1]


def _config(connection) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


def _upgrade(connection) -> None:
    cfg = _config(connection)
    insp = inspect(connection)
    if insp.has_table("tenants") and not insp.has_table("alembic_version"):
        logger.info("legacy database without alembic_version: stamping 0001")
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")


async def upgrade_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_upgrade)
