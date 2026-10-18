import os
import uuid
from datetime import datetime, timedelta, timezone

from locust import HttpUser, between, task


class RegistrationUser(HttpUser):
    wait_time = between(0.2, 1.0)
    slot_id = os.getenv("PERF_SLOT_ID", "")
    guest_count = int(os.getenv("PERF_GUEST_COUNT", "1"))

    def on_start(self):
        if not self.slot_id:
            response = self.client.get("/api/v1/slots", name="GET /api/v1/slots")
            if response.status_code != 200:
                raise RuntimeError(f"GET /api/v1/slots returned HTTP {response.status_code}: {response.text[:200]}")
            try:
                slots = response.json().get("slots", [])
            except ValueError as exc:
                raise RuntimeError(f"GET /api/v1/slots returned non-JSON content: {response.text[:200]}") from exc
            available = next((slot for slot in slots if slot.get("selectable")), None)
            if not available:
                raise RuntimeError("No selectable slot found. Seed a slot before running the load test.")
            self.slot_id = available["id"]

    @task
    def submit_registration(self):
        index = uuid.uuid4().hex[:10]
        with self.client.post(
            "/api/v1/registrations",
            json={
                "full_name": f"Load Test {index}",
                "phone_number": f"+919000{index[:6]}",
                "address": "Performance test address",
                "slot_id": self.slot_id,
                "guest_count": self.guest_count,
                "idempotency_key": str(uuid.uuid4()),
            },
            name="POST /api/v1/registrations",
            catch_response=True,
        ) as response:
            if response.status_code in (201, 409):
                response.success()
            else:
                response.failure(f"unexpected status {response.status_code}")

