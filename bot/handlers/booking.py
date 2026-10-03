import re
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import httpx
from telegram import (InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, KeyboardButton,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, Update)
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
                          MessageHandler, filters)

import config
from api_client import api
from handlers.start import main_menu

SERVICE, MASTER, DAY, SLOT, PHONE, CONFIRM = range(6)
WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
TZ = ZoneInfo(config.TZ)
CANCEL = [Btn("❌ Отмена", callback_data="cancel_booking")]


def fmt(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(TZ).strftime("%d.%m в %H:%M")


async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    u = q.from_user
    context.user_data["client"] = await api.put(
        "/clients", {"telegram_id": u.id, "username": u.username, "name": u.full_name})
    services = await api.get("/services")
    context.user_data["services"] = {s["id"]: s for s in services}
    kb = [[Btn(f"{s['name']} — {s['price']}₽", callback_data=f"svc:{s['id']}")] for s in services] + [CANCEL]
    await q.message.edit_text("✂️ Выберите услугу:", reply_markup=Markup(kb))
    return SERVICE


async def service_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sid = int(q.data.split(":")[1])
    context.user_data["service"] = context.user_data["services"][sid]
    masters = await api.get("/masters", service_id=sid)
    if not masters:
        await q.message.edit_text("Для этой услуги пока нет мастеров.", reply_markup=Markup([CANCEL]))
        return SERVICE
    context.user_data["masters"] = {m["id"]: m for m in masters}
    kb = [[Btn(m["name"], callback_data=f"mst:{m['id']}")] for m in masters] + [CANCEL]
    await q.message.edit_text("👤 Выберите мастера:", reply_markup=Markup(kb))
    return MASTER


async def show_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("mst:"):
        context.user_data["master"] = context.user_data["masters"][int(q.data.split(":")[1])]
    today = datetime.now(TZ).date()
    days = [today + timedelta(days=i) for i in range(7)]
    kb = [[Btn(f"{WD[d.weekday()]} {d:%d.%m}", callback_data=f"day:{d.isoformat()}")] for d in days] + [CANCEL]
    await q.message.edit_text("📅 Выберите дату:", reply_markup=Markup(kb))
    return DAY


async def day_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    day = q.data.split(":", 1)[1]
    d = context.user_data
    slots = await api.get("/slots", master_id=d["master"]["id"], service_id=d["service"]["id"], date=day)
    back = [Btn("🔙 Другая дата", callback_data="back_days")]
    if not slots:
        await q.message.edit_text("😔 На эту дату свободного времени нет.", reply_markup=Markup([back, CANCEL]))
        return DAY
    d["slots"] = {datetime.fromisoformat(s).astimezone(TZ).strftime("%H:%M"): s for s in slots}
    labels = list(d["slots"])
    kb = [[Btn(t, callback_data=f"slot:{t}") for t in labels[i:i + 3]] for i in range(0, len(labels), 3)]
    await q.message.edit_text("🕒 Выберите время:", reply_markup=Markup(kb + [back, CANCEL]))
    return SLOT


async def slot_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = context.user_data
    d["starts_at"] = d["slots"][q.data.split(":", 1)[1]]
    if d["client"].get("phone"):
        return await ask_confirm(q.message.chat, context)
    kb = ReplyKeyboardMarkup([[KeyboardButton("📱 Поделиться номером", request_contact=True)]],
                             resize_keyboard=True, one_time_keyboard=True)
    await q.message.chat.send_message("📱 Оставьте номер телефона — кнопкой ниже или текстом:", reply_markup=kb)
    return PHONE


async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.message
    phone = m.contact.phone_number if m.contact else m.text.strip()
    if not re.fullmatch(r"\+?[\d\s\-()]{7,18}", phone):
        await m.reply_text("⚠️ Не похоже на номер. Попробуйте ещё раз:")
        return PHONE
    u = m.from_user
    context.user_data["client"] = await api.put("/clients", {"telegram_id": u.id, "phone": phone})
    await m.reply_text("Номер принят ✅", reply_markup=ReplyKeyboardRemove())
    return await ask_confirm(m.chat, context)


async def ask_confirm(chat, context):
    d = context.user_data
    text = (f"📋 <b>Проверьте запись:</b>\n\n👤 {escape(d['master']['name'])}\n"
            f"✂️ {escape(d['service']['name'])} ({d['service']['price']}₽)\n"
            f"📅 {fmt(d['starts_at'])}\n📞 {escape(d['client']['phone'])}")
    kb = [[Btn("✅ Подтверждаю", callback_data="confirm_yes")], CANCEL]
    await chat.send_message(text, reply_markup=Markup(kb), parse_mode="HTML")
    return CONFIRM


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = context.user_data
    try:
        b = await api.post("/bookings", {"client_id": d["client"]["id"], "master_id": d["master"]["id"],
                                         "service_id": d["service"]["id"], "starts_at": d["starts_at"]})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            await q.message.edit_text("⚠️ Это время только что заняли. Выберите другое.", reply_markup=main_menu())
            return ConversationHandler.END
        raise
    await q.message.edit_text(
        f"🎉 Вы записаны!\n\n👤 {escape(b['master_name'])}\n📅 {fmt(b['starts_at'])}\n\n"
        "Напомню за 24 часа и за 2 часа до визита.", reply_markup=main_menu())
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
        await q.message.edit_text("Запись отменена.", reply_markup=main_menu())
    else:
        await update.message.reply_text("Запись отменена.", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("Главное меню:", reply_markup=main_menu())
    context.user_data.clear()
    return ConversationHandler.END


booking_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_booking, pattern=r"^menu_book$")],
    states={
        SERVICE: [CallbackQueryHandler(service_selected, pattern=r"^svc:\d+$")],
        MASTER: [CallbackQueryHandler(show_days, pattern=r"^mst:\d+$")],
        DAY: [CallbackQueryHandler(day_selected, pattern=r"^day:"),
              CallbackQueryHandler(show_days, pattern=r"^back_days$")],
        SLOT: [CallbackQueryHandler(slot_selected, pattern=r"^slot:"),
               CallbackQueryHandler(show_days, pattern=r"^back_days$")],
        PHONE: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), phone_received)],
        CONFIRM: [CallbackQueryHandler(confirm_booking, pattern=r"^confirm_yes$")],
    },
    fallbacks=[CallbackQueryHandler(cancel_booking, pattern=r"^cancel_booking$"),
               CommandHandler("cancel", cancel_booking)],
)
