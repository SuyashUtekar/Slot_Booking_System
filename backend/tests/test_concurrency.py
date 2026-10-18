import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("DATABASE_URL", "").startswith("sqlite"),
    reason="Run concurrency tests against PostgreSQL; SQLite serializes writes differently.",
)


def create_slot(client, capacity=10):
    start = datetime.now(timezone.utc) + timedelta(days=1)
    response = client.post(
        "/api/v1/admin/slots",
        headers={"Authorization": "Bearer test-token"},
        json={"label": "Concurrent slot", "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=2)).isoformat(), "capacity": capacity},
    )
    assert response.status_code == 201
    return response.json()["id"]


def booking(slot_id, index, guests=1, key=None):
    return {"full_name": f"Concurrent User {index}", "phone_number": f"+9198765{index:05d}", "address": "Test address", "slot_id": slot_id, "guest_count": guests, "idempotency_key": key or f"concurrent-key-{index:04d}"}


def test_only_capacity_fits_under_simultaneous_submissions(client):
    slot_id = create_slot(client, capacity=10)
    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(lambda index: client.post("/api/v1/registrations", json=booking(slot_id, index)), range(20)))
    statuses = [response.status_code for response in responses]
    assert statuses.count(201) == 10
    assert statuses.count(409) == 10
    slot = client.get("/api/v1/slots").json()["slots"][0]
    assert slot["booked_guests"] == 10
    assert sum(item["guest_count"] for item in client.get("/api/v1/admin/registrations", headers={"Authorization": "Bearer test-token"}).json()["items"]) == 10


def test_same_idempotency_key_creates_one_booking(client):
    slot_id = create_slot(client, capacity=20)
    payload = booking(slot_id, 1, guests=4, key="same-key-concurrent-001")
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post("/api/v1/registrations", json=payload), range(8)))
    assert all(response.status_code == 201 for response in responses)
    confirmations = {response.json()["confirmation_code"] for response in responses}
    assert len(confirmations) == 1
    assert client.get("/api/v1/slots").json()["slots"][0]["booked_guests"] == 4

