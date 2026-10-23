import logging

from telegram import BotCommandScopeChat, Update
from telegram.ext import ContextTypes

from api_client import ApiError, api
from handlers.common import get_role
from ui import e, main_menu, show

log = logging.getLogger(__name__)

CLIENT_COMMANDS = [("start", "🏠 Главное меню")]
MASTER_COMMANDS = CLIENT_COMMANDS + [("schedule", "📋 Записи клиентов")]
ADMIN_COMMANDS = MASTER_COMMANDS + [("admin", "⚙️ Админка")]


async def set_staff_commands(bot, chat_id: int, role: str):
    try:
        await bot.set_my_commands(ADMIN_COMMANDS if role == "admin" else MASTER_COMMANDS,
                                  scope=BotCommandScopeChat(chat_id))
    except Exception as err:  # не критично
        log.warning("set_my_commands for %s failed: %s", chat_id, err)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ask", None)
    u = update.effective_user
    if context.args:  # глубокая ссылка: приглашение админа/мастера
        await _accept_invite(update, context, context.args[0])
    await api.put("/clients", {"telegram_id": u.id, "username": u.username, "name": u.full_name})
    salon = await api.get("/salon")
    role = (await get_role(u.id))["role"]
    text = e(salon.get("welcome_text")) or f"👋 Добро пожаловать в «{e(salon['name'])}»!\nВыберите, что вас интересует 👇"
    await show(update, text, main_menu(role))


async def _accept_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    if not (code.startswith("admin_") or code.startswith("m_")):
        return
    try:
        r = await api.post("/staff/link", {"code": code, "telegram_id": update.effective_user.id})
    except ApiError as err:
        if err.status == 404:
            await update.effective_chat.send_message(
                "⚠️ Ссылка-приглашение недействительна или уже использована. Попросите новую у администратора.")
            return
        raise
    await set_staff_commands(context.bot, update.effective_user.id, r["role"])
    if r["role"] == "admin":
        await update.effective_chat.send_message(
            f"👑 Готово! Вы — администратор «{e(r['name'])}».\n\n"
            "• /admin — настройки: услуги, цены, мастера, график, предоплата, статистика\n"
            "• /schedule — записи клиентов: отменить, посмотреть клиента\n\nСюда же будут приходить уведомления о новых записях и отменах.",
            parse_mode="HTML")
    else:
        await update.effective_chat.send_message(
            f"💇 Готово, {e(r['name'])}! Теперь сюда будут приходить ваши новые записи и отмены, "
            "а по /schedule — все ваши записи.", parse_mode="HTML")
