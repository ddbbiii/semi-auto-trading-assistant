# Native server deployment

These templates target Ubuntu 24.04 without Docker. Run the API and web processes as the dedicated `trading-assistant` user, bind all application services to loopback, and expose Nginx only on the server's Tailscale address.

The first deployment must leave `TRADING_ASSISTANT_FUTU_ENABLED=0` until OpenD login and device verification are completed. The same applies to model and SMTP credentials. A missing integration is a supported degraded mode.

Before starting services:

1. Install Python 3.12, Node.js 18+, Nginx, SQLite, Tesseract OCR, and Tailscale.
2. Create `/opt/trading-assistant/{app,web,bin}`, `/var/lib/trading-assistant/backups`, and `/etc/trading-assistant`.
3. Build the Next standalone bundle and copy its `server.js`, `.next/static`, and `public` assets to `/opt/trading-assistant/web`.
4. Install the Python project and optional `futu-api` into `/opt/trading-assistant/venv`.
5. Copy the environment file with mode `0600`, then enable the API, web, and backup timer units.
6. Replace `TAILSCALE_IP` in the Nginx template after the device joins the user's tailnet.

OpenD is installed separately under `/opt/trading-assistant/opend`. Keep its XML configuration mode `0600`, leave the service disabled until login/device verification succeeds, and never expose port `11111` beyond loopback.

Do not add a wildcard Nginx listener or public firewall rule for this application.
