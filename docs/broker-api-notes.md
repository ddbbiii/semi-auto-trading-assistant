# Broker API Notes

## Futu / Moomoo

Both Futu OpenAPI and Moomoo OpenAPI use a local OpenD gateway.

Python packages:

- `futu-api`, imported as `futu`
- `moomoo-api`, imported as `moomoo`

Do not store account credentials in this repository.

## First-Phase Policy

The first adapter implementation should support read-only operations first:

- quote snapshots,
- holdings,
- cash,
- open orders.

Trading should remain disabled until paper trading and audit logging are stable.

## Brokers Without An Official Retail API

Do not reverse engineer a broker application or assume that a private API is
safe to automate. The supported integration target is:

- generate validated order drafts and checklists,
- make the user manually place the order in their broker,
- log user approval and intended order details,
- record actual order/fill results manually or from exported/account data,
- never automate the app UI or submit orders through unofficial/private APIs
  without explicit review.
