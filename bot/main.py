import asyncio
import logging
from urllib.parse import urlsplit

from telegram import BotCommandScopeDefault, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, MessageHandler, PicklePersistence,
                          filters)
from telegram.request import BaseRequest

import config
from api_client import api
from handlers import admin, master, staff  # noqa: F401  (регистрируют экраны в router)
from handlers.booking import booking_handler
from handlers.client import (cancel_ask, cancel_no, cancel_yes, rate, receipt, reminder_cancel, reminder_ok,
                             show_profile)
from handlers.common import ask_cancel, on_error, on_text, stale_button
from handlers.info import back_to_menu, show_contacts, show_portfolio, show_price
from handlers.payments import decide
from handlers.privacy import forget_ask, forget_yes, privacy
from handlers.router import PATTERN, on_callback
from handlers.start import CLIENT_COMMANDS, set_staff_commands, start_command

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

# Таймауты запросов к Telegram, секунды. Через релей за границей ответ бывает медленнее, чем напрямую.
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 20
WRITE_TIMEOUT = 20
POOL_TIMEOUT = 10
# getUpdates (long polling): Telegram держит запрос до POLL_TIMEOUT с, PTB прибавляет его к read-таймауту
POLL_TIMEOUT = 10
GET_UPDATES_TIMEOUT = 10
# post_init — меню команд и описание бота. Не критично: не держим старт дольше этого
POST_INIT_TIMEOUT = 60
# При старте ждём Telegram/релей бесконечно (повтор раз в секунду), а не падаем
BOOTSTRAP_RETRIES = -1


async def _setup_menus(app: Application):
    await app.bot.set_my_commands(CLIENT_COMMANDS, scope=BotCommandScopeDefault())
    ids = await api.get("/staff/ids")
    for chat_id in ids["masters"]:
        await set_staff_commands(app.bot, chat_id, "master")
    if ids["admin"]:
        await set_staff_commands(app.bot, ids["admin"], "admin")
    salon = await api.get("/salon")
    await app.bot.set_my_short_description(f"Онлайн-запись в «{salon['name']}» — без звонков, 24/7")


async def post_init(app: Application):
    try:
        await asyncio.wait_for(_setup_menus(app), POST_INIT_TIMEOUT)
    except Exception as err:  # Telegram/API недоступны — бот всё равно запускается, меню обновится при рестарте
        log.warning("post_init: %r", err)
    log.info("bot @%s started (Telegram API: %s)", app.bot.username, urlsplit(config.TELEGRAM_API_BASE).netloc)


def build(request: BaseRequest | None = None, updates_request: BaseRequest | None = None) -> Application:
    """request/updates_request — только для тестов (фейковый Telegram)."""
    persistence = PicklePersistence(filepath=config.STATE_FILE) if config.STATE_FILE else None
    base = config.TELEGRAM_API_BASE
    builder = (Application.builder().token(config.BOT_TOKEN)
               .base_url(f"{base}/bot").base_file_url(f"{base}/file/bot")  # PTB допишет токен
               .post_init(post_init))
    if request:
        builder = builder.request(request).get_updates_request(updates_request or request)
    else:
        builder = (builder.connect_timeout(CONNECT_TIMEOUT).read_timeout(READ_TIMEOUT)
                   .write_timeout(WRITE_TIMEOUT).pool_timeout(POOL_TIMEOUT)
                   .get_updates_connect_timeout(CONNECT_TIMEOUT).get_updates_read_timeout(GET_UPDATES_TIMEOUT)
                   .get_updates_write_timeout(GET_UPDATES_TIMEOUT).get_updates_pool_timeout(POOL_TIMEOUT))
    if persistence:
        builder = builder.persistence(persistence)
    app = builder.build()
    private = filters.ChatType.PRIVATE

    app.add_handler(booking_handler())  # первым: он ведёт диалог записи
    app.add_handler(CommandHandler("start", start_command, filters=private))
    app.add_handler(CommandHandler("admin", admin.admin_cmd, filters=private))
    app.add_handler(CommandHandler("schedule", staff.schedule_cmd, filters=private))
    app.add_handler(CommandHandler("myid", staff.myid, filters=private))
    app.add_handler(CommandHandler("privacy", privacy, filters=private))
    app.add_handler(CommandHandler("forget", forget_ask, filters=private))

    app.add_handler(CallbackQueryHandler(back_to_menu, pattern=r"^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(show_price, pattern=r"^menu_price$"))
    app.add_handler(CallbackQueryHandler(show_portfolio, pattern=r"^menu_portfolio$"))
    app.add_handler(CallbackQueryHandler(show_contacts, pattern=r"^menu_contacts$"))
    app.add_handler(CallbackQueryHandler(show_profile, pattern=r"^menu_profile$"))
    app.add_handler(CallbackQueryHandler(privacy, pattern=r"^menu_privacy$"))
    app.add_handler(CallbackQueryHandler(forget_ask, pattern=r"^forget_ask$"))
    app.add_handler(CallbackQueryHandler(forget_yes, pattern=r"^forget_yes$"))
    app.add_handler(CallbackQueryHandler(cancel_ask, pattern=r"^cancel_id:\d+$"))
    app.add_handler(CallbackQueryHandler(cancel_yes, pattern=r"^cancel_yes:\d+$"))
    app.add_handler(CallbackQueryHandler(cancel_no, pattern=r"^cancel_no:\d+$"))
    app.add_handler(CallbackQueryHandler(reminder_ok, pattern=r"^rem_ok:\d+$"))
    app.add_handler(CallbackQueryHandler(reminder_cancel, pattern=r"^rem_cancel:\d+$"))
    app.add_handler(CallbackQueryHandler(rate, pattern=r"^rev:\d+:[1-5]$"))
    app.add_handler(CallbackQueryHandler(decide, pattern=r"^pay_(ok|no):\d+$"))
    app.add_handler(CallbackQueryHandler(ask_cancel, pattern=r"^ask_cancel:"))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=PATTERN))
    app.add_handler(CallbackQueryHandler(stale_button))  # всё остальное — устаревшие кнопки

    app.add_handler(MessageHandler(private & (filters.PHOTO | filters.Document.ALL), receipt))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def main():
    build().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False,
                        timeout=POLL_TIMEOUT, bootstrap_retries=BOOTSTRAP_RETRIES)


if __name__ == "__main__":
    main()
