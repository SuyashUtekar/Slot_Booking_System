# Event Registration App — Implementation Plan

A link-based, Google-Forms-style registration app that runs on a **single machine**, with time-slot booking, per-slot guest caps, and an Excel record of every registration.

---

## 1. Goals

| # | Requirement |
|---|-------------|
| 1 | Page 1: collect **name, phone number, address** |
| 2 | Page 2: choose a **time slot** (e.g. 6–7 PM) and **number of guests** |
| 3 | Each slot has a **guest cap** (e.g. 100–200). When full, the slot is **frozen/removed from the UI** |
| 4 | Every registration is **stored and exported to Excel** |
| 5 | Shareable **public link**, works on mobile |

### Bottlenecks to solve
1. **Traffic management** — many users opening the link at once
2. **Concurrent booking** — no overbooking even when hundreds submit simultaneously
3. **User-friendly UI** — fast, mobile-first, clear errors

---

## 2. Tech Stack (single machine)

| Layer | Choice | Why |
|-------|--------|-----|
| Backend | **FastAPI** (Python 3.11+) + Uvicorn | Async, fast, easy validation with Pydantic |
| Database | **SQLite (WAL mode)** | Zero setup, serialized writes make capacity checks safe, handles thousands of writes/min |
| Frontend | **React + Vite + Tailwind** (or Alpine.js if you want even lighter) | Multi-step form UX, small static bundle |
| Excel | **openpyxl** (or `pandas`) | Generate/append `.xlsx` |
| Reverse proxy | **Caddy** (or Nginx) | HTTPS, gzip, static caching, rate limiting |
| Public access | **Cloudflare Tunnel** (or port-forward + domain) | Shareable link from one machine without exposing your IP |
| Bot protection | **Cloudflare Turnstile** (free CAPTCHA alternative) | Stops spam bookings eating capacity |
| Process manager | **systemd** or Docker Compose | Auto-restart |
| Load testing | **Locust** or k6 | Prove the concurrency design works |

> **Source of truth = SQLite.** Excel is a *derived export*, never the database. Writing to an `.xlsx` directly on every request causes file locking, corruption, and slowness under load.

---

## 3. Architecture

```
User phone/browser
        │
        ▼
 Cloudflare (CDN + Tunnel + Turnstile)
        │
        ▼
 Caddy  ── serves static React build (cached)
        │  └─ proxies /api/* + rate limits
        ▼
 FastAPI (2–4 Uvicorn workers)
        │
        ├── GET  /api/slots          (availability, cached ~2s)
        ├── POST /api/register       (atomic booking)
        └── /api/admin/*             (login, dashboard, export)
        │
        ▼
   SQLite (WAL)  ──►  Background exporter  ──►  registrations.xlsx
```

---

## 4. Data Model

```sql
CREATE TABLE slots (
  id         INTEGER PRIMARY KEY,
  label      TEXT NOT NULL,          -- "6:00 PM - 7:00 PM"
  start_time TEXT NOT NULL,
  capacity   INTEGER NOT NULL,       -- e.g. 150
  booked     INTEGER NOT NULL DEFAULT 0,
  is_active  INTEGER NOT NULL DEFAULT 1,
  CHECK (booked >= 0 AND booked <= capacity)
);

CREATE TABLE registrations (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  phone           TEXT NOT NULL,
  address         TEXT NOT NULL,
  slot_id         INTEGER NOT NULL REFERENCES slots(id),
  guests          INTEGER NOT NULL CHECK (guests BETWEEN 1 AND 20),  -- hard ceiling; real limit = MAX_GUESTS_PER_BOOKING in config
  idempotency_key TEXT UNIQUE,       -- prevents double submit
  booking_ref     TEXT UNIQUE,       -- shown on confirmation
  created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
  exported        INTEGER DEFAULT 0
);

CREATE UNIQUE INDEX uq_phone_active ON registrations(phone);  -- one booking per phone (optional)
```

The `CHECK (booked <= capacity)` constraint is a **database-level safety net**: even if application code has a bug, overbooking is impossible.

---

## 5. Solving the Core Problem: Concurrent Slot Booking

### The wrong way (race condition)
```
read booked → check < capacity → write booked+n
```
Two requests can both read `booked = 148`, both pass the check, and both write → overbooked.

### The right way: single atomic conditional update
```python
def book_slot(conn, slot_id, guests, data, idem_key):
    with conn:  # one transaction
        cur = conn.execute(
            """UPDATE slots
               SET booked = booked + :g
               WHERE id = :id AND is_active = 1
                 AND booked + :g <= capacity""",
            {"g": guests, "id": slot_id},
        )
        if cur.rowcount == 0:
            raise SlotFull()          # -> HTTP 409
        conn.execute("INSERT INTO registrations (...) VALUES (...)", ...)
```

- The check and the increment happen **in one SQL statement** — no gap for a race.
- The slot update and registration insert are in **one transaction** — both succeed or neither does.
- SQLite serializes writers, so correctness is guaranteed; with WAL mode, readers (the availability endpoint) never block.
- Set `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`

### Handling "slot full" gracefully
- API returns **409** with the **fresh availability list**.
- Frontend shows: *"That slot just filled up — please pick another"* and auto-refreshes the slot list. The user's page-1 data is preserved (don't make them retype).

### Guests vs remaining capacity
A slot with 3 seats left must reject a 5-guest booking but still accept 3. The `booked + :g <= capacity` condition handles this; the UI also disables guest counts above `remaining`.

### One person booking for many guests
One person can register a group of up to `MAX_GUESTS_PER_BOOKING` (10–20) guests in a single booking. Because large groups consume seats quickly (a 20-guest booking is 10–20% of a 100–200 seat slot), the same atomic update is used, and the limit is enforced in three places: the UI stepper, Pydantic validation, and the DB `CHECK`. The one-booking-per-phone unique index (Section 4) stops someone from bypassing the per-booking limit by submitting several bookings, so the phone number's total is also capped at the limit.

---

## 6. Traffic Management

| Technique | Detail |
|-----------|--------|
| **Static assets via CDN/Caddy** | React build is static, cached with long max-age. Server never renders pages. |
| **Cache availability endpoint** | `GET /api/slots` cached 1–2 seconds in memory. 5,000 users polling = ~1 DB read/sec. |
| **Poll smartly** | Frontend polls every 5–10 s on page 2 only, with jitter. Optional upgrade: Server-Sent Events. |
| **Rate limiting** | Caddy/slowapi: e.g. 10 req/min/IP on `/register`, higher on `/slots`. |
| **Idempotency key** | Frontend generates a UUID per submit; retries or double-taps return the *same* booking, not a second one. |
| **Disable button on submit** | Prevents accidental double-clicks. |
| **Turnstile CAPTCHA** | Invisible challenge on submit; blocks bots hoarding seats. |
| **Short-lived seat hold (optional)** | When user lands on the confirm step, hold seats for 5 min (`holds` table with expiry) so they don't fail after filling everything. Add only if you see many "slot full at submit" failures. |
| **Waiting room (optional, for huge spikes)** | If the link goes viral, add a simple queue: users get a token and are admitted N per second. Cloudflare Waiting Room does this without code. |
| **Worker tuning** | 2–4 Uvicorn workers; keep handlers short (no Excel work in the request path). |

**Capacity estimate:** a FastAPI + SQLite setup on a normal laptop/VM comfortably handles several hundred booking writes per second — far more than a venue with a few thousand seats needs. The real spike risk is *reads* and *bots*, which caching and Turnstile cover.

---

## 7. Excel Export Strategy

Do **not** write to Excel inside `POST /register`.

1. **Background exporter** (APScheduler task or a small thread): every ~10–30 s, select rows where `exported = 0`, append to `registrations.xlsx`, mark them exported. Writes are batched and single-threaded → no file-lock conflicts.
2. **Admin download button**: `GET /api/admin/export.xlsx` regenerates a fresh file from the DB on demand (always complete and consistent).
3. **Excel columns:** Booking Ref · Name · Phone · Address · Slot · Guests · Registered At.
4. Optional second sheet: **Slot Summary** (slot, capacity, booked, remaining).
5. Also keep a nightly copy of the `.db` file as a backup.

---

## 8. API Design

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/slots` | List slots with `remaining` and `status` (`open` / `almost_full` / `full`) |
| POST | `/api/register` | Validate + atomically book; returns `booking_ref` |
| GET | `/api/registration/{ref}` | Confirmation lookup |
| POST | `/api/admin/login` | Admin auth (token/cookie) |
| GET | `/api/admin/stats` | Totals, per-slot fill |
| GET | `/api/admin/export.xlsx` | Download Excel |
| POST | `/api/admin/slots` | Create/edit slot, change capacity, freeze manually |

**Validation (server-side always, client-side for UX):**
- Name: 2–80 chars
- Phone: Indian 10-digit regex (`^[6-9]\d{9}$`), normalized (strip +91/spaces)
- Address: 10–300 chars
- Guests: 1 to `MAX_GUESTS_PER_BOOKING` (config value, 10–20; enforced server-side, so it can be changed without a code change)
- Slot must be active

---

## 9. Frontend / UX Plan

### Flow
```
[Step 1: Your details] → [Step 2: Slot + guests] → [Step 3: Review] → [Success screen]
```
A progress bar (Step 1 of 3) at the top.

### Step 1 — Details
- Large inputs, correct mobile keyboards (`inputmode="tel"` for phone).
- Inline validation on blur, not on every keystroke.
- "Next" button stays disabled until valid, with clear helper text.

### Step 2 — Slot & guests
- Slots shown as **tappable cards/chips** (not a dropdown), each with a label and status:
  - 🟢 **Available** — "120 spots left"
  - 🟠 **Filling fast** — "Only 12 left" (when < 10–15%)
  - ⚫ **Full** — greyed out, unclickable, with a "Full" badge
- **Frozen slots**: either hide them or show as disabled; showing them disabled is friendlier (users see the venue is popular and understand why).
- Guest counter with **+ / −** stepper, capped at `min(MAX_GUESTS_PER_BOOKING, remaining)`. Since the limit can be up to 20, also allow tapping the number to type it directly instead of pressing + many times.
- Live refresh of availability every few seconds; if the chosen slot fills while the user is deciding, show a clear inline message and deselect it.

### Step 3 — Review & submit
- Summary of all details with "Edit" links back.
- Single prominent **Confirm Registration** button; spinner + disabled state while submitting.

### Success screen
- Big confirmation, **booking reference**, slot, guest count.
- "Save screenshot" hint / optional download of a small PDF or QR code for venue entry.
- Optional: QR code that staff can scan at the gate (check-in feature later).

### General UX rules
- Mobile-first (most users arrive from WhatsApp/links), large tap targets (≥44px).
- Total page weight under ~200 KB; no heavy libraries.
- Plain-language error messages ("That slot just filled up — please choose another"), never raw errors.
- Preserve form state in memory if the user navigates back.
- Accessible: labels, focus states, sufficient contrast, keyboard navigable.
- Optional: English + Hindi/Marathi toggle.

---

## 10. Project Structure

```
event-registration/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, middleware, static mount
│   │   ├── config.py          # env settings (caps, limits, admin creds)
│   │   ├── db.py              # SQLite connection, PRAGMAs, migrations
│   │   ├── models.py          # Pydantic schemas
│   │   ├── routes/
│   │   │   ├── public.py      # /slots, /register
│   │   │   └── admin.py       # stats, export, slot mgmt
│   │   ├── services/
│   │   │   ├── booking.py     # atomic booking logic
│   │   │   └── exporter.py    # Excel generation + scheduler
│   │   └── utils/validators.py
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/ (components: StepDetails, StepSlot, StepReview, Success)
│   └── vite.config.ts
├── deploy/
│   ├── Caddyfile
│   ├── registration.service   # systemd unit
│   └── docker-compose.yml     # optional
├── data/                      # registrations.db, registrations.xlsx, backups
└── README.md
```

---

## 11. Step-by-Step Build Plan

### Phase 1 — Foundation (Day 1)
1. Create repo, Python venv, install `fastapi uvicorn[standard] openpyxl apscheduler slowapi pydantic`.
2. Implement `db.py`: connection helper, WAL pragmas, schema creation script.
3. Seed script to create slots (label, capacity) from a config/JSON file.

### Phase 2 — Core booking API (Day 1–2)
4. `GET /api/slots` with computed `remaining` and `status`.
5. Pydantic models + validators for registration payload.
6. Implement atomic `book_slot()` (Section 5) and `POST /api/register`.
7. Idempotency-key handling: if key exists, return the existing booking.
8. Unit tests: validation, booking success, slot-full, partial capacity, duplicate key.
9. **Concurrency test**: spawn 500 parallel requests against a slot with capacity 150 and assert `booked == 150` exactly, and registrations sum correctly.

### Phase 3 — Excel export (Day 2)
10. `exporter.py`: batch append of unexported rows, mark as exported.
11. APScheduler job every 15 s.
12. On-demand `export.xlsx` endpoint (full regeneration), plus slot-summary sheet.

### Phase 4 — Frontend (Day 2–4)
13. Scaffold Vite + React + Tailwind.
14. Build the 3-step wizard with progress bar and shared form state.
15. Slot cards with live availability polling (with jitter), disabled/frozen states, guest stepper.
16. Submit flow with idempotency key, loading state, and 409 handling (refresh + keep data).
17. Success screen with booking reference.
18. Mobile testing on real phones; Lighthouse pass.

### Phase 5 — Admin (Day 4–5)
19. Simple admin login (env-based password → signed cookie/JWT).
20. Dashboard: totals, per-slot progress bars, recent registrations, Download Excel button.
21. Controls: edit capacity, manually freeze/unfreeze a slot, search a registration.

### Phase 6 — Hardening & traffic (Day 5–6)
22. Add rate limiting and in-memory cache for `/slots`.
23. Add Turnstile verification on `/register`.
24. Caddy config: HTTPS, gzip/brotli, static cache headers, request size limits.
25. Cloudflare Tunnel (or domain + port forward) to expose the public link.
26. Logging (request IDs, booking events) and a nightly DB backup cron.

### Phase 7 — Load test & launch (Day 6–7)
27. Locust scenario: 3,000 users hit page → poll slots → 30% submit within a 60-second window.
28. Verify: zero overbooking, p95 latency of `/register` < 500 ms, CPU/RAM acceptable.
29. Tune Uvicorn worker count and SQLite pragmas if needed.
30. Dry run with a few real users; fix UX rough edges.
31. Go live; monitor the admin dashboard.

---

## 12. Edge Cases Checklist

- [ ] Two users book the last seats simultaneously → one succeeds, the other gets a friendly 409
- [ ] User double-taps submit / refreshes after submit → idempotency returns same booking
- [ ] Same phone number registers twice → blocked (or allowed with a warning, decide policy)
- [ ] Same person tries to exceed the guest limit by submitting multiple bookings → blocked by the unique phone rule
- [ ] Guest count exceeds remaining seats → rejected server-side even if UI was stale
- [ ] Slot frozen by admin mid-flow → user gets clear message and re-selects
- [ ] Server restart mid-traffic → systemd restarts; SQLite WAL recovers cleanly
- [ ] Excel file open on the admin's machine → exporter writes to a server-side copy; admin downloads fresh export instead of editing the live file
- [ ] Bot flood → Turnstile + rate limits
- [ ] Power/disk failure → nightly backup + `synchronous=NORMAL` with WAL is safe against app crashes (use `FULL` if you need protection against sudden power loss)

---

## 13. Decisions to Confirm

1. **One booking per phone number?** (recommended: yes, since it is what makes the per-person guest limit enforceable)
2. ~~Max guests per booking?~~ **Decided:** one person can book for many guests, limited to 10–20 per booking. Still to pick the exact number (suggested: 15, and keep it configurable).
3. **Do you need OTP phone verification?** (adds SMS cost/complexity; skip for v1 unless fake entries are a concern)
4. **Single event date or multiple dates?** (multiple dates = add a `date` column to `slots`)
5. **Do you want QR-code entry passes** for check-in at the venue? (good v2 feature)
6. **Language support** needed (English/Hindi/Marathi)?

---

## 14. Future Enhancements

- QR-code pass + gate check-in scanner page
- WhatsApp/SMS confirmation
- Waitlist for full slots
- Move to PostgreSQL + Redis if you outgrow a single machine
- Live occupancy display for staff
