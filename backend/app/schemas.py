from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class EventResponse(BaseModel):
    name: str
    timezone: str
    max_guests_per_registration: int
    count_organizer_as_guest: bool


class SlotResponse(BaseModel):
    id: str
    label: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    booked_guests: int
    remaining_guests: int
    status: str
    selectable: bool


class SlotsResponse(BaseModel):
    slots: list[SlotResponse]


class RegistrationCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone_number: str = Field(min_length=5, max_length=40)
    address: str = Field(min_length=3, max_length=2000)
    slot_id: str = Field(min_length=1, max_length=36)
    guest_count: int = Field(ge=1)
    idempotency_key: str = Field(min_length=12, max_length=80)

    @field_validator("full_name", "phone_number", "address", "slot_id", "idempotency_key")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class RegistrationResponse(BaseModel):
    confirmation_code: str
    full_name: str
    slot_label: str
    starts_at: datetime
    ends_at: datetime
    guest_count: int
    created_at: datetime


class SlotCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(gt=0)


class SlotUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    capacity: int | None = Field(default=None, gt=0)
    status: str | None = None


class SettingsUpdate(BaseModel):
    max_guests_per_registration: int = Field(ge=10, le=20)
    count_organizer_as_guest: bool


class AdminLogin(BaseModel):
    token: str = Field(min_length=1, max_length=512)

