# Slot Registration System

A capacity-controlled group registration system for venue visits. Visitors submit organizer details, choose a two-hour slot, and register a group. PostgreSQL is the source of truth; Excel is a generated report.

## Features

- Responsive two-step public registration form
- Automatic two-hour starter slots when the database is empty
- Configurable event timezone, date, hours, capacity, and guest limit
- Atomic PostgreSQL capacity enforcement for simultaneous users
- Idempotent submissions and retry protection
- Admin dashboard and authenticated Excel download
- Excel sheets for registrations, slot summary, and export information
- Pytest API/export tests, PostgreSQL concurrency tests, and Locust tests

## Architecture

```text
Browser -> React/Vite -> FastAPI -> PostgreSQL
                              |
                              +-> Excel export worker -> exports/registrations.xlsx
```

The browser never connects directly to PostgreSQL.

## Requirements

- Python 3.15+
- `uv`
- Node.js and npm
- PostgreSQL 16+
- Optional: Docker and Docker Compose

## Configuration

```bash
cp .env.example .env
```

Important `.env` values:

```env
DATABASE_URL=postgresql+psycopg://venue:venue@localhost:5432/venue_registration
ADMIN_TOKEN=replace-with-a-long-random-secret
EVENT_NAME=Venue Visit Registration
EVENT_TIMEZONE=Asia/Kolkata
MAX_GUESTS_PER_REGISTRATION=15
DEFAULT_SLOT_START_TIME=10:00
DEFAULT_SLOT_END_TIME=18:00
DEFAULT_SLOT_CAPACITY=150
DEFAULT_SLOT_DATE=
EXPORT_PATH=./exports/registrations.xlsx
```

An empty `DEFAULT_SLOT_DATE` creates slots for tomorrow. The default hours create 10 AM-12 PM, 12-2 PM, 2-4 PM, and 4-6 PM slots.

Generate a strong admin token with:

```bash
openssl rand -hex 32
```

Never commit `.env`.

## Local PostgreSQL Setup

On macOS with Homebrew:

```bash
brew install postgresql@16
brew services start postgresql@16
createuser venue
createdb -O venue venue_registration
psql postgres -c "ALTER USER venue WITH PASSWORD 'venue';"
psql -h localhost -U venue -d venue_registration -c "SELECT 1;"
```

The application creates the initial tables and starter slots on startup. PostgreSQL is the runtime database; SQLite is not used by the application.

## Run Locally Without Docker

### Backend

From the repository root:

```bash
uv venv
uv pip install --python .venv/bin/python -r backend/requirements.txt
PYTHONPATH=backend uv run --python .venv/bin/python uvicorn app.main:app --app-dir backend --reload
```

Backend: `http://localhost:8000`

API documentation: `http://localhost:8000/docs`

### Frontend

In a second terminal:

```bash
npm install --prefix frontend
npm run dev --prefix frontend
```

Frontend: `http://localhost:5173`

The Vite server proxies `/api` and `/health` to the backend.

## Admin Access

Open `http://localhost:5173/#admin` and enter the exact value of `ADMIN_TOKEN` from `.env`.

Admin API requests use:

```http
Authorization: Bearer <ADMIN_TOKEN>
```

## Excel Reports

The workbook is generated at `exports/registrations.xlsx` and contains `Registrations`, `Slot Summary`, and `Export Info` sheets.

For local development, the API refreshes the workbook after a successful booking. The worker can also be run separately:

```bash
PYTHONPATH=backend uv run --python .venv/bin/python -m app.worker
```

Keep the export folder private because it contains personal information.

## Tests

Run the fast API and export tests:

```bash
PYTHONPATH=backend uv run --python .venv/bin/python pytest backend/tests -q
```

For true concurrency testing, use a separate PostgreSQL database. Do not use the application database because test setup recreates tables.

```bash
createdb -O venue venue_registration_test
psql venue_registration_test -c "ALTER SCHEMA public OWNER TO venue; GRANT USAGE, CREATE ON SCHEMA public TO venue;"
```

Run all tests against PostgreSQL:

```bash
DATABASE_URL=postgresql+psycopg://venue:venue@localhost:5432/venue_registration_test \
ADMIN_TOKEN=test-token \
PYTHONPATH=backend \
uv run --python .venv/bin/python pytest backend/tests -q
```

The concurrency tests verify that simultaneous users cannot exceed capacity, losing requests receive `409`, idempotent retries create one booking, and counters match confirmed guest totals.

## Locust Performance Testing

Install Locust:

```bash
uv pip install --python .venv/bin/python -r performance/requirements.txt
```

Keep the backend running on port `8000`, then start Locust against the API, not the frontend:

```bash
uv run --python .venv/bin/python locust \
  -f performance/locustfile.py \
  --host http://127.0.0.1:8000
```

Open `http://localhost:8089`. Headless example:

```bash
uv run --python .venv/bin/python locust \
  -f performance/locustfile.py \
  --host http://127.0.0.1:8000 \
  --headless \
  -u 50 \
  -r 10 \
  -t 60s
```

The script treats `201 Created` and `409 Slot Full` as expected outcomes. After a run, verify this PostgreSQL invariant:

```sql
SELECT ts.id, ts.capacity, ts.booked_guests,
       COALESCE(SUM(CASE WHEN r.status = 'CONFIRMED' THEN r.guest_count ELSE 0 END), 0) AS confirmed_guests
FROM time_slots ts
LEFT JOIN registrations r ON r.slot_id = ts.id
GROUP BY ts.id, ts.capacity, ts.booked_guests;
```

Every slot must satisfy `booked_guests <= capacity` and `booked_guests = confirmed_guests`.

Performance evidence: [test_reports/locust_performance_report.txt](test_reports/locust_performance_report.txt)

## Docker Compose

To run PostgreSQL, API, worker, and frontend together:

```bash
cp .env.example .env
docker compose -f deploy/compose.yaml up --build
```

Open `http://localhost:8080`. API docs are at `http://localhost:8000/docs`.

## Free Public Hosting

The repository includes [`render.yaml`](render.yaml) for a free prototype deployment:

- Render free web service: FastAPI backend
- Render free static site: React frontend
- Supabase free PostgreSQL project: persistent database

Render's free web service can sleep after inactivity and may take about a minute to wake. Its local filesystem is ephemeral, so the database is the source of truth and the Excel file is generated for download rather than treated as permanent storage. Render's free PostgreSQL service is temporary, so use Supabase for a longer-lived free database.

### 1. Create the database

Create a project at [Supabase](https://supabase.com/), open **Connect**, and copy a PostgreSQL connection string. Use the pooler connection if the direct connection is not reachable from your hosting service. URL-encode special characters in the database password and use the SQLAlchemy driver prefix:

```text
postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres?sslmode=require
```

### 2. Push the repository to GitHub

Create an empty GitHub repository and push this project. Do not commit `.env`, database passwords, or the admin token.

### 3. Deploy with Render Blueprint

In Render, choose **New > Blueprint**, select the GitHub repository, and apply `render.yaml`. Set these values when prompted:

- `DATABASE_URL`: the Supabase connection string
- `CORS_ORIGINS`: the final frontend URL, for example `https://slot-registration-frontend.onrender.com`
- `DEFAULT_SLOT_DATE`: optional `YYYY-MM-DD`; leave empty to create tomorrow's slots
- `VITE_API_BASE_URL`: the backend URL, for example `https://slot-registration-api.onrender.com`

The static frontend variable is used during the build, so redeploy the frontend after changing it. After deployment, open the frontend URL and use `/#admin` for the admin console. The generated admin token is visible in the Render API service's environment settings.

### 4. Verify the deployment

```bash
curl https://YOUR-API.onrender.com/health/ready
```

Then open the public frontend URL, submit a test registration, and confirm it appears in the admin console and Excel download. Delete test registrations from the Supabase database before sharing the link widely.

This free setup is suitable for a demonstration or small personal event. It has sleeping services, provider quotas, and no production-grade uptime or backup guarantees. For a real high-traffic event, use an always-on API and a managed database with backups.

## API Endpoints

### Public

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health/live` | Liveness |
| GET | `/health/ready` | Database readiness |
| GET | `/api/v1/event` | Public event configuration |
| GET | `/api/v1/slots` | Slot availability |
| POST | `/api/v1/registrations` | Create a booking |

### Admin

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/admin/auth/login` | Validate admin token |
| GET | `/api/v1/admin/summary` | Dashboard totals |
| GET | `/api/v1/admin/registrations` | Registration list |
| GET | `/api/v1/admin/registrations/export` | Download Excel |
| GET | `/api/v1/admin/slots` | List slots |
| POST | `/api/v1/admin/slots` | Create a slot |
| PATCH | `/api/v1/admin/slots/{slot_id}` | Update a slot |
| GET/PATCH | `/api/v1/admin/settings` | Read/update event settings |

## Project Structure

```text
backend/app/       FastAPI application, models, booking, exports, worker
backend/tests/     API, export, and concurrency tests
frontend/          React/Vite public and admin interfaces
performance/       Locust load-test profile
deploy/            Docker Compose configuration
exports/           Private generated workbook directory
test_reports/      Performance evidence
```

## Security and Production Notes

- Use a strong `ADMIN_TOKEN` and store it in a cloud secret manager.
- Never commit `.env`, database passwords, or generated workbooks.
- Expose only the application through HTTPS; never expose PostgreSQL publicly.
- Use managed PostgreSQL backups in production.
- Keep Excel files outside the public static directory.
- Define retention and deletion rules for phone numbers and addresses.
- Run PostgreSQL concurrency tests before opening registration.
- Add Alembic migrations before production schema changes; the MVP creates the initial schema automatically at startup.

