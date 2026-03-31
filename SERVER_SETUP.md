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

## 3. Deployment Checklist for Agent
1. Verify the Python virtual environment is active.
2. Update `run.py` and `src/config.py` with the new port and production domains.
3. Write the Nginx server blocks carefully to avoid breaking existing sites.
4. Test Nginx config: `sudo nginx -t`.
5. Reload Nginx: `sudo systemctl reload nginx`.
6. Ensure PM2 is set to start on boot: `pm2 save && pm2 startup`.
