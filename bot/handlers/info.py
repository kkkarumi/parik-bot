from telegram import Update
from telegram.ext import ContextTypes

from api_client import api
from ui import Btn, e, kb, show


def _back():
    return kb([Btn("📅 Записаться", callback_data="menu_book")], [Btn("🔙 Меню", callback_data="back_to_menu")])


async def show_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    services = await api.get("/services")
    lines = [f"▪️ {e(s['name'])} — <b>{s['price']}₽</b> · {s['duration_min']} мин" for s in services]
    await show(update, "💰 <b>Прайс-лист</b>\n\n" + ("\n".join(lines) or "Скоро здесь появятся услуги."), _back())


async def show_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    url = (await api.get("/salon")).get("instagram_url")
    await show(update, f"📸 Наши работы:\n👉 {e(url)}" if url else "📸 Портфолио скоро появится.", _back())


async def show_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    s = await api.get("/salon")
    parts = [f"<b>{e(s['name'])}</b>\n"]
    if s.get("address"):
        parts.append(f"📍 {e(s['address'])}")
    if s.get("phone"):
        parts.append(f"📞 {e(s['phone'])}")
    if s.get("work_hours_text"):
        parts.append(f"⏰ {e(s['work_hours_text'])}")
    if s.get("instagram_url"):
        parts.append(f"📸 {e(s['instagram_url'])}")
    await show(update, "\n".join(parts), _back())


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    from handlers.start import start_command
    context.args = []
    await start_command(update, context)
