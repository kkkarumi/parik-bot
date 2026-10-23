"""Мастер и админ: список предстоящих записей, расписание по дням, карточка записи, карточка клиента."""
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
    await upcoming(update, context, "0")


PAGE = 10


def _back_home(role: str | None) -> Btn:
    return Btn("⚙️ Админка", callback_data="a:menu") if role == "admin" else Btn("🏠 Меню", callback_data="back_to_menu")


@screen("up")
async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE, page: str = "0", master_id: str = ""):
    """Все предстоящие записи одним списком: нажал — открыл карточку — отменил."""
    uid = update.effective_user.id
    params = {"telegram_id": uid, "limit": 100}
    if master_id:
        params["master_id"] = int(master_id)
    try:
        items = await api.get("/staff/upcoming", **params)
    except ApiError as err:
        if err.status == 403:
            return await show(update, "Этот раздел — для мастеров и администратора салона.")
        raise
    role = (await get_role(uid))["role"]
    p = max(0, min(int(page), max(0, (len(items) - 1) // PAGE)))
    chunk = items[p * PAGE:(p + 1) * PAGE]
    origin = f"u{p}" + (f"m{master_id}" if master_id else "")

    if not items:
        text = "📋 <b>Предстоящих записей нет.</b>"
    else:
        text = (f"📋 <b>Предстоящие записи: {len(items)}</b>\n"
                "Нажмите на запись — откроется карточка: там можно <b>отменить</b> запись "
                "(клиент получит уведомление) или посмотреть клиента.\n")
        last_day = None
        for b in chunk:
            d = dt(b["starts_at"]).date()
            if d != last_day:
                text += f"\n<b>{day_label(d)}</b>\n"
                last_day = d
            mark = " ⏳" if b["status"] == "pending_payment" else ""
            who = f" · {e(b['master_name'])}" if role == "admin" else ""
            text += (f"🕒 {hhmm(b['starts_at'])} {e(b['service_name'])} — {e(b['client_name'] or '—')}"
                     f"{who}{mark}\n")
    buttons = []
    for b in chunk:
        label = f"{dt(b['starts_at']):%d.%m} {hhmm(b['starts_at'])} · {b['client_name'] or '—'}"
        if role == "admin":
            label += f" · {b['master_name']}"
        buttons.append(Btn(label[:60], callback_data=f"bk:{b['id']}:{origin}"))
    suffix = f":{master_id}" if master_id else ""
    nav = []
    if p > 0:
        nav.append(Btn("◀ Раньше", callback_data=f"up:{p - 1}{suffix}"))
    if (p + 1) * PAGE < len(items):
        nav.append(Btn("Дальше ▶", callback_data=f"up:{p + 1}{suffix}"))
    filters_row = []
    if role == "admin":
        try:
            masters = [m for m in await api.get("/admin/masters", telegram_id=uid) if m["is_active"]]
        except ApiError:
            masters = []
        if len(masters) > 1:
            filters_row = [Btn(("• " if not master_id else "") + "Все", callback_data="up:0")] + [
                Btn(("• " if master_id == str(m["id"]) else "") + m["name"], callback_data=f"up:0:{m['id']}")
                for m in masters[:5]]
    await show(update, text, kb(*rows(buttons, 1), nav, filters_row,
                                [Btn("📅 По дням", callback_data="sch:today"), _back_home(role)]))


def _origin_back(origin: str, day: str) -> Btn:
    """Куда вернуться из карточки записи: в общий список (u<стр>[m<мастер>]) или в день."""
    if origin.startswith("u"):
        page, _, master = origin[1:].partition("m")
        return Btn("🔙 К списку записей", callback_data=f"up:{page or 0}" + (f":{master}" if master else ""))
    return Btn("🔙 К расписанию дня", callback_data=f"sch:{day}")


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
    else:
        text += "Нажмите на запись, чтобы отменить её или открыть карточку клиента.\n"
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
        buttons.append(Btn(label, callback_data=f"bk:{b['id']}:d"))
    nav = [Btn("◀", callback_data=f"sch:{d - timedelta(days=1)}"),
           Btn("Сегодня", callback_data="sch:today"),
           Btn("▶", callback_data=f"sch:{d + timedelta(days=1)}")]
    await show(update, text, kb(*rows(buttons, 1), nav,
                                [Btn("🗂 Все предстоящие", callback_data="up:0"), _back_home(role)]))


@screen("bk")
async def booking_card(update: Update, context: ContextTypes.DEFAULT_TYPE, bid: str, origin: str = "d"):
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
        [Btn("❌ Отменить запись", callback_data=f"bkc:{b['id']}:{origin}")]
        if b["status"] in ("pending_payment", "confirmed") and not started else None,
        [Btn("🚫 Клиент не пришёл", callback_data=f"bkn:{b['id']}:{origin}")]
        if b["status"] in ("confirmed", "completed") and started else None,
        [Btn("👤 Карточка клиента", callback_data=f"cl:{b['client_id']}:{b['id']}:{origin}")],
        [_origin_back(origin, day)]))


@screen("bkc")
async def booking_cancel_ask(update: Update, context: ContextTypes.DEFAULT_TYPE, bid: str, origin: str = "d"):
    await show(update, "Отменить запись? Клиент получит уведомление и сможет выбрать другое время.",
               kb([Btn("Да, отменить", callback_data=f"bkcy:{bid}:{origin}"),
                   Btn("Нет", callback_data=f"bk:{bid}:{origin}")]))


@screen("bkcy")
async def booking_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, bid: str, origin: str = "d"):
    try:
        b = await api.post(f"/staff/bookings/{bid}/cancel", telegram_id=update.effective_user.id)
    except ApiError as err:
        if err.status in (404, 409):
            return await show(update, "Эту запись уже нельзя отменить.",
                              kb([Btn("🔙", callback_data=f"bk:{bid}:{origin}")]))
        raise
    day = dt(b["starts_at"]).date().isoformat()
    await show(update, f"🗑 Запись на {when(b['starts_at'])} ({e(b['client_name'])}) отменена, клиент уведомлён.",
               kb([_origin_back(origin, day)]))


@screen("bkn")
async def booking_no_show(update: Update, context: ContextTypes.DEFAULT_TYPE, bid: str, origin: str = "d"):
    try:
        await api.post(f"/staff/bookings/{bid}/no_show", telegram_id=update.effective_user.id)
    except ApiError as err:
        if err.status not in (404, 409):
            raise
    await booking_card(update, context, bid, origin)


@screen("cl")
async def client_card(update: Update, context: ContextTypes.DEFAULT_TYPE, cid: str, back_bid: str = "",
                      origin: str = "d"):
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
    tail = f"{back_bid}:{origin}"
    back = f"bk:{back_bid}:{origin}" if back_bid else ("a:menu" if is_admin else "up:0")
    await show(update, text, kb(
        [Btn("📝 Заметка", callback_data=f"cln:{cid}:{tail}")],
        [Btn("✅ Разблокировать" if c["is_blocked"] else "⛔️ Заблокировать",
             callback_data=f"clb:{cid}:{0 if c['is_blocked'] else 1}:{tail}")] if is_admin else None,
        [Btn("💬 Написать в Telegram", url=f"https://t.me/{c['username']}")] if c.get("username") else None,
        [Btn("🔙 Назад", callback_data=back)]))


@screen("cln")
async def client_note_ask(update: Update, context: ContextTypes.DEFAULT_TYPE, cid: str, back_bid: str = "",
                          origin: str = "d"):
    await ask(update, context, "client_note",
              "📝 Напишите заметку о клиенте (предпочтения, особенности).\nЧтобы удалить заметку — отправьте «-».",
              back=f"cl:{cid}:{back_bid}:{origin}", cid=cid, back_bid=back_bid, origin=origin)


@on_ask("client_note")
async def client_note_save(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    note = update.message.text.strip()
    await api.patch(f"/staff/clients/{a['cid']}", {"notes": "" if note == "-" else note[:2000]},
                    telegram_id=update.effective_user.id)
    await update.message.reply_text("Заметка сохранена ✅")
    await route(update, context, f"cl:{a['cid']}:{a['back_bid']}:{a.get('origin', 'd')}")


@screen("clb")
async def client_block(update: Update, context: ContextTypes.DEFAULT_TYPE, cid: str, flag: str, back_bid: str = "",
                       origin: str = "d"):
    await api.patch(f"/staff/clients/{cid}", {"is_blocked": flag == "1"}, telegram_id=update.effective_user.id)
    await client_card(update, context, cid, back_bid, origin)
