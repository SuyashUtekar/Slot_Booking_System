from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SlotStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class TimeSlot(Base):
    __tablename__ = "time_slots"
    __table_args__ = (CheckConstraint("capacity > 0"), CheckConstraint("booked_guests >= 0"), CheckConstraint("booked_guests <= capacity"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    label: Mapped[str] = mapped_column(String(120))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int] = mapped_column(Integer)
    booked_guests: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default=SlotStatus.OPEN, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    registrations: Mapped[list["Registration"]] = relationship(back_populates="slot")


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (CheckConstraint("guest_count > 0"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    confirmation_code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    phone_number: Mapped[str] = mapped_column(String(40))
    address: Mapped[str] = mapped_column(Text)
    slot_id: Mapped[str] = mapped_column(ForeignKey("time_slots.id"), index=True)
    guest_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=RegistrationStatus.CONFIRMED, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    slot: Mapped[TimeSlot] = relationship(back_populates="registrations")


class ExportOutbox(Base):
    __tablename__ = "export_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    registration_id: Mapped[str] = mapped_column(ForeignKey("registrations.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), default="REGISTRATION_CONFIRMED")
    status: Mapped[str] = mapped_column(String(20), default=OutboxStatus.PENDING, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class EventSettings(Base):
    __tablename__ = "event_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    max_guests_per_registration: Mapped[int] = mapped_column(Integer, default=15)
    count_organizer_as_guest: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

