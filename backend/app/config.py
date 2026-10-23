from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # корень проекта, там лежит .env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", str(ROOT / ".env")), extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite+aiosqlite:///./parik.db"
    bot_token: str = ""              # бэкенд сам шлёт напоминания и уведомления
    sentry_dsn: str = ""
    slot_step_min: int = 30          # шаг сетки слотов
    booking_horizon_days: int = 14   # на сколько дней вперёд можно записаться
    max_active_bookings: int = 3     # сколько будущих записей может держать один клиент
    prepay_timeout_min: int = 30     # сколько ждать чек о предоплате, потом бронь снимается
    review_window_hours: int = 24    # не просить отзыв о визитах старше этого (после простоя)


settings = Settings()
