"""Отправка сообщений в Telegram напрямую через Bot API (бэкенд не зависит от процесса бота)."""
import html

import httpx
from loguru import logger

from .config import settings


def esc(s) -> str:
    return html.escape(str(s or ""))


async def _call(method: str, payload: dict) -> bool:
    if not (settings.bot_token and payload.get("chat_id")):
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"https://api.telegram.org/bot{settings.bot_token}/{method}", json=payload)
            r.raise_for_status()
        return True
    except Exception as e:  # уведомление не должно ломать основной сценарий
        logger.warning(f"telegram {method} failed chat={payload.get('chat_id')}: {e}")
        return False


async def send(chat_id: int | None, text: str, reply_markup: dict | None = None) -> bool:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await _call("sendMessage", payload)


async def send_file(chat_id: int | None, file_id: str, kind: str, caption: str,
                    reply_markup: dict | None = None) -> bool:
    method, field = ("sendPhoto", "photo") if kind == "photo" else ("sendDocument", "document")
    payload = {"chat_id": chat_id, field: file_id, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await _call(method, payload)
