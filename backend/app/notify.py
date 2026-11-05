"""Отправка сообщений в Telegram напрямую через Bot API (бэкенд не зависит от процесса бота).

Адрес Bot API берётся из TELEGRAM_API_BASE: по умолчанию api.telegram.org, а с сервера в РФ — релей.

Что возвращают send/send_file:
  True  — сообщение доставлено;
  False — временная проблема (нет связи, релей/Telegram недоступен, 5xx, 429, неверный адрес): можно повторить;
  None  — повторять бессмысленно (клиент заблокировал бота, чат не найден, нет chat_id).
"""
import html
import re
from urllib.parse import urlsplit

import httpx
from loguru import logger

from .config import settings

TIMEOUT = 10  # секунд на запрос к Telegram
_TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}")


def esc(s) -> str:
    return html.escape(str(s or ""))


def api_url(method: str) -> str:
    return f"{settings.telegram_api_base}/bot{settings.bot_token}/{method}"


def mask(text: str) -> str:
    """Токен бота и секрет релея не должны попадать в логи (они есть в URL запроса и в текстах ошибок httpx)."""
    if settings.bot_token:
        text = text.replace(settings.bot_token, "<token>")
    u = urlsplit(settings.telegram_api_base)
    if u.path.strip("/"):  # https://relay/SECRET → https://relay/<secret>
        text = text.replace(settings.telegram_api_base, f"{u.scheme}://{u.netloc}/<secret>")
    return _TOKEN_RE.sub("<token>", text)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT)


async def _call(method: str, payload: dict) -> bool | None:
    chat = payload.get("chat_id")
    if not chat:
        return None
    if not settings.bot_token:
        return False
    try:
        async with _client() as c:
            r = await c.post(api_url(method), json=payload)
    except httpx.HTTPError as e:  # уведомление не должно ломать основной сценарий
        logger.warning(f"telegram {method} chat={chat}: нет связи с Telegram ({type(e).__name__}: {mask(str(e))})")
        return False
    if r.status_code == 200:
        return True
    try:
        desc = r.json().get("description", "")
    except ValueError:
        desc = "ответ не от Telegram (релей?)"
    if r.status_code in (400, 403):  # бот заблокирован, чат не найден, кривой текст — повтор не поможет
        logger.warning(f"telegram {method} chat={chat}: {r.status_code} {mask(desc)}")
        return None
    logger.warning(f"telegram {method} chat={chat}: {r.status_code} {mask(desc)}")
    return False


async def send(chat_id: int | None, text: str, reply_markup: dict | None = None) -> bool | None:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await _call("sendMessage", payload)


async def send_file(chat_id: int | None, file_id: str, kind: str, caption: str,
                    reply_markup: dict | None = None) -> bool | None:
    method, field = ("sendPhoto", "photo") if kind == "photo" else ("sendDocument", "document")
    payload = {"chat_id": chat_id, field: file_id, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await _call(method, payload)
