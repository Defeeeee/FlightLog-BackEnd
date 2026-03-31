# FlightLog Frontend Development Blueprint

## 🎯 Project Overview
Build a modern, high-performance web dashboard for the **FlightLog Native API**. The goal is to provide pilots with a seamless interface for aircraft management, logbook maintenance, and real-time flight tracking.

## 🛠️ Technical Stack (Recommended)
- **Framework:** Next.js 14+ (App Router)
- **Styling:** Tailwind CSS + Shadcn/UI (Aviation/Professional aesthetic)
- **State Management:** TanStack Query (React Query) for API synchronization
- **Icons:** Lucide-React
- **Authentication:** Supabase Auth (Client-side) + JWT persistence

## 📡 API Architecture Context
The backend is a **Litestar (Python)** API running at `http://localhost:8000/api`. 
**CRITICAL:** Do NOT use the Supabase client to query the database directly. All data operations MUST go through the Python API to ensure proper business logic and RLS enforcement.

---

## 🎨 UI/UX Requirements
- **Visuals:** High-contrast, dark-mode preferred. Use "Aviation Blue" for primary actions.
- **Mobile-First:** Pilots will use this on iPads/Phones. Large, touch-friendly buttons.
- **Dashboard:** Display "Total Hours," "90-Day Currency," and "Total Landings."

---

## 🏗️ Core Page Requirements

### 1. The "Flight Helper" Widget
A large, prominent toggle button.
- **State Check:** Call `GET /api/flight-helper/session` on load.
- **Action:** Call `POST /api/flight-helper/session`.
- **Logic:** 
  - If no session: Show "🛫 START FLIGHT" (requires Aircraft selection).
  - If active: Show "🛬 END FLIGHT" with a timer showing elapsed time.

### 2. Digital Logbook (`/flights`)
- **Table View:** Responsive list of all flights.
- **Detail View:** Click a flight to see full route, landings, and precise timestamps.

### 3. Aircraft Hangar (`/aircraft`)
- **Cards:** Display registration, Type, and ICAO code.

### 4. Pilot Profile (`/profile`)
- **Management:** View/Edit `first_name`, `last_name`, `license_type`, and `cma_expiry`.
- **Currency Status:** Visual indicator (Green/Red) for `cma_expiry`.

---

## 🚦 Endpoint Reference

| Feature | Method | Endpoint | Note |
| :--- | :--- | :--- | :--- |
| **Auth** | POST | `/api/auth/login` | Store token in cookies |
| **Aircraft** | GET | `/api/aircraft` | List all user aircraft |
| **Flights** | GET | `/api/flights` | Fetch flight history |
| **Helper** | POST | `/api/flight-helper/session` | Start/End session |
| **Helper** | GET | `/api/flight-helper/session` | Check if flying |
| **Profile** | GET | `/api/profiles/{id}` | Get user metadata |
