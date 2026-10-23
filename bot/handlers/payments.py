"""Админ подтверждает или отклоняет чек о предоплате (кнопки под фото чека)."""
from telegram import Update
from telegram.ext import ContextTypes

from api_client import ApiError, api
from ui import ack

RESULT = {"confirmed": "✅ <b>Оплата подтверждена</b>, клиент записан.",
          "cancelled": "❌ <b>Оплата отклонена</b>, бронь снята.",
          "completed": "Визит уже прошёл."}


async def decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    action, pid = q.data.split(":")
    try:
        r = await api.post(f"/admin/payments/{pid}/{'approve' if action == 'pay_ok' else 'reject'}",
                           telegram_id=q.from_user.id)
    except ApiError as err:
        if err.status in (403, 404):
            return await ack(q, "Только администратор может подтверждать оплату", alert=True)
        raise
    await ack(q)
    note = RESULT.get(r["status"], f"Статус записи: {r['status']}")
    if not r["ok"]:
        note = "ℹ️ Уже обработано. " + note
    caption = (q.message.caption_html or "") + "\n\n" + note
    await q.message.edit_caption(caption[:1024], parse_mode="HTML", reply_markup=None)
