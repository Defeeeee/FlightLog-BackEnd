# FlightLog Native API

A high-performance, professional-grade backend for flight logging, built with **Python**, **Litestar**, and **Supabase**.

## 🚀 Overview

This API is designed to handle aircraft management, flight logging, and pilot profiles with a strict focus on security and data integrity. It leverages Supabase's **Row Level Security (RLS)** to ensure that pilots can only access and manage their own data.

### Tech Stack
- **Framework:** [Litestar](https://litestar.dev/) (Asynchronous Python)
- **Database:** [Supabase](https://supabase.com/) (PostgreSQL)
- **Validation:** Pydantic v2
- **Server:** Uvicorn
- **Architecture:** Class-based Controllers with Dependency Injection

---

## 🛡️ Security Architecture

### Row Level Security (RLS)
The database is strictly locked down. This API implements a **User-Scoped Client** pattern:
1. **Extraction:** The `auth_guard` extracts the Bearer JWT from the request headers.
2. **Verification:** The JWT is verified against Supabase Auth.
3. **Injection:** A scoped Supabase client is injected into the controller, configured to act specifically on behalf of the authenticated user.
4. **Enforcement:** PostgreSQL RLS policies automatically filter all queries (SELECT, INSERT, UPDATE, DELETE) based on the `auth.uid()`.

---

## 📂 Project Structure

```text
src/
├── auth/            # Security guards and JWT handling
├── controllers/     # API route logic (Aircraft, Flights, Auth, Profiles, Audit, Documents)
├── models/          # Pydantic data schemas
├── services/        # Pure domain logic with no I/O (audit rules, alert scheduling)
├── config.py        # Settings & Environment management
└── supabase_client.py # Supabase client factory (Singleton & Scoped)
run.py               # Application entry point
requirements.txt      # Project dependencies
```

### Why `services/`

The audit rules and the expiry-alert scheduling take plain dicts and return
plain results — no Supabase, no request context. Keeping them out of the
controllers is what makes `test_audit_engine.py` runnable with no database and
no server.

---

## 🛠️ Setup & Installation

### 1. Prerequisites
- Python 3.11+
- A Supabase Project

### 2. Environment Configuration
Create a `.env` file in the root directory:
```env
SUPABASE_URL=your_supabase_project_url
SUPABASE_PUBLISHABLE_KEY=your_supabase_anon_key
DEBUG=True
```

### 3. Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 🚦 Usage

### Running the API
```bash
python run.py
```
The API will be available at `http://localhost:8000`.

### Documentation
- **Swagger UI:** `http://localhost:8000/schema/swagger`
- **Redoc:** `http://localhost:8000/schema/redoc`

---

## 🧪 Testing

### Master Postman Collection
Import `FlightLog_Master_Tester.postman_collection.json` into Postman.
- **Automated Flow:** Register/Login -> The script captures the JWT -> All subsequent requests (Aircraft/Flights) use the token automatically.
- **Variable Tracking:** The collection automatically tracks `user_id`, `last_aircraft_id`, and `last_flight_id`.

### Quick Registration Test
```bash
python test_registration.py
```

---

## 📝 API Endpoints

| Category | Endpoint | Method | Description |
| :--- | :--- | :--- | :--- |
| **Auth** | `/api/auth/register` | POST | Register a new pilot |
| **Auth** | `/api/auth/login` | POST | Authenticate & get JWT |
| **Profiles**| `/api/profiles/{id}` | GET/PATCH | Manage pilot profile |
| **Aircraft**| `/api/aircraft` | GET/POST | List/Add aircraft |
| **Aircraft**| `/api/aircraft/{id}` | PATCH/DELETE| Update/Remove aircraft |
| **Flights** | `/api/flights` | GET/POST | List/Log flights |
| **Audit** | `/api/audit/summary` | GET | Finding counts for the badge and dashboard card |
| **Audit** | `/api/audit/findings` | GET | Findings, filterable by severity/rule |
| **Audit** | `/api/audit/findings/{id}/suppress` | POST | Silence (or restore) a finding |
| **Audit** | `/api/audit/recalculate` | POST | Re-run every rule over the logbook |
| **Documents**| `/api/documents` | GET/POST | List/Add documents with expiry dates |
| **Documents**| `/api/documents/{id}` | PATCH/DELETE| Update/Remove a document |
| **Alerts** | `/api/document-alerts/pending` | GET | Alerts due today (shared secret, all users) |
| **Alerts** | `/api/document-alerts/{id}/sent` | POST | Record a delivered alert (shared secret) |
| **System** | `/api/health` | GET | API & DB status |

### Audit engine

Findings are recomputed automatically whenever a flight is created, edited or
deleted, and stored in `audit_findings`. Four rules run: overlapping flights,
aircraft missing from the hangar, duplicates, and PIC/SIC breakdowns that don't
match the flight time. A finding the pilot suppresses keeps being refreshed but
stops counting — recalculation never clears that flag.

Run the rule checks with no database:

```bash
python test_audit_engine.py
```

### Document expiry alerts

`/api/document-alerts/*` runs across every user under the service role, so it
authenticates with `DOCUMENTS_ALERT_SECRET` instead of a session and **refuses to
run when that variable is unset**. The backend only decides what is due and
records what was delivered; the WhatsApp send itself happens in the Next app
(`/api/cron/document-alerts`), which is where the Kapso credentials live. Add
the same secret to both `.env` files and schedule the frontend route daily.
