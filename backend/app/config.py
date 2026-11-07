from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # корень проекта, там лежит .env
TELEGRAM_API_DEFAULT = "https://api.telegram.org"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", str(ROOT / ".env")), extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite+aiosqlite:///./parik.db"
    bot_token: str = ""              # бэкенд сам шлёт напоминания и уведомления
    # Адрес Bot API. Если сервер в РФ и Telegram оттуда недоступен — адрес релея (relay/README.md),
    # например https://relay.example.com/SECRET. Без «/» на конце (лишний уберём сами).
    telegram_api_base: str = TELEGRAM_API_DEFAULT
    sentry_dsn: str = ""
    tenant_api_key: str = ""         # бэкенду не нужен — только чтобы вырезать его из событий Sentry
    slot_step_min: int = 30          # шаг сетки слотов
    booking_horizon_days: int = 14   # на сколько дней вперёд можно записаться
    max_active_bookings: int = 3     # сколько будущих записей может держать один клиент
    prepay_timeout_min: int = 30     # сколько ждать чек о предоплате, потом бронь снимается
    review_window_hours: int = 24    # не просить отзыв о визитах старше этого (после простоя)
    # за сколько минут до начала слот закрывается для записи (0 = можно записаться до самого начала)
    min_lead_min: int = Field(0, ge=0)
    # до скольких минут до визита клиент может отменить запись сам (0 = без ограничения).
    # Мастер и админ отменяют всегда. Ровно за N минут отменить ещё можно.
    cancel_before_min: int = Field(0, ge=0)
    # демо-бот для показа клиентам: разрешён manage reset-demo, рассылка по клиентам выключена
    demo_mode: bool = False

    @field_validator("telegram_api_base")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.strip().rstrip("/") or TELEGRAM_API_DEFAULT


settings = Settings()
