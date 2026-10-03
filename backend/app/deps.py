from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Tenant


async def get_tenant(x_api_key: str = Header(...), session: AsyncSession = Depends(get_session)) -> Tenant:
    tenant = await session.scalar(select(Tenant).where(Tenant.api_key == x_api_key))
    if not tenant:
        raise HTTPException(401, "bad api key")
    return tenant
