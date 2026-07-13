# OpenStock Decision Desk Frontend

This directory contains the Next.js frontend for the personal investment decision desk. The current product has three routes: Decision, Holdings, and Opportunities.

The code is derived from [OpenStock by Open Dev Society](https://github.com/Open-Dev-Society/OpenStock). The original AGPL-3.0 license and attribution are retained in `LICENSE`. Modified source must continue to satisfy the AGPL-3.0 obligations when deployed or redistributed.

```bash
npm install
npm run dev
npm run lint
npm test
npm run build
```

For local development set `NEXT_PUBLIC_TRADING_ASSISTANT_API_URL=http://127.0.0.1:8765`. Production uses same-origin `/api/v1` through Nginx and emits a Next standalone build.
