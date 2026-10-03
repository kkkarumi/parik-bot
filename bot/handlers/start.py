from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from api_client import api


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Записаться", callback_data="menu_book")],
        [InlineKeyboardButton("💰 Прайс-лист", callback_data="menu_price")],
        [InlineKeyboardButton("🗂 Мои записи", callback_data="menu_profile")],
        [InlineKeyboardButton("📸 Портфолио", callback_data="menu_portfolio")],
        [InlineKeyboardButton("📞 Контакты", callback_data="menu_contacts")],
    ])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    salon = await api.get("/salon")
    text = salon.get("welcome_text") or f"👋 Добро пожаловать в «{salon['name']}»!\nВыберите пункт меню 👇"
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu())
    else:
        q = update.callback_query
        await q.answer()
        await q.message.edit_text(text, reply_markup=main_menu())
