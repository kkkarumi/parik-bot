from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SalonOut(ORM):
    name: str
    address: str | None = None
    phone: str | None = None
    work_hours_text: str | None = None
    instagram_url: str | None = None
    welcome_text: str | None = None


class ServiceOut(ORM):
    id: int
    name: str
    price: int
    duration_min: int


class MasterOut(ORM):
    id: int
    name: str


class ClientIn(BaseModel):
    telegram_id: int
    username: str | None = None
    name: str | None = None
    phone: str | None = None


class ClientOut(ORM):
    id: int
    telegram_id: int
    name: str | None = None
    phone: str | None = None


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
    master_name: str
    service_name: str
    client_name: str | None = None
    client_phone: str | None = None


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str | None = None
