"""Мастер и админ: расписание по дням, карточка записи, карточка клиента."""
from datetime import date, datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

import config
from api_client import ApiError, api
from handlers.common import ask, get_role, on_ask
from handlers.router import route, screen
from ui import STATUS, WD, Btn, day_label, dt, e, hhmm, kb, rows, show, when


def _today() -> date:
    return datetime.now(config.TZ).date()


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш Telegram ID: <code>{update.effective_user.id}</code>", parse_mode="HTML")


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ask", None)
    await schedule(update, context, "today")


@screen("sch")
async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, day: str = "today"):
    uid = update.effective_user.id
    d = _today() if day == "today" else date.fromisoformat(day)
    try:
        items = await api.get("/staff/schedule", telegram_id=uid, day=d.isoformat())
    except ApiError as err:
        if err.status == 403:
            return await show(update, "Эта команда — для мастеров и администратора салона.")
        raise
    role = (await get_role(uid))["role"]

    text = f"📋 <b>{day_label(d)}</b> ({WD[d.weekday()]})\n"
    if not items:
        text += "\nЗаписей нет."
    buttons = []
    for b in items:
        mark = "" if b["status"] == "confirmed" else f" · {STATUS[b['status']]}"
        who = role == "admin" and f" · {e(b['master_name'])}" or ""
        text += (f"\n🕒 <b>{hhmm(b['starts_at'])}–{hhmm(b['ends_at'])}</b>{who}{mark}\n"
                 f"✂️ {e(b['service_name'])} · {b['price']}₽\n"
                 f"👤 {e(b['client_name'] or '—')} · <code>{e(b['client_phone'] or '—')}</code>\n")
        label = f"{hhmm(b['starts_at'])} {b['client_name'] or ''}"[:30]
        if role == "admin":
            label += f" · {b['master_name']}"[:20]
        buttons.append(Btn(label, callback_data=f"bk:{b['id']}"))
    nav = [Btn("◀", callback_data=f"sch:{d - timedelta(days=1)}"),
           Btn("Сегодня", callback_data="sch:today"),
           Btn("▶", callback_data=f"sch:{d + timedelta(days=1)}")]
    extra = [Btn("⚙️ Админка", callback_data="a:menu")] if role == "admin" else []
    await show(update, text, kb(*rows(buttons, 1), nav, extra))


@screen("bk")
async def booking_card(update: Update, context: ContextTypes.DEFAULT_TYPE, bid: str):
    uid = update.effective_user.id
    try:
        b = await api.get(f"/staff/bookings/{bid}", telegram_id=uid)
    except ApiError as err:
        if err.status in (403, 404):
            return await show(update, "Запись не найдена.")
        raise
    started = dt(b["starts_at"]) <= datetime.now(config.TZ)
    user = f" (@{e(b['client_username'])})" if b.get("client_username") else ""
    text = (f"<b>Запись №{b['id']}</b> — {STATUS[b['status']]}\n\n"
            f"📅 {when(b['starts_at'])}–{hhmm(b['ends_at'])}\n💇 {e(b['master_name'])}\n"
            f"✂️ {e(b['service_name'])} · {b['price']}₽\n"
            f"👤 {e(b['client_name'] or '—')}{user}\n📞 <code>{e(b['client_phone'] or '—')}</code>")
    day = dt(b["starts_at"]).date().isoformat()
    await show(update, text, kb(
        [Btn("👤 Карточка клиента", callback_data=f"cl:{b['client_id']}:{b['id']}")],
        [Btn("❌ Отменить запись", callback_data=f"bkc:{b['id']}")]
        if b["status"] in ("pending_payment", "confirmed") and not started else None,
        [Btn("🚫 Клиент не пришёл", callback_data=f"bkn:{b['id']}")]
        if b["status"] in ("confirmed", "completed") and started else None,
        [Btn("🔙 К расписанию", callback_data=f"sch:{day}")]))


@screen("bkc")
async def booking_cancel_ask(update: Update, context: ContextTypes.DEFAULT_TYPE, bid: str):
    await show(update, "Отменить запись? Клиент получит уведомление и сможет выбрать другое время.",
               kb([Btn("Да, отменить", callback_data=f"bkcy:{bid}"), Btn("Нет", callback_data=f"bk:{bid}")]))


@screen("bkcy")
async def booking_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, bid: str):
    try:
        b = await api.post(f"/staff/bookings/{bid}/cancel", telegram_id=update.effective_user.id)
    except ApiError as err:
        if err.status in (404, 409):
            return await show(update, "Эту запись уже нельзя отменить.", kb([Btn("🔙", callback_data=f"bk:{bid}")]))
        raise
    day = dt(b["starts_at"]).date().isoformat()
    await show(update, f"🗑 Запись на {when(b['starts_at'])} отменена, клиент уведомлён.",
               kb([Btn("🔙 К расписанию", callback_data=f"sch:{day}")]))


@screen("bkn")
async def booking_no_show(update: Update, context: ContextTypes.DEFAULT_TYPE, bid: str):
    try:
        await api.post(f"/staff/bookings/{bid}/no_show", telegram_id=update.effective_user.id)
    except ApiError as err:
        if err.status not in (404, 409):
            raise
    await booking_card(update, context, bid)


@screen("cl")
async def client_card(update: Update, context: ContextTypes.DEFAULT_TYPE, cid: str, back_bid: str = ""):
    uid = update.effective_user.id
    try:
        c = await api.get(f"/staff/clients/{cid}", telegram_id=uid)
    except ApiError as err:
        if err.status in (403, 404):
            return await show(update, "Клиент не найден.")
        raise
    is_admin = (await get_role(uid))["role"] == "admin"
    user = f" · @{e(c['username'])}" if c.get("username") else ""
    blocked = "\n⛔️ <b>Заблокирован</b> — не может записываться через бота" if c["is_blocked"] else ""
    text = (f"👤 <b>{e(c['name'] or 'Без имени')}</b>{user}\n📞 <code>{e(c['phone'] or '—')}</code>{blocked}\n\n"
            f"Визитов: <b>{c['visits']}</b> · потрачено: <b>{c['spent']}₽</b>\n"
            f"Не пришёл: {c['no_shows']} · отмен: {c['cancelled']}\n")
    if c.get("notes"):
        text += f"\n📝 {e(c['notes'])}\n"
    if c["history"]:
        text += "\n<b>Последние записи:</b>\n" + "\n".join(
            f"• {dt(b['starts_at']):%d.%m.%y} {e(b['service_name'])} ({e(b['master_name'])}) — {STATUS[b['status']]}"
            for b in c["history"][:7])
    back = f"bk:{back_bid}" if back_bid else ("a:menu" if is_admin else "sch:today")
    await show(update, text, kb(
        [Btn("📝 Заметка", callback_data=f"cln:{cid}:{back_bid}")],
        [Btn("✅ Разблокировать" if c["is_blocked"] else "⛔️ Заблокировать",
             callback_data=f"clb:{cid}:{0 if c['is_blocked'] else 1}:{back_bid}")] if is_admin else None,
        [Btn("💬 Написать в Telegram", url=f"https://t.me/{c['username']}")] if c.get("username") else None,
        [Btn("🔙 Назад", callback_data=back)]))


@screen("cln")
async def client_note_ask(update: Update, context: ContextTypes.DEFAULT_TYPE, cid: str, back_bid: str = ""):
    await ask(update, context, "client_note",
              "📝 Напишите заметку о клиенте (предпочтения, особенности).\nЧтобы удалить заметку — отправьте «-».",
              back=f"cl:{cid}:{back_bid}", cid=cid, back_bid=back_bid)


@on_ask("client_note")
async def client_note_save(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    note = update.message.text.strip()
    await api.patch(f"/staff/clients/{a['cid']}", {"notes": "" if note == "-" else note[:2000]},
                    telegram_id=update.effective_user.id)
    await update.message.reply_text("Заметка сохранена ✅")
    await route(update, context, f"cl:{a['cid']}:{a['back_bid']}")


@screen("clb")
async def client_block(update: Update, context: ContextTypes.DEFAULT_TYPE, cid: str, flag: str, back_bid: str = ""):
    await api.patch(f"/staff/clients/{cid}", {"is_blocked": flag == "1"}, telegram_id=update.effective_user.id)
    await client_card(update, context, cid, back_bid)
