# Architecture

## Product Boundary

The assistant is a supervised decision-support and execution tool.

It should never submit an order without explicit user approval and a fresh
post-approval risk check.

## Layers

1. Data adapters: read quotes, holdings, cash, and open orders where an official
   API exists. Futu OpenD is supported for available markets; brokers without a
   documented retail API remain manual import and execution venues.
2. Market state: normalize broker data into local domain objects.
3. Signal layer: trend, relative strength, volatility sizing, support/resistance,
   add lines, stop lines, and warrant expiry alerts.
4. Risk layer: deterministic hard gates.
5. Draft layer: creates human-readable order drafts.
6. Approval layer: user approval with a short validity window.
7. Execution layer: limit orders only when an official supported trading API is
   available. Until then, generate broker-neutral execution checklists and
   record manual order outcomes.
8. Audit layer: append-only review trail keyed by `order_intent_id`.

## Rollout

1. Data and position sync.
2. Alerts and signals.
3. Order drafts.
4. Paper trading.
5. Manual broker execution checklist with post-trade logging.
6. Small real-money stock/ETF limit orders only if a supported official trading
   API is later confirmed.
7. Warrants/CBBCs only after stricter controls and audit history.
