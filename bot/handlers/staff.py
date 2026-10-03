from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import httpx
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, Update
from telegram.ext import ContextTypes

import config
from api_client import api

TZ = ZoneInfo(config.TZ)
WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def hhmm(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(TZ).strftime("%H:%M")


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш Telegram ID: <code>{update.effective_user.id}</code>", parse_mode="HTML")


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
        day = date.fromisoformat(q.data.split(":", 1)[1])
    else:
        day = datetime.now(TZ).date()
    uid = update.effective_user.id
    try:
        items = await api.get("/staff/schedule", telegram_id=uid, day=day.isoformat())
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            text = "Эта команда только для мастеров и администратора."
            await (q.message.edit_text(text) if q else update.message.reply_text(text))
            return
        raise

    head = f"📋 <b>Записи на {day:%d.%m} ({WD[day.weekday()]})</b>\n"
    if items:
        lines = [
            f"\n🕒 <b>{hhmm(b['starts_at'])}–{hhmm(b['ends_at'])}</b> · {escape(b['master_name'])}\n"
            f"✂️ {escape(b['service_name'])} ({b['price']}₽)\n"
            f"👤 {escape(b['client_name'] or '—')} · <code>{escape(b['client_phone'] or '—')}</code>"
            for b in items]
        text = head + "".join(lines)
    else:
        text = head + "\nЗаписей нет."
    kb = Markup([[
        Btn("◀", callback_data=f"sch:{(day - timedelta(days=1)).isoformat()}"),
        Btn("Сегодня", callback_data=f"sch:{datetime.now(TZ).date().isoformat()}"),
        Btn("▶", callback_data=f"sch:{(day + timedelta(days=1)).isoformat()}"),
    ]])
    if q:
        await q.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
