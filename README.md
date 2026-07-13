# OpenStock Personal Decision Desk

OpenStock Personal Decision Desk is a single-user portfolio review tool. It turns confirmed holdings, fresh quotes, deterministic risk rules, and optional public-news explanations into a short decision inbox.

It does not place orders. Every order draft is non-executable and must be copied into the broker manually.

## Product Flow

- **Decision** shows at most three current actions, their triggers, invalidation conditions, expiry, evidence, and data quality.
- **Holdings** keeps original-currency values and adds a clearly marked CNY estimate and concentration view.
- **Opportunities** separates watchlist ideas from portfolio risk decisions and reads its ordered symbols from the persistent watchlist database.
- **Settings** controls the full-analysis interval and whether US premarket, regular sessions, and US after-hours participate in scheduled analysis.
- Screenshot, CSV, and XLSX imports are previewed and edited before they become the active portfolio snapshot.
- Feedback records `executed`, `snoozed`, or `rejected`; it never silently changes the strategy.

Any portfolio snapshot older than 24 hours makes exact quantities non-actionable. API quotes up to 30 minutes old may support intraday monitoring, and a recent closed-market quote may support reference-only risk review. Concrete limit drafts require a quote no more than two minutes old with valid bid and ask. Missing OpenD, Finnhub, model, or news services are shown as degraded instead of being hidden.

## Architecture

- Next.js 15 / React 19 frontend in `frontend/openstock`
- FastAPI API in `src/trading_assistant`
- SQLite + SQLAlchemy + Alembic persistence
- Futu OpenD as the primary quote source and Finnhub as fallback
- APScheduler risk monitoring every 15 minutes plus configurable full analysis during enabled market sessions (120 minutes by default)
- Market-session detection for A-share, Hong Kong, and US regular trading, with DST-aware US premarket and after-hours controls
- Optional OpenAI-compatible explanation layer that cannot alter actions, prices, weights, quantities, priorities, or expiry

The imported OpenStock frontend remains AGPL-3.0 licensed. Its original authorship and license are retained in `frontend/openstock/LICENSE` and `frontend/openstock/README.md`.

## Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item configs\local.env.example configs\local.env
python -m alembic upgrade head
trading-assistant-api
```

In a second terminal:

```powershell
cd frontend\openstock
npm install
Copy-Item .env.example .env.local
npm run dev
```

Open `http://localhost:3000`. API health is available at `http://127.0.0.1:8765/health`.

## Opportunity Watchlist Sync

The durable source for the Opportunities page can be any local Markdown file whose latest `### ... Active Watchlist` section contains the ordered symbols and rationales. Theme priorities and removed or deprioritized symbols are intentionally excluded.

After changing that section, run:

```powershell
$env:WATCHLIST_SOURCE_PATH = 'C:\path\to\private-finance-notes.md'
$env:TRADING_ASSISTANT_SSH_HOST = 'user@private-host'
$env:TRADING_ASSISTANT_SSH_KEY = "$HOME\.ssh\private-key"
.\scripts\sync-opportunity-watchlist.ps1
```

The script validates the Markdown, sends only the structured watchlist over SSH, atomically replaces the remote SQLite rows, and prints the resulting `count` and `symbols`. A parse or network failure leaves the previous watchlist intact and does not require a service restart. The repository ships only a synthetic demonstration portfolio; real snapshots, account values and deployment credentials must remain in ignored runtime storage.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest
cd frontend\openstock
npx tsc --noEmit
npm run lint
npm test
npm run build
```

## Server Layout

Production is designed for native systemd services without Docker:

- Next standalone: `127.0.0.1:3100`
- FastAPI: `127.0.0.1:8765`
- Futu OpenD: `127.0.0.1:11111`
- private Nginx entry bound only to the server's Tailscale address
- data and backups under `/var/lib/trading-assistant`
- secrets in `/etc/trading-assistant/trading-assistant.env` with mode `0600`

Deployment templates are in `deploy/`.

## Safety Boundary

Deterministic code owns risk limits, weights, quantities, and draft construction. The explanation model receives only symbols, percentages, rule output, price changes, and public evidence; it does not receive account identifiers or full account value. With explicit user consent, screenshot imports may be compressed in memory and sent to the configured vision-capable model for confirmation-preview extraction only; they are not persisted, and local OCR remains the provider-failure fallback.

This software is a personal review aid, not investment advice or a brokerage service.
