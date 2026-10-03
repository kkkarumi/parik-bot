import html

import httpx
from loguru import logger

from .config import settings


def esc(s) -> str:
    return html.escape(str(s or ""))


async def send(chat_id: int | None, text: str, reply_markup: dict | None = None) -> None:
    if not (settings.bot_token and chat_id):
        return
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"https://api.telegram.org/bot{settings.bot_token}/sendMessage", json=payload)
            r.raise_for_status()
    except Exception as e:  # уведомление не должно ломать основной сценарий
        logger.warning(f"telegram send failed chat={chat_id}: {e}")
