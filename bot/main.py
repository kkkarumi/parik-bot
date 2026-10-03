import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

import config
from handlers.booking import booking_handler
from handlers.info import show_contacts, show_portfolio, show_price
from handlers.profile import cancel_by_id, rate, reminder_cancel, reminder_ok, show_profile
from handlers.staff import myid, schedule
from handlers.start import start_command

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)


def main():
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(booking_handler)  # первым: он перехватывает menu_book и свои состояния
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("schedule", schedule))
    app.add_handler(CallbackQueryHandler(schedule, pattern=r"^sch:\d{4}-\d{2}-\d{2}$"))
    app.add_handler(CallbackQueryHandler(start_command, pattern=r"^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(show_price, pattern=r"^menu_price$"))
    app.add_handler(CallbackQueryHandler(show_portfolio, pattern=r"^menu_portfolio$"))
    app.add_handler(CallbackQueryHandler(show_contacts, pattern=r"^menu_contacts$"))
    app.add_handler(CallbackQueryHandler(show_profile, pattern=r"^menu_profile$"))
    app.add_handler(CallbackQueryHandler(cancel_by_id, pattern=r"^cancel_id:\d+$"))
    app.add_handler(CallbackQueryHandler(reminder_ok, pattern=r"^rem_ok:\d+$"))
    app.add_handler(CallbackQueryHandler(reminder_cancel, pattern=r"^rem_cancel:\d+$"))
    app.add_handler(CallbackQueryHandler(rate, pattern=r"^rev:\d+:[1-5]$"))
    app.run_polling()


if __name__ == "__main__":
    main()
