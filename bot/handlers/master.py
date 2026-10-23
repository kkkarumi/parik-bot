"""Кабинет мастера: что он видит после подключения к боту."""
from datetime import date, datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

import config
from api_client import ApiError, api
from handlers.router import screen
from ui import WD, Btn, day_label, e, hhmm, kb, main_menu, rows, show

HELP = (
    "<b>Что можно сделать:</b>\n"
    "• <b>📋 Мои записи</b> — все ваши клиенты на ближайшие дни. Нажмите на запись: можно "
    "<b>отменить</b> её (клиенту придёт извинение и предложение выбрать другое время), "
    "отметить «не пришёл» или открыть карточку клиента — история визитов и ваши заметки.\n"
    "• <b>🌴 Выходной</b> — заболели или нужен отгул? Отметьте день: клиенты не смогут на него "
    "записаться, администратор получит уведомление.\n"
    "• <b>🕒 Мой график</b> — ваши рабочие часы и услуги (меняет администратор).\n\n"
    "<b>Уведомления приходят сами:</b> новая запись, отмена, отзыв клиента после визита."
)


def _me_menu(with_admin: bool = False):
    return kb([Btn("📋 Мои записи", callback_data="up:0"), Btn("📅 По дням", callback_data="sch:today")],
              [Btn("🌴 Выходной / отгул", callback_data="me:off"), Btn("🕒 Мой график", callback_data="me:hours")],
              [Btn("⚙️ Админка", callback_data="a:menu")] if with_admin else None,
              [Btn("👤 Меню клиента", callback_data="me:client")])


@screen("me")
async def master_home(update: Update, context: ContextTypes.DEFAULT_TYPE, intro: str = ""):
    uid = update.effective_user.id
    try:
        me = await api.get("/staff/me", telegram_id=uid)
    except ApiError as err:
        if err.status == 403:
            return await show(update, "Кабинет мастера доступен только подключённым мастерам.",
                              main_menu(None))
        raise
    role = (await api.get("/staff/role", telegram_id=uid))["role"]
    head = f"{intro}\n\n" if intro else ""
    text = (f"{head}💇 <b>{e(me['name'])}</b> — мастер «{e(me['salon'])}»\n"
            f"Сегодня записей: <b>{me['today']}</b> · всего впереди: <b>{me['upcoming']}</b>\n\n{HELP}")
    await show(update, text, _me_menu(with_admin=role == "admin"))


@screen("me:client")
async def client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = main_menu(None)
    rows_ = [list(r) for r in m.inline_keyboard] + [[Btn("💇 Кабинет мастера", callback_data="me")]]
    await show(update, "Так бот видят клиенты 👇", kb(*rows_))


@screen("me:hours")
async def my_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await api.get("/staff/me", telegram_id=update.effective_user.id)
    week = "\n".join(f"{WD[d['weekday']]}: " + (", ".join(f"{i['start']}–{i['end']}" for i in d["intervals"])
                                                or "выходной") for d in me["hours"])
    off = ", ".join(f"{date.fromisoformat(x):%d.%m}" for x in me["days_off"]) or "нет"
    text = (f"🕒 <b>Мой график</b>\n\n{week}\n\n<b>Отмеченные выходные:</b> {off}\n"
            f"<b>Услуги:</b> {e(', '.join(me['services'])) or '—'}\n\n"
            "Постоянный график и список услуг меняет администратор. Разовый выходной можно отметить самому.")
    await show(update, text, kb([Btn("🌴 Выходной / отгул", callback_data="me:off")],
                                [Btn("🔙 Кабинет", callback_data="me")]))


@screen("me:off")
async def my_days_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await api.get("/staff/me", telegram_id=update.effective_user.id)
    btns = [Btn(f"❌ {day_label(date.fromisoformat(d))}", callback_data=f"me:offdel:{d}") for d in me["days_off"]]
    text = ("🌴 <b>Выходные и отгулы</b>\n\nВ отмеченные дни клиенты не смогут к вам записаться. "
            "Администратор получает уведомление.\n")
    text += "\nНажмите на дату, чтобы снова выйти на работу." if btns else "\nСейчас выходных не отмечено."
    await show(update, text, kb(*rows(btns, 2), [Btn("➕ Отметить выходной", callback_data="me:offpick:0")],
                                [Btn("🔙 Кабинет", callback_data="me")]))


@screen("me:offpick")
async def my_day_off_pick(update: Update, context: ContextTypes.DEFAULT_TYPE, page: str = "0"):
    p = max(0, int(page))
    start = datetime.now(config.TZ).date() + timedelta(days=14 * p)
    btns = [Btn(day_label(start + timedelta(days=i)), callback_data=f"me:offadd:{start + timedelta(days=i)}")
            for i in range(14)]
    nav = ([Btn("◀ Раньше", callback_data=f"me:offpick:{p - 1}")] if p > 0 else []) + \
        [Btn("Позже ▶", callback_data=f"me:offpick:{p + 1}")]
    await show(update, "Какой день вы не работаете?", kb(*rows(btns, 2), nav, [Btn("🔙 Назад", callback_data="me:off")]))


@screen("me:offadd")
async def my_day_off_add(update: Update, context: ContextTypes.DEFAULT_TYPE, day: str):
    r = await api.post("/staff/timeoff", {"day": day}, telegram_id=update.effective_user.id)
    d = date.fromisoformat(day)
    if not r["bookings"]:
        return await show(update, f"🌴 Выходной на {day_label(d)} отмечен, администратор в курсе.",
                          kb([Btn("🔙 К выходным", callback_data="me:off")], [Btn("🏠 Кабинет", callback_data="me")]))
    btns = [Btn(f"{hhmm(b['starts_at'])} · {b['client_name'] or '—'} · {b['service_name']}"[:60],
                callback_data=f"bk:{b['id']}:d") for b in r["bookings"]]
    await show(update, f"🌴 Выходной на {day_label(d)} отмечен — новых записей не будет.\n\n"
                       f"⚠️ <b>Но на этот день у вас уже есть записи ({len(btns)}).</b> Откройте каждую и "
                       "отмените — клиент получит извинение и сможет выбрать другое время. "
                       "Или договоритесь с клиентом сами и перенесите.",
               kb(*rows(btns, 1), [Btn("🔙 К выходным", callback_data="me:off")]))


@screen("me:offdel")
async def my_day_off_del(update: Update, context: ContextTypes.DEFAULT_TYPE, day: str):
    await api.delete(f"/staff/timeoff/{day}", telegram_id=update.effective_user.id)
    await my_days_off(update, context)

