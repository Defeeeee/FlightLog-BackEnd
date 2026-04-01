# 🛠️ Server Deployment Instructions (Handover)

## 🎯 Objective
Configure the production environment on Ubuntu ARM for `flightlog.fdiaznem.com.ar`.

## 1. App Configuration
- **Port:** Change the application port to **`7477`** (Aviation themed).
- **Process Manager:** Initialize the app using **PM2** with the name `flightlog-7477`.
  - Command: `pm2 start run.py --name flightlog-7477 --interpreter ./venv/bin/python`

## 2. Nginx & Subdomains
- **Action:** Look at `/etc/nginx/sites-enabled/` and `/etc/nginx/nginx.conf` first to understand existing patterns.
- **Subdomains:**
  - `auth.flightlog.fdiaznem.com.ar` -> Proxies to `http://localhost:7477/api/auth/`
  - `api.flightlog.fdiaznem.com.ar` -> Proxies to `http://localhost:7477/api/`
- **SSL:** Use **Certbot** to issue and manage Let's Encrypt certificates for both subdomains.
  - Command: `sudo certbot --nginx -d auth.flightlog.fdiaznem.com.ar -d api.flightlog.fdiaznem.com.ar`

## 3. Database Schema Updates
- **Context:** The Supabase database tables (`aircraft` and `flights`) were recently updated with new fields (e.g., `type_acft`, `pic_day_loc`, `IMC Pil`, etc.).
- **Codebase:** The Pydantic models (`src/models/aircraft.py`, `src/models/flight.py`) and Controllers (`src/controllers/flights.py`) have been updated locally to map these using `alias` parameters and `model_dump(by_alias=True, mode="json")`.
- **Action for Next Agent:** Ensure these latest code changes are pulled onto the server (`git pull origin main`). Do not revert the `mode="json"` or `by_alias=True` serialization logic, as it safely handles column names with spaces.

## 4. Deployment Checklist for Agent
1. Verify the Python virtual environment is active.
2. Pull the latest code (`git pull origin main`) to get the latest schema mapping fixes.
3. Update `run.py` and `src/config.py` with the new port and production domains.
4. Write the Nginx server blocks carefully to avoid breaking existing sites.
5. Test Nginx config: `sudo nginx -t`.
6. Reload Nginx: `sudo systemctl reload nginx`.
7. Ensure PM2 is set to start on boot: `pm2 save && pm2 startup`.
