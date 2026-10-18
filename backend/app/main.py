from datetime import datetime, timedelta, timezone
from datetime import time as time_type
from hmac import compare_digest
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import Base, SessionLocal, engine, get_db
from app.models import Registration, RegistrationStatus, SlotStatus, TimeSlot
from app.schemas import AdminLogin, EventResponse, RegistrationCreate, RegistrationResponse, SettingsUpdate, SlotCreate, SlotResponse, SlotsResponse, SlotUpdate
from app.services import create_registration, get_event_settings, public_slot, write_export

settings = get_settings()
app = FastAPI(title="Slot Registration API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[item.strip() for item in settings.cors_origins.split(",")], allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"])


def refresh_export() -> None:
    db = SessionLocal()
    try:
        write_export(db, settings.export_path)
    finally:
        db.close()


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.scalar(select(func.count(TimeSlot.id))) == 0:
            local_zone = ZoneInfo(settings.event_timezone)
            selected_date = datetime.strptime(settings.default_slot_date, "%Y-%m-%d").date() if settings.default_slot_date else (datetime.now(local_zone).date() + timedelta(days=1))
            start_time = time_type.fromisoformat(settings.default_slot_start_time)
            end_time = time_type.fromisoformat(settings.default_slot_end_time)
            cursor = datetime.combine(selected_date, start_time, tzinfo=local_zone)
            closing_time = datetime.combine(selected_date, end_time, tzinfo=local_zone)
            while cursor < closing_time:
                slot_end = min(cursor + timedelta(hours=2), closing_time)
                db.add(TimeSlot(label=f"{cursor:%-I:%M %p} - {slot_end:%-I:%M %p}", starts_at=cursor, ends_at=slot_end, capacity=settings.default_slot_capacity))
                cursor = slot_end
            db.commit()
        write_export(db, settings.export_path)
    finally:
        db.close()


def admin_auth(authorization: str | None = Header(default=None)) -> None:
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not compare_digest(supplied, settings.admin_token.strip()):
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Admin authentication required."})


@app.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    db.execute(select(1))
    return {"status": "ready"}


@app.get("/api/v1/event", response_model=EventResponse)
def event(db: Session = Depends(get_db)) -> EventResponse:
    config = get_event_settings(db)
    return EventResponse(name=settings.event_name, timezone=config.timezone, max_guests_per_registration=config.max_guests_per_registration, count_organizer_as_guest=config.count_organizer_as_guest)


@app.get("/api/v1/slots", response_model=SlotsResponse)
def slots(date: str | None = Query(default=None), db: Session = Depends(get_db)) -> SlotsResponse:
    rows = db.scalars(select(TimeSlot).order_by(TimeSlot.starts_at)).all()
    if date:
        rows = [row for row in rows if row.starts_at.date().isoformat() == date]
    now = datetime.now(timezone.utc)
    return SlotsResponse(slots=[public_slot(row, now) for row in rows])


@app.post("/api/v1/registrations", response_model=RegistrationResponse, status_code=201)
def register(payload: RegistrationCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> RegistrationResponse:
    try:
        item = create_registration(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "Guest count exceeds the configured maximum."}) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc), "message": "This slot is no longer available. Please choose another slot."}) from exc
    background_tasks.add_task(refresh_export)
    return RegistrationResponse(confirmation_code=item.confirmation_code, full_name=item.full_name, slot_label=item.slot.label, starts_at=item.slot.starts_at, ends_at=item.slot.ends_at, guest_count=item.guest_count, created_at=item.created_at)


@app.post("/api/v1/admin/auth/login")
def login(payload: AdminLogin) -> dict:
    token = payload.token.strip()
    if not compare_digest(token, settings.admin_token.strip()):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return {"token": token}


@app.get("/api/v1/admin/summary", dependencies=[Depends(admin_auth)])
def summary(db: Session = Depends(get_db)) -> dict:
    registrations = db.scalar(select(func.count(Registration.id)).where(Registration.status == RegistrationStatus.CONFIRMED)) or 0
    guests = db.scalar(select(func.coalesce(func.sum(Registration.guest_count), 0)).where(Registration.status == RegistrationStatus.CONFIRMED)) or 0
    capacity = db.scalar(select(func.coalesce(func.sum(TimeSlot.capacity), 0)).where(TimeSlot.status != SlotStatus.CANCELLED)) or 0
    return {"registrations": registrations, "guests": guests, "capacity": capacity, "remaining": max(0, capacity - guests)}


@app.get("/api/v1/admin/registrations", dependencies=[Depends(admin_auth)])
def admin_registrations(db: Session = Depends(get_db), limit: int = Query(default=100, le=500), offset: int = Query(default=0, ge=0)) -> dict:
    items = db.scalars(select(Registration).options(joinedload(Registration.slot)).order_by(Registration.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [{"confirmation_code": item.confirmation_code, "full_name": item.full_name, "phone_number": item.phone_number, "address": item.address, "slot_label": item.slot.label, "guest_count": item.guest_count, "status": item.status, "created_at": item.created_at} for item in items]}


@app.get("/api/v1/admin/slots", dependencies=[Depends(admin_auth)])
def admin_slots(db: Session = Depends(get_db)) -> SlotsResponse:
    now = datetime.now(timezone.utc)
    return SlotsResponse(slots=[public_slot(item, now) for item in db.scalars(select(TimeSlot).order_by(TimeSlot.starts_at)).all()])


@app.post("/api/v1/admin/slots", dependencies=[Depends(admin_auth)], response_model=SlotResponse, status_code=201)
def create_slot(payload: SlotCreate, db: Session = Depends(get_db)) -> SlotResponse:
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
    item = TimeSlot(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return public_slot(item, datetime.now(timezone.utc))


@app.patch("/api/v1/admin/slots/{slot_id}", dependencies=[Depends(admin_auth)], response_model=SlotResponse)
def update_slot(slot_id: str, payload: SlotUpdate, db: Session = Depends(get_db)) -> SlotResponse:
    item = db.get(TimeSlot, slot_id)
    if not item:
        raise HTTPException(status_code=404, detail="Slot not found")
    changes = payload.model_dump(exclude_unset=True)
    if "capacity" in changes and changes["capacity"] < item.booked_guests:
        raise HTTPException(status_code=409, detail="Capacity cannot be lower than booked guests")
    if "status" in changes and changes["status"] not in {status.value for status in SlotStatus}:
        raise HTTPException(status_code=422, detail="Invalid slot status")
    for key, value in changes.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return public_slot(item, datetime.now(timezone.utc))


@app.get("/api/v1/admin/settings", dependencies=[Depends(admin_auth)])
def admin_settings(db: Session = Depends(get_db)) -> dict:
    config = get_event_settings(db)
    return {"max_guests_per_registration": config.max_guests_per_registration, "count_organizer_as_guest": config.count_organizer_as_guest, "timezone": config.timezone}


@app.patch("/api/v1/admin/settings", dependencies=[Depends(admin_auth)])
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> dict:
    config = get_event_settings(db)
    config.max_guests_per_registration = payload.max_guests_per_registration
    config.count_organizer_as_guest = payload.count_organizer_as_guest
    db.commit()
    return {"max_guests_per_registration": config.max_guests_per_registration, "count_organizer_as_guest": config.count_organizer_as_guest, "timezone": config.timezone}


@app.get("/api/v1/admin/registrations/export", dependencies=[Depends(admin_auth)])
def export(db: Session = Depends(get_db)) -> FileResponse:
    path = write_export(db, settings.export_path)
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="registrations.xlsx")

