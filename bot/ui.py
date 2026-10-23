"""Общие кирпичики интерфейса."""
from datetime import date, datetime
from html import escape

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import BadRequest

import config

WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WD_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
STATUS = {"pending_payment": "⏳ ждёт предоплату", "confirmed": "✅ подтверждена", "completed": "✔️ состоялась",
          "cancelled": "❌ отменена", "no_show": "🚫 не пришёл"}


def e(s) -> str:
    return escape(str(s or ""))


def dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(config.TZ)


def when(iso: str) -> str:
    d = dt(iso)
    return f"{WD[d.weekday()]} {d:%d.%m} в {d:%H:%M}"


def hhmm(iso: str) -> str:
    return dt(iso).strftime("%H:%M")


def day_label(d: date) -> str:
    today = datetime.now(config.TZ).date()
    if d == today:
        return f"Сегодня, {d:%d.%m}"
    if (d - today).days == 1:
        return f"Завтра, {d:%d.%m}"
    return f"{WD[d.weekday()]} {d:%d.%m}"


def rows(buttons: list, n: int) -> list[list]:
    return [buttons[i:i + n] for i in range(0, len(buttons), n)]


def kb(*rows_) -> Markup:
    return Markup([list(r) for r in rows_ if r])


def main_menu(role: str | None = None) -> Markup:
    r = [[Btn("📅 Записаться", callback_data="menu_book")],
         [Btn("🗂 Мои записи", callback_data="menu_profile"), Btn("💰 Прайс", callback_data="menu_price")],
         [Btn("📸 Наши работы", callback_data="menu_portfolio"), Btn("📞 Контакты", callback_data="menu_contacts")]]
    if role == "admin":
        r.append([Btn("⚙️ Админка", callback_data="a:menu")])
    elif role == "master":
        r.append([Btn("📋 Моё расписание", callback_data="sch:today")])
    return Markup(r)


async def ack(q, text: str | None = None, alert: bool = False):
    """Ответить на нажатие кнопки, не падая, если на него уже ответили."""
    try:
        await q.answer(text, show_alert=alert)
    except BadRequest:
        pass


async def show(update, text: str, markup=None, *, new: bool = False):
    """Отредактировать сообщение с кнопкой, а если нельзя (фото/старое/команда) — прислать новое."""
    q = update.callback_query
    if q and not new:
        try:
            return await q.message.edit_text(text, reply_markup=markup, parse_mode="HTML",
                                             disable_web_page_preview=True)
        except BadRequest as err:
            if "not modified" in str(err).lower():
                return q.message
    chat = update.effective_chat
    return await chat.send_message(text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
