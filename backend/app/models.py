from datetime import date, datetime, time, timezone

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Index, SmallInteger,
                        String, Text, Time, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    # предоплата: 0 = выключена; payment_details — куда переводить (показывается клиенту)
    prepay_amount: Mapped[int] = mapped_column(default=0, server_default="0")
    payment_details: Mapped[str | None] = mapped_column(Text)
    # одноразовый код: кто откроет ссылку t.me/<bot>?start=admin_<код>, тот станет админом
    admin_invite_code: Mapped[str | None] = mapped_column(String(32))


class Master(Base):
    __tablename__ = "masters"
    __table_args__ = (Index("ix_masters_invite_code", "invite_code", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    invite_code: Mapped[str | None] = mapped_column(String(32))  # ссылка-приглашение для мастера


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


class MasterTimeOff(Base):
    """Выходной/больничный/отпуск мастера на конкретную дату — слоты в этот день не выдаются."""
    __tablename__ = "master_time_off"
    __table_args__ = (UniqueConstraint("master_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"), index=True)
    day: Mapped[date] = mapped_column(Date)


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("tenant_id", "telegram_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(80))
    name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)  # заметки мастера: предпочтения, аллергии
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=utcnow)


# Статусы записи:
#   pending_payment — ждём предоплату (слот уже держим)
#   confirmed       — подтверждена
#   completed       — визит прошёл (ставится автоматически после окончания)
#   cancelled       — отменена (cancelled_by: client | staff | system)
#   no_show         — клиент не пришёл (отмечает мастер/админ)
ACTIVE_STATUSES = ("pending_payment", "confirmed")


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
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    cancelled_by: Mapped[str | None] = mapped_column(String(10))
    client_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_24h: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_2h: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(lazy="joined")
    master: Mapped[Master] = relationship(lazy="joined")
    service: Mapped[Service] = relationship(lazy="joined")
    client: Mapped[Client] = relationship(lazy="joined")

    # Postgres: БД физически не даст пересечь интервалы одного мастера.
    # В SQLite EXCLUDE нет — там защищает asyncio.Lock в create_booking (бэкенд = один процесс).
    __table_args__ = (
        ExcludeConstraint(
            ("master_id", "="),
            (text("tstzrange(starts_at, ends_at)"), "&&"),
            name="bookings_no_overlap",
            where=text("status <> 'cancelled'"),
            using="gist",
        ),
    ) if settings.database_url.startswith("postgresql") else ()


class Payment(Base):
    """Ручная предоплата: клиент шлёт чек, админ подтверждает.
    status: awaiting (ждём чек) | pending (чек прислан, ждёт админа) | approved | rejected | expired"""
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    amount: Mapped[int]
    receipt_file_id: Mapped[str | None] = mapped_column(String(200))  # telegram file_id
    status: Mapped[str] = mapped_column(String(20), default="awaiting")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    booking: Mapped[Booking] = relationship(lazy="joined")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
