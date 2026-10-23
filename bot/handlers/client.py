"""Клиент: мои записи, отмена, кнопки из напоминаний, оценка визита, чек предоплаты."""
from telegram import Update
from telegram.ext import ContextTypes

from api_client import ApiError, api
from handlers.booking import payment_text
from handlers.common import get_role
from ui import Btn, ack, e, kb, main_menu, show, when


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    bookings = await api.get("/bookings", telegram_id=q.from_user.id)
    role = (await get_role(q.from_user.id))["role"]
    if not bookings:
        return await show(update, "🔍 Предстоящих записей нет.", main_menu(role))
    await show(update, f"🗂 <b>Ваши записи ({len(bookings)}):</b>")
    for b in bookings:
        if b["status"] == "pending_payment":
            await q.message.chat.send_message(
                payment_text(b), parse_mode="HTML",
                reply_markup=kb([Btn("❌ Отменить бронь", callback_data=f"cancel_id:{b['id']}")]))
        else:
            await q.message.chat.send_message(
                f"✂️ {e(b['service_name'])} — {b['price']}₽\n👤 {e(b['master_name'])}\n📅 {when(b['starts_at'])}",
                reply_markup=kb([Btn("❌ Отменить", callback_data=f"cancel_id:{b['id']}")]))
    await q.message.chat.send_message("Главное меню 👇", reply_markup=main_menu(role))


async def cancel_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    bid = q.data.split(":")[1]
    await q.message.edit_reply_markup(kb([Btn("Да, отменить", callback_data=f"cancel_yes:{bid}"),
                                          Btn("Нет, оставить", callback_data=f"cancel_no:{bid}")]))


async def cancel_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q, "Запись остаётся 👍")
    bid = q.data.split(":")[1]
    await q.message.edit_reply_markup(kb([Btn("❌ Отменить", callback_data=f"cancel_id:{bid}")]))


async def _cancel(update: Update, booking_id: str):
    q = update.callback_query
    try:
        b = await api.post(f"/bookings/{booking_id}/cancel", telegram_id=q.from_user.id)
    except ApiError as err:
        if err.status in (404, 409):
            return await show(update, "⚠️ Эта запись уже отменена или прошла.")
        raise
    await show(update, f"🗑 Запись на {when(b['starts_at'])} отменена. Мастер предупреждён.\n"
                       "Записаться на другое время: /start")


async def cancel_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update.callback_query)
    await _cancel(update, update.callback_query.data.split(":")[1])


# --- кнопки из напоминания (их присылает бэкенд) ---
async def reminder_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q, "Спасибо! Ждём вас 🙌")
    try:
        await api.post(f"/bookings/{q.data.split(':')[1]}/confirm", telegram_id=q.from_user.id)
        await q.message.edit_text(q.message.text_html + "\n\n✅ <b>Вы подтвердили визит</b>", parse_mode="HTML")
    except ApiError:
        await q.message.edit_text("⚠️ Эта запись уже неактуальна.")


async def reminder_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    bid = q.data.split(":")[1]
    await q.message.edit_reply_markup(kb([Btn("Да, отменить", callback_data=f"cancel_yes:{bid}"),
                                          Btn("Нет, приду", callback_data=f"rem_ok:{bid}")]))


# --- оценка после визита ---
async def rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    _, bid, n = q.data.split(":")
    try:
        await api.post(f"/bookings/{bid}/review", {"rating": int(n)}, telegram_id=q.from_user.id)
    except ApiError:
        return await q.message.edit_text("Оценка уже учтена. Спасибо! 🙏")
    if int(n) >= 4:
        text = f"Спасибо за {'⭐' * int(n)}! Будем рады видеть вас снова 🙌"
    else:
        text = "Спасибо за честность. Мы разберёмся и постараемся стать лучше 🙏"
    await q.message.edit_text(text, reply_markup=kb([Btn("📅 Записаться снова", callback_data="menu_book")]))


# --- чек о предоплате: клиент просто присылает фото или файл ---
async def receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.message
    if m.photo:
        file_id, kind = m.photo[-1].file_id, "photo"
    else:
        file_id, kind = m.document.file_id, "document"
    pending = [b for b in await api.get("/bookings", telegram_id=m.from_user.id) if b["status"] == "pending_payment"]
    if not pending:
        role = (await get_role(m.from_user.id))["role"]
        return await m.reply_text("Я принимаю только чеки о предоплате, а записей, ждущих оплату, у вас нет.",
                                  reply_markup=main_menu(role))
    b = pending[0]
    r = await api.post(f"/bookings/{b['id']}/receipt", {"file_id": file_id, "kind": kind}, telegram_id=m.from_user.id)
    if r.get("delivered"):
        await m.reply_text(f"📨 Чек отправлен администратору. Как только он подтвердит оплату, "
                           f"я пришлю подтверждение записи на {when(b['starts_at'])}.")
    else:
        salon = await api.get("/salon")
        await m.reply_text("⚠️ Не получилось передать чек администратору. Пожалуйста, позвоните нам"
                           + (f": {salon['phone']}" if salon.get("phone") else "."))
