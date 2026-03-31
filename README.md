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
├── controllers/     # API route logic (Aircraft, Flights, Auth, Profiles)
├── models/          # Pydantic data schemas
├── config.py        # Settings & Environment management
└── supabase_client.py # Supabase client factory (Singleton & Scoped)
run.py               # Application entry point
requirements.txt      # Project dependencies
```

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
| **System** | `/api/health` | GET | API & DB status |
