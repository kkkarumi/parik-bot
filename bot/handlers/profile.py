from html import escape

import httpx
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, Update
from telegram.ext import ContextTypes

from api_client import api
from handlers.booking import fmt
from handlers.start import main_menu


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    bookings = await api.get("/bookings", telegram_id=q.from_user.id)
    if not bookings:
        await q.message.edit_text("🔍 Предстоящих записей нет.", reply_markup=main_menu())
        return
    await q.message.edit_text("🗂 Ваши записи:")
    for b in bookings:
        await q.message.chat.send_message(
            f"Запись №{b['id']}\n👤 {escape(b['master_name'])}\n✂️ {escape(b['service_name'])} ({b['price']}₽)\n"
            f"📅 {fmt(b['starts_at'])}",
            reply_markup=Markup([[Btn("❌ Отменить", callback_data=f"cancel_id:{b['id']}")]]))
    await q.message.chat.send_message("Главное меню:", reply_markup=main_menu())


async def _cancel(q, booking_id: int):
    try:
        await api.post(f"/bookings/{booking_id}/cancel", telegram_id=q.from_user.id)
        await q.message.edit_text("🗑 Запись отменена.")
    except httpx.HTTPStatusError:
        await q.message.edit_text("⚠️ Запись не найдена или уже отменена.")


async def cancel_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _cancel(q, int(q.data.split(":")[1]))


# --- кнопки из напоминаний и запроса отзыва (их шлёт бэкенд) ---
async def reminder_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    bid = int(q.data.split(":")[1])
    try:
        await api.post(f"/bookings/{bid}/confirm", telegram_id=q.from_user.id)
        await q.message.edit_text("✅ Отлично, ждём вас!")
    except httpx.HTTPStatusError:
        await q.message.edit_text("⚠️ Запись не найдена.")


async def reminder_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _cancel(q, int(q.data.split(":")[1]))


async def rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, bid, n = q.data.split(":")
    try:
        await api.post(f"/bookings/{bid}/review", {"rating": int(n)}, telegram_id=q.from_user.id)
    except httpx.HTTPStatusError:
        pass
    await q.message.edit_text("Спасибо за оценку! 🙏")
