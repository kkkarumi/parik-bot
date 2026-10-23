"""Кто вызывает API.
Доступ к API в целом — по X-Api-Key (его знает только бот). Внутри — роль по telegram_id:
админ салона (tenants.admin_chat_id) или мастер (masters.telegram_chat_id)."""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Master, Tenant


async def get_tenant(x_api_key: str = Header(...), session: AsyncSession = Depends(get_session)) -> Tenant:
    tenant = await session.scalar(select(Tenant).where(Tenant.api_key == x_api_key))
    if not tenant:
        raise HTTPException(401, "bad api key")
    return tenant


@dataclass
class Staff:
    tenant: Tenant
    telegram_id: int
    is_admin: bool
    master: Master | None  # мастер, если этот telegram привязан к мастеру

    def can_manage(self, master_id: int) -> bool:
        return self.is_admin or (self.master is not None and self.master.id == master_id)


async def resolve_role(s: AsyncSession, t: Tenant, telegram_id: int) -> Staff:
    master = await s.scalar(select(Master).where(
        Master.tenant_id == t.id, Master.telegram_chat_id == telegram_id, Master.is_active))
    return Staff(t, telegram_id, t.admin_chat_id == telegram_id, master)


async def get_staff(telegram_id: int, t: Tenant = Depends(get_tenant),
                    s: AsyncSession = Depends(get_session)) -> Staff:
    st = await resolve_role(s, t, telegram_id)
    if not (st.is_admin or st.master):
        raise HTTPException(403, "not staff")
    return st


async def require_admin(telegram_id: int, t: Tenant = Depends(get_tenant)) -> Tenant:
    if t.admin_chat_id is None or t.admin_chat_id != telegram_id:
        raise HTTPException(403, "admin only")
    return t
