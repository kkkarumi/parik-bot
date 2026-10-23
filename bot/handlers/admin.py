"""/admin — всё, что владелец салона настраивает сам: услуги, мастера, график, салон, предоплата,
статистика, поиск клиента, рассылка, ссылка и QR-код для клиентов."""
import asyncio
import io
import logging
import re
from datetime import date, datetime, timedelta

from telegram import Update
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import ContextTypes

import config
from api_client import ApiError, api
from handlers.common import ask, on_ask
from handlers.router import route, screen
from ui import WD, WD_FULL, Btn, day_label, e, kb, rows, show

log = logging.getLogger(__name__)


def _uid(update: Update) -> int:
    return update.effective_user.id


async def _a(update: Update, method: str, path: str, json=None, **params):
    """Запрос в админку от имени текущего пользователя."""
    return await api.request(method, path, json=json, telegram_id=_uid(update), **params)


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ask", None)
    await menu(update, context)


@screen("a:menu")
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        s = await _a(update, "GET", "/admin/salon")
    except ApiError as err:
        if err.status == 403:
            return await show(update, "⛔️ Админка доступна только администратору салона.")
        raise
    prepay = f"включена, {s['prepay_amount']}₽" if s["prepay_amount"] else "выключена"
    await show(update, f"⚙️ <b>Админка «{e(s['name'])}»</b>\n\nПредоплата: {prepay}", kb(
        [Btn("📋 Записи клиентов", callback_data="up:0"), Btn("📊 Статистика", callback_data="a:stats:30")],
        [Btn("✂️ Услуги и цены", callback_data="a:svcs"), Btn("👥 Мастера", callback_data="a:msts")],
        [Btn("🏠 Салон", callback_data="a:salon"), Btn("💳 Предоплата", callback_data="a:prepay")],
        [Btn("🔎 Найти клиента", callback_data="a:find"), Btn("📣 Рассылка", callback_data="a:bc")],
        [Btn("🔗 Ссылка и QR-код для клиентов", callback_data="a:link")]))


# ======================= услуги =======================
@screen("a:svcs")
async def services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = await _a(update, "GET", "/admin/services")
    btns = [Btn(f"{'' if s['is_active'] else '🙈 '}{s['name']} — {s['price']}₽ · {s['duration_min']} мин",
                callback_data=f"a:svc:{s['id']}") for s in items]
    text = "✂️ <b>Услуги</b>\n\nНажмите на услугу, чтобы изменить цену, длительность или скрыть её."
    if not items:
        text = "✂️ <b>Услуг пока нет.</b> Добавьте первую 👇"
    await show(update, text, kb(*rows(btns, 1), [Btn("➕ Добавить услугу", callback_data="a:svc_add")],
                                [Btn("🔙 Админка", callback_data="a:menu")]))


async def _service(update, sid) -> dict | None:
    return next((s for s in await _a(update, "GET", "/admin/services") if s["id"] == int(sid)), None)


@screen("a:svc")
async def service(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: str):
    s = await _service(update, sid)
    if not s:
        return await services(update, context)
    state = "показывается клиентам" if s["is_active"] else "🙈 скрыта от клиентов"
    await show(update, f"✂️ <b>{e(s['name'])}</b>\n\n💰 {s['price']}₽\n⏱ {s['duration_min']} мин\n{state}", kb(
        [Btn("✏️ Название", callback_data=f"a:svc_f:{sid}:name"),
         Btn("💰 Цена", callback_data=f"a:svc_f:{sid}:price"),
         Btn("⏱ Время", callback_data=f"a:svc_f:{sid}:duration_min")],
        [Btn("🙈 Скрыть" if s["is_active"] else "👁 Показать", callback_data=f"a:svc_tog:{sid}")],
        [Btn("🔙 К услугам", callback_data="a:svcs")]))


SVC_PROMPTS = {"name": "Новое название услуги:", "price": "Новая цена в рублях (число):",
               "duration_min": "Сколько минут длится услуга? (число, например 45)"}


@screen("a:svc_f")
async def service_field(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: str, field: str):
    await ask(update, context, "svc_field", SVC_PROMPTS[field], back=f"a:svc:{sid}", sid=sid, field=field)


def _int(text: str) -> int | None:
    m = re.fullmatch(r"\s*(\d{1,7})\s*(₽|р|руб\.?|мин\.?)?\s*", text.lower())
    return int(m.group(1)) if m else None


@on_ask("svc_field")
async def service_field_save(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    text = update.message.text.strip()
    value = text[:120] if a["field"] == "name" else _int(text)
    if value in (None, ""):
        return await ask(update, context, "svc_field", "⚠️ Нужно число. " + SVC_PROMPTS[a["field"]],
                         back=a["back"], sid=a["sid"], field=a["field"])
    try:
        await _a(update, "PATCH", f"/admin/services/{a['sid']}", {a["field"]: value})
    except ApiError as err:
        if err.status != 422:
            raise
        return await ask(update, context, "svc_field", "⚠️ Недопустимое значение. " + SVC_PROMPTS[a["field"]],
                         back=a["back"], sid=a["sid"], field=a["field"])
    await route(update, context, f"a:svc:{a['sid']}")


@screen("a:svc_tog")
async def service_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: str):
    s = await _service(update, sid)
    await _a(update, "PATCH", f"/admin/services/{sid}", {"is_active": not s["is_active"]})
    await service(update, context, sid)


@screen("a:svc_add")
async def service_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ask(update, context, "svc_add", "➕ <b>Новая услуга</b>\n\nКак она называется? Например: «Стрижка машинкой»",
              back="a:svcs", step="name")


@on_ask("svc_add")
async def service_add_step(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    text = update.message.text.strip()
    if a["step"] == "name":
        return await ask(update, context, "svc_add", f"«{e(text[:120])}» — сколько стоит? (число в рублях)",
                         back="a:svcs", step="price", name=text[:120])
    n = _int(text)
    if n is None:
        return await ask(update, context, "svc_add", "⚠️ Нужно число. Попробуйте ещё раз:", **{
            k: v for k, v in a.items() if k != "kind"})
    if a["step"] == "price":
        return await ask(update, context, "svc_add", "Сколько минут длится? (например 30, 45, 60)",
                         back="a:svcs", step="dur", name=a["name"], price=n)
    try:
        s = await _a(update, "POST", "/admin/services", {"name": a["name"], "price": a["price"], "duration_min": n})
    except ApiError as err:
        if err.status != 422:
            raise
        return await ask(update, context, "svc_add", "⚠️ Длительность — от 5 до 720 минут. Ещё раз:",
                         back="a:svcs", step="dur", name=a["name"], price=a["price"])
    await update.message.reply_text(f"✅ Услуга «{s['name']}» добавлена и назначена всем мастерам.")
    await route(update, context, f"a:svc:{s['id']}")


# ======================= мастера =======================
@screen("a:msts")
async def masters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = await _a(update, "GET", "/admin/masters")
    btns = [Btn(f"{'' if m['is_active'] else '🙈 '}{m['name']}{' 📱' if m['linked'] else ''}",
                callback_data=f"a:mst:{m['id']}") for m in items]
    await show(update, "👥 <b>Мастера</b>\n\n📱 — мастер подключён к боту и получает уведомления о записях.",
               kb(*rows(btns, 2), [Btn("➕ Добавить мастера", callback_data="a:mst_add")],
                  [Btn("🔙 Админка", callback_data="a:menu")]))


def _hours_line(day: dict) -> str:
    return ", ".join(f"{i['start']}–{i['end']}" for i in day["intervals"]) or "выходной"


@screen("a:mst")
async def master(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str):
    m = await _a(update, "GET", f"/admin/masters/{mid}")
    hours = await _a(update, "GET", f"/admin/masters/{mid}/hours")
    off = await _a(update, "GET", f"/admin/masters/{mid}/timeoff")
    svcs = {s["id"]: s["name"] for s in await _a(update, "GET", "/admin/services")}
    status = "работает" if m["is_active"] else "🙈 скрыт от клиентов"
    tg = "📱 подключён к боту" if m["linked"] else "не подключён к боту (не получает уведомления)"
    week = "\n".join(f"{WD[d['weekday']]}: {_hours_line(d)}" for d in hours)
    offs = ", ".join(f"{date.fromisoformat(x):%d.%m}" for x in off[:8]) or "нет"
    sv = ", ".join(svcs[i] for i in m["service_ids"] if i in svcs) or "не выбраны"
    await show(update, f"💇 <b>{e(m['name'])}</b> — {status}\n{tg}\n\n<b>График:</b>\n{week}\n\n"
                       f"<b>Выходные дни:</b> {offs}\n<b>Услуги:</b> {e(sv)}", kb(
        [Btn("🕒 График", callback_data=f"a:mh:{mid}"), Btn("🌴 Выходные", callback_data=f"a:mo:{mid}")],
        [Btn("✂️ Услуги мастера", callback_data=f"a:ms:{mid}"), Btn("✏️ Имя", callback_data=f"a:mname:{mid}")],
        [Btn("🔓 Отвязать Telegram", callback_data=f"a:munl:{mid}") if m["linked"]
         else Btn("📱 Подключить к боту", callback_data=f"a:minv:{mid}")],
        [Btn("🙈 Скрыть мастера" if m["is_active"] else "👁 Вернуть мастера", callback_data=f"a:mtog:{mid}")],
        [Btn("🔙 К мастерам", callback_data="a:msts")]))


@screen("a:mst_add")
async def master_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ask(update, context, "mst_add", "➕ Как зовут нового мастера? (так его увидят клиенты)", back="a:msts")


@on_ask("mst_add")
async def master_add_save(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    m = await _a(update, "POST", "/admin/masters", {"name": update.message.text.strip()[:80]})
    await update.message.reply_text(
        f"✅ Мастер {m['name']} добавлен: делает все услуги, график Пн–Сб 10:00–20:00.\n"
        "Поправьте график и услуги, если нужно, и подключите мастера к боту — тогда он будет получать "
        "уведомления о записях.")
    await route(update, context, f"a:mst:{m['id']}")


@screen("a:mname")
async def master_name(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str):
    await ask(update, context, "mst_name", "Новое имя мастера:", back=f"a:mst:{mid}", mid=mid)


@on_ask("mst_name")
async def master_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    await _a(update, "PATCH", f"/admin/masters/{a['mid']}", {"name": update.message.text.strip()[:80]})
    await route(update, context, f"a:mst:{a['mid']}")


@screen("a:mtog")
async def master_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str):
    m = await _a(update, "GET", f"/admin/masters/{mid}")
    await _a(update, "PATCH", f"/admin/masters/{mid}", {"is_active": not m["is_active"]})
    await master(update, context, mid)


@screen("a:minv")
async def master_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str):
    inv = await _a(update, "POST", f"/admin/masters/{mid}/invite")
    link = f"https://t.me/{context.bot.username}?start={inv['code']}"
    await show(update, "📱 <b>Ссылка для мастера</b>\n\nПерешлите её мастеру. Он откроет — и бот его узнает: "
                       "будет присылать новые записи, отмены и покажет расписание по /schedule.\n\n"
                       f"{link}\n\nСсылка одноразовая.", kb([Btn("🔙 К мастеру", callback_data=f"a:mst:{mid}")]))


@screen("a:munl")
async def master_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str):
    await _a(update, "POST", f"/admin/masters/{mid}/unlink")
    await master(update, context, mid)


# --- услуги мастера ---
@screen("a:ms")
async def master_services(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str):
    m = await _a(update, "GET", f"/admin/masters/{mid}")
    svcs = [s for s in await _a(update, "GET", "/admin/services") if s["is_active"]]
    btns = [Btn(f"{'✅' if s['id'] in m['service_ids'] else '▫️'} {s['name']}",
                callback_data=f"a:mst_s:{mid}:{s['id']}") for s in svcs]
    await show(update, f"✂️ <b>Что делает {e(m['name'])}?</b>\nНажмите, чтобы включить/выключить.",
               kb(*rows(btns, 1), [Btn("🔙 К мастеру", callback_data=f"a:mst:{mid}")]))


@screen("a:mst_s")
async def master_service_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str, sid: str):
    m = await _a(update, "GET", f"/admin/masters/{mid}")
    ids = set(m["service_ids"]) ^ {int(sid)}
    await _a(update, "PUT", f"/admin/masters/{mid}/services", {"service_ids": sorted(ids)})
    await master_services(update, context, mid)


# --- график ---
@screen("a:mh")
async def master_hours(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str):
    hours = await _a(update, "GET", f"/admin/masters/{mid}/hours")
    btns = [Btn(f"{WD[d['weekday']]}: {_hours_line(d)}", callback_data=f"a:mhd:{mid}:{d['weekday']}") for d in hours]
    await show(update, "🕒 <b>График работы</b>\nНажмите на день, чтобы изменить часы.", kb(
        *rows(btns, 1),
        [Btn("📋 Как в Пн — на Вт–Пт", callback_data=f"a:mhc:{mid}:weekdays")],
        [Btn("📋 Как в Пн — на все дни", callback_data=f"a:mhc:{mid}:all")],
        [Btn("🔙 К мастеру", callback_data=f"a:mst:{mid}")]))


@screen("a:mhd")
async def master_hours_day(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str, wd: str):
    await ask(update, context, "hours",
              f"🕒 Часы на <b>{WD_FULL[int(wd)]}</b>.\n\nПримеры:\n• <code>10-20</code>\n"
              "• <code>9:30-14:00, 15:00-19:00</code> (с перерывом)\n• <code>выходной</code>",
              back=f"a:mh:{mid}", mid=mid, wd=wd)


def parse_hours(text: str) -> list[dict] | None:
    t = text.lower().strip()
    if t in ("выходной", "вых", "нет", "-", "0"):
        return []
    out = []
    for part in re.split(r"[,;\n]+", t):
        m = re.fullmatch(r"\s*(\d{1,2})(?:[:.](\d{2}))?\s*[-–—]\s*(\d{1,2})(?:[:.](\d{2}))?\s*", part)
        if not m:
            return None
        h1, m1, h2, m2 = int(m[1]), int(m[2] or 0), int(m[3]), int(m[4] or 0)
        if h2 == 24 and m2 == 0:
            h2, m2 = 23, 59
        if not (0 <= h1 <= 23 and 0 <= h2 <= 23 and m1 < 60 and m2 < 60) or (h1, m1) >= (h2, m2):
            return None
        out.append({"start": f"{h1:02d}:{m1:02d}", "end": f"{h2:02d}:{m2:02d}"})
    return out


@on_ask("hours")
async def master_hours_save(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    intervals = parse_hours(update.message.text)
    err_text = "⚠️ Не понял формат. Напишите, например, <code>10-20</code> или <code>выходной</code>:"
    if intervals is None:
        return await ask(update, context, "hours", err_text, back=a["back"], mid=a["mid"], wd=a["wd"])
    try:
        await _a(update, "PUT", f"/admin/masters/{a['mid']}/hours", {"weekday": int(a["wd"]), "intervals": intervals})
    except ApiError as err:
        if err.status != 422:
            raise
        return await ask(update, context, "hours", "⚠️ Интервалы пересекаются. " + err_text,
                         back=a["back"], mid=a["mid"], wd=a["wd"])
    await route(update, context, f"a:mh:{a['mid']}")


@screen("a:mhc")
async def master_hours_copy(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str, scope: str):
    hours = await _a(update, "GET", f"/admin/masters/{mid}/hours")
    mon = hours[0]["intervals"]
    for wd in (range(1, 5) if scope == "weekdays" else range(1, 7)):
        await _a(update, "PUT", f"/admin/masters/{mid}/hours", {"weekday": wd, "intervals": mon})
    await master_hours(update, context, mid)


# --- выходные дни ---
@screen("a:mo")
async def master_off(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str):
    off = await _a(update, "GET", f"/admin/masters/{mid}/timeoff")
    btns = [Btn(f"❌ {day_label(date.fromisoformat(d))}", callback_data=f"a:mod:{mid}:{d}") for d in off]
    text = ("🌴 <b>Выходные дни</b> (отпуск, больничный, личные дела)\nВ эти дни клиенты не смогут "
            "записаться к мастеру. Нажмите на дату, чтобы убрать выходной.")
    await show(update, text, kb(*rows(btns, 2), [Btn("➕ Добавить выходной", callback_data=f"a:moa:{mid}:0")],
                                [Btn("🔙 К мастеру", callback_data=f"a:mst:{mid}")]))


@screen("a:moa")
async def master_off_pick(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str, page: str = "0"):
    p = int(page)
    start = datetime.now(config.TZ).date() + timedelta(days=14 * p)
    btns = [Btn(day_label(start + timedelta(days=i)), callback_data=f"a:moad:{mid}:{start + timedelta(days=i)}")
            for i in range(14)]
    nav = [Btn("◀ Раньше", callback_data=f"a:moa:{mid}:{p - 1}")] if p > 0 else []
    nav.append(Btn("Позже ▶", callback_data=f"a:moa:{mid}:{p + 1}"))
    await show(update, "Выберите день, когда мастер не работает:",
               kb(*rows(btns, 2), nav, [Btn("🔙 Назад", callback_data=f"a:mo:{mid}")]))


@screen("a:moad")
async def master_off_add(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str, day: str):
    r = await _a(update, "POST", f"/admin/masters/{mid}/timeoff", {"day": day})
    if r["bookings"]:
        lines = "\n".join(f"• {datetime.fromisoformat(b['starts_at']).astimezone(config.TZ):%H:%M} "
                          f"{e(b['client_name'])} · {e(b['service_name'])}" for b in r["bookings"])
        await show(update, f"🌴 Выходной на {day_label(date.fromisoformat(day))} добавлен.\n\n"
                           f"⚠️ На этот день уже есть записи — новых не будет, а эти отмените или перенесите "
                           f"(клиент получит уведомление):\n{lines}",
                   kb([Btn("📋 Открыть расписание дня", callback_data=f"sch:{day}")],
                      [Btn("🔙 К выходным", callback_data=f"a:mo:{mid}")]))
    else:
        await master_off(update, context, mid)


@screen("a:mod")
async def master_off_del(update: Update, context: ContextTypes.DEFAULT_TYPE, mid: str, day: str):
    await _a(update, "DELETE", f"/admin/masters/{mid}/timeoff/{day}")
    await master_off(update, context, mid)


# ======================= салон =======================
SALON_FIELDS = {
    "name": ("Название", "Как называется салон?"),
    "address": ("Адрес", "Адрес салона (клиенты увидят его в «Контактах» и в напоминании):"),
    "phone": ("Телефон", "Телефон для связи:"),
    "work_hours_text": ("Часы работы", "Часы работы одной строкой, например «Пн–Сб 10:00–20:00»:"),
    "instagram_url": ("Ссылка на работы", "Ссылка на Instagram/VK/Telegram-канал с работами:"),
    "welcome_text": ("Приветствие", "Текст приветствия, который клиент видит по /start:"),
}


@screen("a:salon")
async def salon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = await _a(update, "GET", "/admin/salon")
    lines = "\n".join(f"<b>{label}:</b> {e(s.get(k)) or '—'}" for k, (label, _) in SALON_FIELDS.items())
    btns = [Btn(f"✏️ {label}", callback_data=f"a:sal:{k}") for k, (label, _) in SALON_FIELDS.items()]
    await show(update, f"🏠 <b>Салон</b>\n\n{lines}", kb(
        *rows(btns, 2), [Btn("👑 Передать админку", callback_data="a:adm_inv")],
        [Btn("🔙 Админка", callback_data="a:menu")]))


@screen("a:sal")
async def salon_field(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str):
    hint = "" if field == "name" else "\n\nЧтобы очистить — отправьте «-»."
    await ask(update, context, "salon", SALON_FIELDS[field][1] + hint, back="a:salon", field=field)


@on_ask("salon")
async def salon_field_save(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    v = update.message.text.strip()
    try:
        await _a(update, "PATCH", "/admin/salon", {a["field"]: "" if v == "-" else v})
    except ApiError as err:
        if err.status != 422:
            raise
        return await ask(update, context, "salon", "⚠️ Слишком длинно. Покороче, пожалуйста:",
                         back="a:salon", field=a["field"])
    await route(update, context, "a:salon")


@screen("a:adm_inv")
async def admin_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inv = await _a(update, "POST", "/admin/salon/admin-invite")
    link = f"https://t.me/{context.bot.username}?start={inv['code']}"
    await show(update, "👑 <b>Передача админки</b>\n\nКто откроет эту ссылку, станет администратором салона, "
                       "а вы перестанете им быть. Ссылка одноразовая.\n\n" + link,
               kb([Btn("🔙 К салону", callback_data="a:salon")]))


# ======================= предоплата =======================
@screen("a:prepay")
async def prepay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = await _a(update, "GET", "/admin/salon")
    on = s["prepay_amount"] > 0
    text = ("💳 <b>Предоплата</b>\n\nЗащита от неявок: после записи клиент переводит предоплату и присылает "
            f"скрин чека в бот. Вы подтверждаете одной кнопкой. Если чек не пришёл за {config.PREPAY_TIMEOUT_MIN} "
            "минут — бронь снимается сама.\n\n"
            f"<b>Сейчас:</b> {'включена, ' + str(s['prepay_amount']) + '₽' if on else 'выключена'}\n"
            f"<b>Реквизиты:</b> {e(s.get('payment_details')) or '—'}")
    await show(update, text, kb(
        [Btn("💰 Сумма предоплаты", callback_data="a:pp:amount"), Btn("🏦 Реквизиты", callback_data="a:pp:details")],
        [Btn("⛔️ Выключить предоплату", callback_data="a:pp_off")] if on else None,
        [Btn("🔙 Админка", callback_data="a:menu")]))


@screen("a:pp")
async def prepay_field(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str):
    prompt = ("Сколько рублей брать предоплатой? Например <code>300</code>. «0» — выключить."
              if field == "amount" else
              "Куда переводить? Например:\n<code>Сбербанк, 2202 2000 0000 0000, Алим К.</code>\nили номер телефона для СБП.")
    await ask(update, context, "prepay", prompt, back="a:prepay", field=field)


@on_ask("prepay")
async def prepay_save(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    text = update.message.text.strip()
    if a["field"] == "amount":
        n = _int(text)
        if n is None:
            return await ask(update, context, "prepay", "⚠️ Нужно число, например 300:", back="a:prepay", field="amount")
        try:
            await _a(update, "PATCH", "/admin/salon", {"prepay_amount": n})
        except ApiError as err:
            if err.status != 422:
                raise
            return await ask(update, context, "prepay", "Сначала укажите реквизиты — куда переводить:",
                             back="a:prepay", field="details", then_amount=n)
    else:
        payload = {"payment_details": text[:1000]}
        if a.get("then_amount"):
            payload["prepay_amount"] = a["then_amount"]
        await _a(update, "PATCH", "/admin/salon", payload)
    await route(update, context, "a:prepay")


@screen("a:pp_off")
async def prepay_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _a(update, "PATCH", "/admin/salon", {"prepay_amount": 0})
    await prepay(update, context)


# ======================= статистика =======================
@screen("a:stats")
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE, days: str = "30"):
    st = await _a(update, "GET", "/admin/stats", days=int(days))
    rating = f"{st['avg_rating']} ⭐ ({st['reviews']} отз.)" if st["avg_rating"] else "отзывов пока нет"
    def top(items):
        return "\n".join(f"• {e(x['name'])}: {x['visits']} виз. · {x['revenue']}₽" for x in items) or "—"
    text = (f"📊 <b>Статистика за {st['days']} дн.</b>\n\n"
            f"Выручка: <b>{st['revenue']}₽</b>\n"
            f"Визитов: <b>{st['completed']}</b> из {st['bookings']} записей\n"
            f"Отмен: {st['cancelled']} · не пришли: {st['no_show']}\n"
            f"Новых клиентов: {st['new_clients']}\n"
            f"Рейтинг: {rating}\n"
            f"Впереди записей: {st['upcoming']}\n\n"
            f"<b>Мастера:</b>\n{top(st['by_master'])}\n\n<b>Услуги:</b>\n{top(st['by_service'])}")
    periods = [Btn(("• " if str(n) == days else "") + f"{n} дн.", callback_data=f"a:stats:{n}") for n in (7, 30, 90)]
    await show(update, text, kb(periods, [Btn("🔙 Админка", callback_data="a:menu")]))


# ======================= клиенты =======================
@screen("a:find")
async def find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ask(update, context, "find", "🔎 Введите имя, @username или последние цифры телефона:", back="a:menu")


@on_ask("find")
async def find_run(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    found = await _a(update, "GET", "/admin/clients/search", q=update.message.text.strip()[:60])
    if not found:
        return await show(update, "Никого не нашёл 🤷", kb([Btn("🔎 Искать ещё", callback_data="a:find")],
                                                         [Btn("🔙 Админка", callback_data="a:menu")]))
    btns = [Btn(f"{'⛔️ ' if c['is_blocked'] else ''}{c['name'] or 'Без имени'} · {c['phone'] or '—'}",
                callback_data=f"cl:{c['id']}:") for c in found]
    await show(update, f"Найдено: {len(found)}", kb(*rows(btns, 1), [Btn("🔙 Админка", callback_data="a:menu")]))


# ======================= рассылка =======================
@screen("a:bc")
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = len(await _a(update, "GET", "/admin/clients/ids"))
    await ask(update, context, "bc", f"📣 <b>Рассылка</b> — получат {n} клиентов.\n\nНапишите текст сообщения "
                                     "(акция, свободные окна, новости). Перед отправкой покажу превью.",
              back="a:menu")


@on_ask("bc")
async def broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, a: dict):
    context.user_data["bc_text"] = update.message.text_html[:3500]
    n = len(await _a(update, "GET", "/admin/clients/ids"))
    await update.message.reply_text("👀 <b>Так увидят клиенты:</b>", parse_mode="HTML")
    await update.message.reply_text(context.user_data["bc_text"], parse_mode="HTML",
                                    reply_markup=kb([Btn("📅 Записаться", callback_data="menu_book")]))
    await show(update, f"Отправить {n} клиентам?", kb(
        [Btn("✅ Отправить", callback_data="a:bc_go"), Btn("✖️ Отмена", callback_data="a:menu")]))


@screen("a:bc_go")
async def broadcast_go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = context.user_data.pop("bc_text", None)
    if not text:
        return await menu(update, context)
    ids = await _a(update, "GET", "/admin/clients/ids")
    await show(update, f"📤 Отправляю {len(ids)} клиентам…")
    ok = fail = 0
    markup = kb([Btn("📅 Записаться", callback_data="menu_book")])
    for chat_id in ids:
        for attempt in (1, 2):
            try:
                await context.bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
                ok += 1
            except RetryAfter as err:  # Telegram просит притормозить
                if attempt == 1:
                    await asyncio.sleep(err.retry_after if isinstance(err.retry_after, (int, float))
                                        else err.retry_after.total_seconds())
                    continue
                fail += 1
            except Forbidden:
                fail += 1  # клиент заблокировал бота
            except TelegramError as err:
                log.warning("broadcast to %s failed: %s", chat_id, err)
                fail += 1
            break
        await asyncio.sleep(0.05)  # не упираться в лимиты Telegram (~30 сообщений/сек)
    await show(update, f"✅ Рассылка завершена: доставлено {ok}, не доставлено {fail}.",
               kb([Btn("🔙 Админка", callback_data="a:menu")]), new=True)


# ======================= ссылка и QR =======================
@screen("a:link")
async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://t.me/{context.bot.username}"
    caption = (f"🔗 Ссылка на запись: {url}\n\nПоставьте её в Instagram, на 2ГИС и Яндекс Картах, "
               "а QR-код распечатайте и повесьте у зеркала или на кассе.")
    try:
        import qrcode
        img = qrcode.make(url, box_size=12, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await update.effective_chat.send_photo(buf, caption=caption,
                                               reply_markup=kb([Btn("🔙 Админка", callback_data="a:menu")]))
    except ImportError:
        await show(update, caption, kb([Btn("🔙 Админка", callback_data="a:menu")]))
