"""Привязка Telegram-аккаунтов к салону/мастерам.
  python -m app.staff list
  python -m app.staff admin 123456789
  python -m app.staff master "Мастер 1" 123456789
Свой id боту можно узнать командой /myid."""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .db import SessionLocal  # noqa: E402
from .models import Master, Tenant  # noqa: E402


async def main(args: list[str]):
    async with SessionLocal() as s:
        t = await s.scalar(select(Tenant).where(Tenant.api_key == os.environ["TENANT_API_KEY"]))
        if not t:
            print("Салон не найден — сначала python -m app.seed")
            return
        masters = (await s.scalars(select(Master).where(Master.tenant_id == t.id))).all()
        if args[:1] == ["admin"]:
            t.admin_chat_id = int(args[1])
            await s.commit()
            print("admin_chat_id =", t.admin_chat_id)
        elif args[:1] == ["master"]:
            m = next((m for m in masters if m.name == args[1]), None)
            if not m:
                print("Нет такого мастера. Есть:", [m.name for m in masters])
                return
            m.telegram_chat_id = int(args[2])
            await s.commit()
            print(m.name, "->", m.telegram_chat_id)
        else:
            print("admin_chat_id:", t.admin_chat_id)
            for m in masters:
                print(f"master {m.name!r}: {m.telegram_chat_id}")


asyncio.run(main(sys.argv[1:]))
