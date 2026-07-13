# OpenStock Frontend Integration

OpenStock is vendored under `frontend/openstock` as the first reusable web UI
for the semi-automated trading assistant.

Upstream: https://github.com/Open-Dev-Society/OpenStock

License: AGPL-3.0. Keep `frontend/openstock/LICENSE` and upstream attribution.
If a modified version is redistributed or exposed as a hosted web service,
review AGPL source-code obligations before launch.

## Current Role

Use OpenStock as the browser UI shell for:

- the decision inbox,
- confirmed holdings and concentration,
- opportunity watchlists,
- analysis and user risk-rule settings.

It is not the execution engine. The Python package remains responsible for
deterministic risk controls, order-draft generation, broker abstractions, and
audit logging.

## Local Requirements

- Node.js 20+; this machine verified `v22.14.0`
- npm; this machine verified `10.9.2`
- the FastAPI service listening on `127.0.0.1:8765`
- optional Futu OpenD, Finnhub, email and OpenAI-compatible credentials

## Minimal Local Environment

Create `frontend/openstock/.env.local` locally. Do not commit it.

```dotenv
NEXT_PUBLIC_TRADING_ASSISTANT_API_URL=http://127.0.0.1:8765
```

Run the frontend:

```powershell
cd frontend\openstock
npm install
npm run dev
```

Open http://localhost:3000.

## Verification

Verified locally after vendoring:

```powershell
npm test
npm run build
```

Run `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build`, and
`npm audit` before publishing a release.

## Integration Boundary

Keep these boundaries:

- OpenStock handles pages, charts, watchlists, and browser UX.
- Python backend handles holdings sync, deterministic risk checks, order drafts,
  execution checklists, and audit records.
- LLM output may explain signals, but must not bypass risk controls or submit
  orders.
- Any broker without an official supported trading API remains a manual
  execution venue.

## Planned Adaptation Steps

1. Add a Python API layer for holdings, risk status, order drafts, and audit
   history.
2. Add an OpenStock page or panel for "Assistant" using the Python API.
3. Read watchlists from the local persistent database.
4. Add manual execution workflow: generate draft, show risk checks, user
   executes in a broker, then record the result.
5. Revisit Finnhub/TradingView coverage for Hong Kong warrants and CBBCs; do
   not assume reliable minute-level warrant data from OpenStock.
