import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import ExportOutbox, OutboxStatus
from app.services import write_export


def run_once() -> bool:
    db = SessionLocal()
    try:
        job = db.scalar(select(ExportOutbox).where(ExportOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.FAILED])).order_by(ExportOutbox.created_at).limit(1))
        if not job:
            return False
        job.status = OutboxStatus.PROCESSING
        job.attempt_count += 1
        db.commit()
        try:
            write_export(db, get_settings().export_path)
            job.status = OutboxStatus.DONE
            job.last_error = None
            job.processed_at = datetime.now(timezone.utc)
        except Exception as exc:
            job.status = OutboxStatus.FAILED
            job.last_error = str(exc)[:500]
        db.commit()
        return True
    finally:
        db.close()


if __name__ == "__main__":
    while True:
        run_once()
        time.sleep(2)

