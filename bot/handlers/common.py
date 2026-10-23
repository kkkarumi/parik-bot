"""Ожидание текстового ввода, роли, обработка ошибок и «протухших» кнопок."""
import logging
import time
from collections.abc import Awaitable, Callable

import httpx
from telegram import Update
from telegram.error import Conflict, NetworkError
from telegram.ext import ContextTypes

from api_client import ApiError, api
from ui import Btn, kb, main_menu, show

log = logging.getLogger(__name__)

# kind -> handler(update, context, data) ; регистрируются модулями admin/staff
ASK_HANDLERS: dict[str, Callable[[Update, ContextTypes.DEFAULT_TYPE, dict], Awaitable[None]]] = {}


def on_ask(kind: str):
    def deco(fn):
        ASK_HANDLERS[kind] = fn
        return fn
    return deco


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, prompt: str,
              back: str = "a:menu", **data):
    """Попросить ввести текст. Следующее текстовое сообщение уйдёт в обработчик kind."""
    context.user_data["ask"] = {"kind": kind, "back": back, **data}
    await show(update, prompt, kb([Btn("✖️ Отмена", callback_data=f"ask_cancel:{back}")]))


async def ask_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data.pop("ask", None)
    back = q.data.split(":", 1)[1]
    await q.answer("Отменено")
    # вернуться на экран, откуда спрашивали
    from handlers.router import route
    await route(update, context, back)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = context.user_data.pop("ask", None)
    if a and a["kind"] in ASK_HANDLERS:
        await ASK_HANDLERS[a["kind"]](update, context, a)
        return
    role = await get_role(update.effective_user.id)
    await update.message.reply_text("Выберите действие в меню 👇", reply_markup=main_menu(role["role"]))


async def get_role(telegram_id: int) -> dict:
    try:
        return await api.get("/staff/role", telegram_id=telegram_id)
    except Exception:
        return {"role": None}


async def stale_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Эта кнопка уже не работает — вот актуальное меню", show_alert=False)
    role = await get_role(q.from_user.id)
    await show(update, "Главное меню 👇", main_menu(role["role"]), new=True)


CONFLICT_HINT = (
    "\n⚠️  Этот BOT_TOKEN уже использует ДРУГОЙ запущенный бот — Telegram отдаёт сообщения то ему, то нам.\n"
    "    Остановите другой экземпляр (старый скрипт в PyCharm/терминале, сервер, другой компьютер).\n"
    "    Не находится — в @BotFather: /revoke → новый токен в .env → перезапуск.\n")
_last_warn: dict[str, float] = {}


def _warn_once(key: str, message: str, every: float = 300) -> None:
    """Не засорять лог одинаковыми ошибками: одна строка раз в every секунд."""
    now = time.monotonic()
    if now - _last_warn.get(key, -every) >= every:
        _last_warn[key] = now
        log.error(message)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    if update is None and isinstance(err, Conflict):
        return _warn_once("conflict", CONFLICT_HINT)
    if update is None and isinstance(err, NetworkError):  # пропал интернет — PTB сам переподключится
        return _warn_once("network", f"Нет связи с Telegram ({err}). Жду и переподключаюсь…", every=60)
    if isinstance(err, (httpx.TransportError, ApiError)) and not (isinstance(err, ApiError) and err.status < 500):
        text = "😔 Сервис записи временно недоступен. Попробуйте через пару минут."
        log.warning("api problem: %r", err)
    else:
        text = "😔 Что-то пошло не так. Попробуйте ещё раз: /start"
        log.exception("unhandled error", exc_info=err)
    if isinstance(update, Update) and update.effective_chat:
        try:
            if update.callback_query:
                await update.callback_query.answer()
            await update.effective_chat.send_message(text)
        except Exception:
            pass
