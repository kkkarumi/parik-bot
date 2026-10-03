from datetime import datetime, time, timezone

from .config import settings
from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, SmallInteger,
                        String, Text, Time, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Всегда отдаёт aware-datetime в UTC (SQLite хранит время без таймзоны)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Tenant(Base):
    """Салон. Всё остальное привязано через tenant_id."""
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    api_key: Mapped[str] = mapped_column(String(64), unique=True)
    timezone: Mapped[str] = mapped_column(String(40), default="Europe/Moscow")
    admin_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    address: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    work_hours_text: Mapped[str | None] = mapped_column(String(120))
    instagram_url: Mapped[str | None] = mapped_column(String(200))
    welcome_text: Mapped[str | None] = mapped_column(Text)


class Master(Base):
    __tablename__ = "masters"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    price: Mapped[int]
    duration_min: Mapped[int] = mapped_column(default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MasterService(Base):
    __tablename__ = "master_services"
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"), primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), primary_key=True)


class WorkingHours(Base):
    """weekday: 0=Пн … 6=Вс. Несколько строк на день = перерыв."""
    __tablename__ = "working_hours"
    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"), index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("tenant_id", "telegram_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(80))
    name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)  # аллергии, предпочтения


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime())
    price: Mapped[int]  # цена фиксируется на момент записи
    # confirmed | cancelled | completed | no_show   (pending_payment — когда добавим предоплату)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    client_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_24h: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_2h: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(lazy="joined")
    master: Mapped[Master] = relationship(lazy="joined")
    service: Mapped[Service] = relationship(lazy="joined")
    client: Mapped[Client] = relationship(lazy="joined")

    # В SQLite EXCLUDE нет: там защита — asyncio.Lock в create_booking (один процесс)
    __table_args__ = (
        # Главная защита от двойной записи: БД физически не даст пересечь интервалы одного мастера
        ExcludeConstraint(
            ("master_id", "="),
            (text("tstzrange(starts_at, ends_at)"), "&&"),
            name="bookings_no_overlap",
            where=text("status <> 'cancelled'"),
            using="gist",
        ),
    ) if settings.database_url.startswith("postgresql") else ()


class Payment(Base):
    """Задел под ручную предоплату: клиент шлёт чек, админ подтверждает."""
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    amount: Mapped[int]
    receipt_file_id: Mapped[str | None] = mapped_column(String(200))  # telegram file_id
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
