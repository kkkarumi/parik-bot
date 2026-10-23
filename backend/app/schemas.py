from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- салон ----------
class SalonOut(ORM):
    name: str
    address: str | None = None
    phone: str | None = None
    work_hours_text: str | None = None
    instagram_url: str | None = None
    welcome_text: str | None = None
    timezone: str = "Europe/Moscow"
    prepay_amount: int = 0


class SalonAdminOut(SalonOut):
    payment_details: str | None = None
    admin_chat_id: int | None = None


class SalonPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    address: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=40)
    work_hours_text: str | None = Field(None, max_length=120)
    instagram_url: str | None = Field(None, max_length=200)
    welcome_text: str | None = Field(None, max_length=2000)
    prepay_amount: int | None = Field(None, ge=0, le=1_000_000)
    payment_details: str | None = Field(None, max_length=1000)


# ---------- услуги / мастера ----------
class ServiceOut(ORM):
    id: int
    name: str
    price: int
    duration_min: int


class ServiceAdminOut(ServiceOut):
    is_active: bool


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price: int = Field(ge=0, le=1_000_000)
    duration_min: int = Field(ge=5, le=720)


class ServicePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    price: int | None = Field(None, ge=0, le=1_000_000)
    duration_min: int | None = Field(None, ge=5, le=720)
    is_active: bool | None = None


class MasterOut(ORM):
    id: int
    name: str


class MasterAdminOut(MasterOut):
    is_active: bool
    linked: bool
    service_ids: list[int]


class MasterIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class MasterPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    is_active: bool | None = None


class ServiceIds(BaseModel):
    service_ids: list[int]


class Interval(BaseModel):
    start: str  # "10:00"
    end: str    # "20:00"

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        try:
            h, m = (int(x) for x in v.strip().replace(".", ":").split(":"))
        except ValueError:
            raise ValueError("bad time") from None
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("bad time")
        return f"{h:02d}:{m:02d}"


class DayHours(BaseModel):
    weekday: int = Field(ge=0, le=6)
    intervals: list[Interval]  # пусто = выходной


class TimeOffIn(BaseModel):
    day: date


class InviteOut(BaseModel):
    code: str


# ---------- клиенты ----------
class ClientIn(BaseModel):
    telegram_id: int
    username: str | None = None
    name: str | None = None
    phone: str | None = None


class ClientOut(ORM):
    id: int
    telegram_id: int
    username: str | None = None
    name: str | None = None
    phone: str | None = None
    is_blocked: bool = False


class ClientPatch(BaseModel):
    notes: str | None = Field(None, max_length=2000)
    is_blocked: bool | None = None


class ClientCard(ClientOut):
    notes: str | None = None
    visits: int
    no_shows: int
    cancelled: int
    spent: int
    history: list["BookingOut"]


# ---------- записи ----------
class BookingIn(BaseModel):
    client_id: int
    master_id: int
    service_id: int
    starts_at: datetime


class BookingOut(BaseModel):
    id: int
    starts_at: datetime
    ends_at: datetime
    price: int
    status: str
    master_id: int
    master_name: str
    service_name: str
    client_id: int
    client_name: str | None = None
    client_phone: str | None = None
    client_username: str | None = None
    prepay_amount: int = 0          # >0 только у записей, ждущих предоплату
    payment_details: str | None = None


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str | None = Field(None, max_length=2000)


class ReceiptIn(BaseModel):
    file_id: str = Field(min_length=1, max_length=200)
    kind: str = Field("photo", pattern="^(photo|document)$")


# ---------- персонал ----------
class LinkIn(BaseModel):
    code: str
    telegram_id: int


class RoleOut(BaseModel):
    role: str | None  # admin | master | None
    master_id: int | None = None
    name: str | None = None


class StaffIds(BaseModel):
    admin: int | None
    masters: list[int]


class Stats(BaseModel):
    days: int
    bookings: int
    completed: int
    cancelled: int
    no_show: int
    revenue: int
    upcoming: int
    new_clients: int
    avg_rating: float | None
    reviews: int
    by_master: list[dict]
    by_service: list[dict]


ClientCard.model_rebuild()
