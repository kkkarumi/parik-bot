"""Один обработчик на все служебные кнопки: callback_data вида "a:svc:12" -> экран "a:svc" с аргументом "12".
Так любой экран можно открыть по строке (например, «назад» после отмены ввода)."""
from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

SCREENS: dict[str, Callable[..., Awaitable[None]]] = {}
PATTERN = r"^(a|sch|bk|bkc|bkcy|bkn|cl|cln|clb):"


def screen(key: str):
    def deco(fn):
        SCREENS[key] = fn
        return fn
    return deco


def _resolve(data: str):
    parts = data.split(":")
    if ":".join(parts[:2]) in SCREENS:
        return SCREENS[":".join(parts[:2])], parts[2:]
    if parts[0] in SCREENS:
        return SCREENS[parts[0]], parts[1:]
    return None, []


async def route(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    fn, args = _resolve(data)
    if fn:
        await fn(update, context, *args)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    fn, args = _resolve(q.data)
    if not fn:
        from handlers.common import stale_button
        return await stale_button(update, context)
    await q.answer()
    context.user_data.pop("ask", None)  # нажал другую кнопку — ввод больше не ждём
    await fn(update, context, *args)
