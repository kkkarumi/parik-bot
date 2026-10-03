from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", str(Path(__file__).resolve().parents[2] / ".env")), extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./parik.db"
    bot_token: str = ""          # нужен бэкенду для напоминаний/уведомлений
    sentry_dsn: str = ""
    slot_step_min: int = 30      # шаг сетки слотов
    booking_horizon_days: int = 30


settings = Settings()
