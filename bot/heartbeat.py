"""Healthcheck бота для Docker: файл-«пульс» обновляется раз в HEARTBEAT_EVERY секунд,
но только пока getUpdates реально получает ответы от Telegram.

Почему не по ошибкам: при блокировке (ТСПУ) соединение просто висит, PTB видит TimedOut и молча
повторяет — обработчик ошибок не вызывается. А успешный ответ getUpdates при long polling приходит
минимум раз в POLL_TIMEOUT (10 с), даже когда никто не пишет боту.
"""
import time
from pathlib import Path

from telegram.ext import ContextTypes
from telegram.request import HTTPXRequest

import config

HEARTBEAT_EVERY = 30  # с: как часто обновлять файл (HEALTHCHECK в Dockerfile считает его живым 120 с)
STALE_AFTER = 90      # с без ответа на getUpdates — считаем, что связи с Telegram нет

_last_ok = 0.0  # time.monotonic() последнего ответа 200 на getUpdates


class UpdatesRequest(HTTPXRequest):
    """HTTP-клиент для getUpdates, который запоминает время последнего успешного ответа."""

    async def do_request(self, *args, **kwargs):
        global _last_ok
        code, payload = await super().do_request(*args, **kwargs)
        if code == 200:
            _last_ok = time.monotonic()
        return code, payload


def telegram_ok() -> bool:
    return time.monotonic() - _last_ok < STALE_AFTER


async def beat(context: ContextTypes.DEFAULT_TYPE) -> None:
    if config.HEARTBEAT_FILE and telegram_ok():
        Path(config.HEARTBEAT_FILE).touch()
