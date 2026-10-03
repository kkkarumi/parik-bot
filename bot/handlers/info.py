from html import escape

from telegram import Update
from telegram.ext import ContextTypes

from api_client import api
from handlers.start import main_menu


async def show_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lines = [f"▪️ {escape(s['name'])} — {s['price']}₽ ({s['duration_min']} мин)" for s in await api.get("/services")]
    await q.message.edit_text("💰 <b>Прайс-лист:</b>\n\n" + "\n".join(lines), reply_markup=main_menu(), parse_mode="HTML")


async def show_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    salon = await api.get("/salon")
    url = salon.get("instagram_url")
    await q.message.edit_text(f"📸 Наши работы:\n👉 {url}" if url else "📸 Портфолио скоро появится.",
                              reply_markup=main_menu())


async def show_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    s = await api.get("/salon")
    parts = [f"📞 <b>{escape(s['name'])}</b>\n"]
    if s.get("address"):
        parts.append(f"📍 {escape(s['address'])}")
    if s.get("phone"):
        parts.append(f"📞 {escape(s['phone'])}")
    if s.get("work_hours_text"):
        parts.append(f"⏰ {escape(s['work_hours_text'])}")
    await q.message.edit_text("\n".join(parts), reply_markup=main_menu(), parse_mode="HTML")
