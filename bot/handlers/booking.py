"""Запись клиента: услуга → мастер → день → время → телефон → подтверждение (→ предоплата)."""
import re
import warnings
from datetime import date

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
                          MessageHandler, filters)
from telegram.warnings import PTBUserWarning

import config
from api_client import ApiError, api
from handlers.common import get_role
from ui import Btn, ack, day_label, e, hhmm, kb, main_menu, rows, show, when

SERVICE, MASTER, DAY, SLOT, PHONE, CONFIRM = range(6)
CANCEL = [Btn("✖️ Отменить запись", callback_data="cancel_booking")]
FLOW_KEYS = ("services", "service", "masters", "master", "slots", "starts_at", "single_master")


async def _menu(update: Update, text: str):
    role = (await get_role(update.effective_user.id))["role"]
    await show(update, text, main_menu(role))


async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    context.user_data.pop("ask", None)
    for k in FLOW_KEYS + ("client",):
        context.user_data.pop(k, None)
    u = q.from_user
    context.user_data["client"] = await api.put(
        "/clients", {"telegram_id": u.id, "username": u.username, "name": u.full_name})
    return await show_services(update, context)


async def show_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update.callback_query)
    services = await api.get("/services")
    if not services:
        await _menu(update, "😔 Онлайн-запись пока не настроена. Позвоните нам — запишем вручную.")
        return ConversationHandler.END
    context.user_data["services"] = {s["id"]: s for s in services}
    btns = [Btn(f"{s['name']} — {s['price']}₽", callback_data=f"svc:{s['id']}") for s in services]
    await show(update, "✂️ <b>Выберите услугу:</b>", kb(*rows(btns, 1), CANCEL))
    return SERVICE


async def service_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    d = context.user_data
    if q.data.startswith("svc:"):
        sid = int(q.data.split(":")[1])
        if sid not in d.get("services", {}):
            return await show_services(update, context)
        d["service"] = d["services"][sid]
    masters = await api.get("/masters", service_id=d["service"]["id"])
    if not masters:
        await show(update, "Для этой услуги сейчас нет свободных мастеров.",
                   kb([Btn("🔙 Другая услуга", callback_data="back_services")], CANCEL))
        return SERVICE
    d["masters"] = {m["id"]: m for m in masters}
    if len(masters) == 1:  # выбирать не из кого — сразу к датам
        d["master"] = masters[0]
        d["single_master"] = True
        return await show_days(update, context)
    d["single_master"] = False
    btns = [Btn(m["name"], callback_data=f"mst:{m['id']}") for m in masters]
    await show(update, f"✂️ {e(d['service']['name'])}\n\n👤 <b>Выберите мастера:</b>",
               kb(*rows(btns, 2), [Btn("🔙 Назад", callback_data="back_services")], CANCEL))
    return MASTER


async def show_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    d = context.user_data
    if q.data.startswith("mst:"):
        mid = int(q.data.split(":")[1])
        if mid not in d.get("masters", {}):
            return await show_services(update, context)
        d["master"] = d["masters"][mid]
    days = await api.get("/days", master_id=d["master"]["id"], service_id=d["service"]["id"])
    back = Btn("🔙 Назад", callback_data="back_services" if d.get("single_master") else "back_masters")
    head = f"✂️ {e(d['service']['name'])} · 👤 {e(d['master']['name'])}\n\n"
    if not days:
        await show(update, head + "😔 В ближайшие две недели свободного времени нет. Выберите другого мастера "
                                  "или позвоните нам.", kb([back], CANCEL))
        return DAY
    btns = [Btn(day_label(date.fromisoformat(x["day"])), callback_data=f"day:{x['day']}") for x in days]
    await show(update, head + "📅 <b>Выберите дату:</b>", kb(*rows(btns, 2), [back], CANCEL))
    return DAY


async def day_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    d = context.user_data
    day = q.data.split(":", 1)[1]
    slots = await api.get("/slots", master_id=d["master"]["id"], service_id=d["service"]["id"], date=day)
    back = [Btn("🔙 Другая дата", callback_data="back_days")]
    if not slots:
        await show(update, "😔 На этот день время уже разобрали. Выберите другую дату.", kb(back, CANCEL))
        return DAY
    d["slots"] = {hhmm(s): s for s in slots}
    btns = [Btn(t, callback_data=f"slot:{t}") for t in d["slots"]]
    await show(update, f"📅 {day_label(date.fromisoformat(day))}\n\n🕒 <b>Выберите время:</b>",
               kb(*rows(btns, 4), back, CANCEL))
    return SLOT


async def slot_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    d = context.user_data
    t = q.data.split(":", 1)[1]
    if t not in d.get("slots", {}):
        return await show_days(update, context)
    d["starts_at"] = d["slots"][t]
    if d["client"].get("phone"):
        return await ask_confirm(update, context)
    await q.message.edit_reply_markup(None)
    d["awaiting_phone"] = True
    markup = ReplyKeyboardMarkup([[KeyboardButton("📱 Отправить мой номер", request_contact=True)]],
                                 resize_keyboard=True, one_time_keyboard=True)
    await q.message.chat.send_message("📱 Оставьте номер телефона, чтобы мастер мог связаться с вами.\n"
                                      "Нажмите кнопку ниже или напишите номер:", reply_markup=markup)
    return PHONE


def clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        return "+7" + digits
    if 10 <= len(digits) <= 15 and raw.strip().startswith("+"):
        return "+" + digits
    return None


async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.message
    phone = clean_phone(m.contact.phone_number if m.contact else (m.text or ""))
    if not phone:
        await m.reply_text("⚠️ Не похоже на номер телефона. Пример: +7 928 123-45-67")
        return PHONE
    context.user_data["client"] = await api.put("/clients", {"telegram_id": m.from_user.id, "phone": phone})
    context.user_data.pop("awaiting_phone", None)
    await m.reply_text("Номер сохранён ✅", reply_markup=ReplyKeyboardRemove())
    return await ask_confirm(update, context)


async def ask_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    salon = await api.get("/salon")
    prepay = (f"\n\n💳 Нужна предоплата <b>{salon['prepay_amount']}₽</b> — реквизиты пришлю после подтверждения."
              if salon.get("prepay_amount") else "")
    text = (f"📋 <b>Проверьте запись:</b>\n\n✂️ {e(d['service']['name'])} — {d['service']['price']}₽\n"
            f"👤 {e(d['master']['name'])}\n📅 {when(d['starts_at'])}\n📞 {e(d['client']['phone'])}{prepay}")
    await show(update, text, kb([Btn("✅ Всё верно, записаться", callback_data="confirm_yes")],
                                [Btn("🔙 Другое время", callback_data="back_days")], CANCEL),
               new=update.callback_query is None)
    return CONFIRM


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await ack(q)
    d = context.user_data
    try:
        b = await api.post("/bookings", {"client_id": d["client"]["id"], "master_id": d["master"]["id"],
                                         "service_id": d["service"]["id"], "starts_at": d["starts_at"]})
    except ApiError as err:
        if err.status == 409:
            await show(update, "⚠️ Это время только что заняли. Выберите другое 👇",
                       kb([Btn("📅 Выбрать время", callback_data="back_days")], CANCEL))
            return DAY
        if err.status == 429:
            await _menu(update, "⚠️ У вас уже несколько активных записей. Отмените ненужную в «Мои записи» "
                                "или дождитесь визита.")
            return ConversationHandler.END
        if err.status == 403:
            salon = await api.get("/salon")
            await _menu(update, "Онлайн-запись для вас недоступна. Позвоните нам"
                                + (f": {e(salon['phone'])}" if salon.get("phone") else "."))
            return ConversationHandler.END
        raise
    for k in ("services", "masters", "slots"):
        d.pop(k, None)
    if b["status"] == "pending_payment":
        await show(update, payment_text(b), kb([Btn("🗂 Мои записи", callback_data="menu_profile")]))
    else:
        await _menu(update, f"🎉 <b>Вы записаны!</b>\n\n✂️ {e(b['service_name'])}\n👤 {e(b['master_name'])}\n"
                            f"📅 {when(b['starts_at'])}\n\nНапомню за день и за 2 часа до визита. "
                            "Отменить можно в «Мои записи».")
    return ConversationHandler.END


def payment_text(b: dict) -> str:
    return (f"⏳ <b>Время забронировано — осталась предоплата {b['prepay_amount']}₽</b>\n\n"
            f"✂️ {e(b['service_name'])} · 👤 {e(b['master_name'])}\n📅 {when(b['starts_at'])}\n\n"
            f"<b>Куда перевести:</b>\n{e(b['payment_details'])}\n\n"
            f"📎 После перевода пришлите сюда <b>скриншот чека</b> (фото или файл). "
            f"Если чека не будет {config.PREPAY_TIMEOUT_MIN} минут, бронь снимется автоматически.")


async def _drop_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for k in FLOW_KEYS:
        context.user_data.pop(k, None)
    if context.user_data.pop("awaiting_phone", None):  # убрать кнопку «Отправить номер»
        await update.effective_chat.send_message("Запись прервана.", reply_markup=ReplyKeyboardRemove())


async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await ack(update.callback_query)
    await _drop_flow(update, context)
    await _menu(update, "Главное меню 👇")
    return ConversationHandler.END


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start посреди записи — выйти из диалога и показать меню."""
    await _drop_flow(update, context)
    from handlers.start import start_command
    await start_command(update, context)
    return ConversationHandler.END


async def timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for k in FLOW_KEYS:
        context.user_data.pop(k, None)
    context.user_data.pop("awaiting_phone", None)


def booking_handler() -> ConversationHandler:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PTBUserWarning)  # per_message=False — осознанно (есть шаг с текстом)
        return _build()


def _build() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_booking, pattern=r"^menu_book$")],
        states={
            SERVICE: [CallbackQueryHandler(service_selected, pattern=r"^svc:\d+$"),
                      CallbackQueryHandler(show_services, pattern=r"^back_services$")],
            MASTER: [CallbackQueryHandler(show_days, pattern=r"^mst:\d+$"),
                     CallbackQueryHandler(show_services, pattern=r"^back_services$")],
            DAY: [CallbackQueryHandler(day_selected, pattern=r"^day:\d{4}-\d{2}-\d{2}$"),
                  CallbackQueryHandler(service_selected, pattern=r"^back_masters$"),
                  CallbackQueryHandler(show_services, pattern=r"^back_services$"),
                  CallbackQueryHandler(show_days, pattern=r"^back_days$")],
            SLOT: [CallbackQueryHandler(slot_selected, pattern=r"^slot:\d{2}:\d{2}$"),
                   CallbackQueryHandler(show_days, pattern=r"^back_days$")],
            PHONE: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), phone_received)],
            CONFIRM: [CallbackQueryHandler(confirm_booking, pattern=r"^confirm_yes$"),
                      CallbackQueryHandler(show_days, pattern=r"^back_days$")],
            ConversationHandler.TIMEOUT: [CallbackQueryHandler(timeout), MessageHandler(filters.ALL, timeout)],
        },
        fallbacks=[CallbackQueryHandler(cancel_booking, pattern=r"^cancel_booking$"),
                   CommandHandler("cancel", cancel_booking),
                   CommandHandler("start", restart)],
        allow_reentry=True,
        conversation_timeout=20 * 60,
        name="booking",
        persistent=bool(config.STATE_FILE),
    )
