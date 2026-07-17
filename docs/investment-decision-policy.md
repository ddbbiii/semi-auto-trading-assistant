# Investment Decision Policy

OpenStock uses one deterministic policy for portfolio review. The canonical machine-readable source is
`src/trading_assistant/investment_policy.py`; the settings page exposes the same payload through
`GET /api/v1/settings/investment-policy`.

## Global policy and optional overrides

The canonical global policy applies to every active holding. A symbol does not become unanalyzable merely
because it has no custom profile. Per-symbol profiles are optional overrides for facts or constraints that are
truly specific to one instrument, such as a target weight, tactical price line, derivative expiry or thesis
invalidation condition.

An optional symbol profile can store:

- investment thesis summary;
- information grade (`A`, `B`, `C`) and separate research-confidence / investment-certainty fields;
- strongest bear case;
- bear, base and bull scenarios;
- buy/add, reduce and exit/invalidation conditions;
- position intent (`long_term`, `tactical`, `derivative`);
- optional price review line, target weight and derivative expiry.

Information grades are evidence provenance, not trade signals. Grade A covers filings, exchange or regulator
records and formal product terms. Grade B covers independently verifiable market data or reputable secondary
sources. Grade C is an unverified lead and can only trigger further research.

## Deterministic behavior

- A concentration threshold is a review reminder, not a target weight and not an automatic reduction.
- An abnormal move first requires event attribution: value event, sentiment/liquidity, mixed or unexplained.
- A long-term stock crossing a price line defaults to review, stop-adding or a reduction check. It never creates
  a mechanical full-exit draft.
- A hard price exit is reserved for warrants/CBBCs or a user-confirmed tactical stop.
- Being below target weight is insufficient to add. A current user-confirmed buy/add condition and valid data are
  both required; concrete quantity additionally requires an execution-ready quote.
- The latest user-confirmed position snapshot remains the baseline until the user reports a holding change or
  confirms a replacement snapshot. Elapsed time alone never creates an account-sync decision.
- Missing evidence, an explicitly reported but unreconciled holding change, or unreliable quotes may produce
  `verify`. The engine does not force a buy or sell conclusion when the inputs are incomplete.
- Clearing a position deactivates an optional profile. Buying the same symbol later does not silently reactivate
  old overrides, while the global policy continues to apply.

## Four response levels

1. `review`: collect evidence and reassess risk/reward.
2. `stop_adding`: keep the position but do not increase exposure.
3. `reduce`: check user-confirmed reduction conditions before lowering exposure.
4. `exit`: use only for thesis invalidation, derivative hard constraints or an explicit tactical stop.

## Model boundary

The optional LLM receives only sanitized symbols, ratios, deterministic results and public evidence summaries.
It may rewrite `title` and `summary` for clarity. It cannot modify the action, response level, priority, quantity,
price, trigger, current limitation, invalidation condition or evidence grades.

This policy supports research and review only. It does not submit orders and is not investment advice.
