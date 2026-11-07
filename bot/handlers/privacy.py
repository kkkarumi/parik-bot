"""Персональные данные (152-ФЗ): /privacy — политика и дата согласия, /forget — отзыв согласия и удаление данных."""
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

import config
from api_client import ApiError, api
from handlers.common import get_role
from legal import render, salon_values
from ui import Btn, ack, kb, main_menu, show


async def _consent_line(telegram_id: int) -> str:
    try:
        me = await api.get("/clients/me", telegram_id=telegram_id)
    except ApiError as err:
        if err.status != 404:
            raise
        me = {}
    if me.get("consent_at"):
        when = datetime.fromisoformat(me["consent_at"]).astimezone(config.TZ)
        return f"✅ Согласие на обработку данных вы дали {when:%d.%m.%Y в %H:%M}."
    return "Согласие на обработку данных вы ещё не давали — бот спросит его перед первой записью."


async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /privacy и кнопка «🔒 Мои данные»."""
    if update.callback_query:
        await ack(update.callback_query)
    salon = await api.get("/salon")
    text = render("privacy.md", **salon_values(salon)) + "\n\n" + await _consent_line(update.effective_user.id)
    await show(update, text, kb([Btn("🗑 Удалить мои данные", callback_data="forget_ask")],
                                [Btn("🔙 Меню", callback_data="back_to_menu")]))


async def forget_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /forget и кнопка «Удалить мои данные»: сначала подтверждение."""
    if update.callback_query:
        await ack(update.callback_query)
    await show(update, "🗑 <b>Удалить ваши данные?</b>\n\n"
                       "• имя, телефон, username и заметки мастера будут стёрты;\n"
                       "• будущие записи отменятся, салон получит уведомление;\n"
                       "• история визитов останется у салона без ваших данных.\n\n"
                       "Это отзыв согласия на обработку данных. Отменить удаление нельзя.",
               kb([Btn("Да, удалить мои данные", callback_data="forget_yes")],
                  [Btn("Нет, оставить", callback_data="back_to_menu")]))


async def forget_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    r = await api.post("/clients/forget", telegram_id=q.from_user.id)
    context.user_data.clear()  # в состоянии бота (state.pickle) тоже лежали имя и телефон
    extra = f"\nОтменено будущих записей: {r['cancelled']}, салон предупреждён." if r.get("cancelled") else ""
    role = (await get_role(q.from_user.id))["role"]
    await show(update, f"✅ Ваши данные удалены.{extra}\n\n"
                       "Если захотите снова записаться — нажмите «📅 Записаться», бот заново спросит согласие.",
               main_menu(role))
