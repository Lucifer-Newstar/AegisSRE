# order-service

AegisShop checkout service, port 9003. Contract: `docs/contracts/order-service.yaml`.

Compose and kind set `SHOP_DATABASE_URL` to a separate `shop-postgres` server,
not the platform incident/evidence store. Successful orders are committed before
the API returns 201 and survive application restarts. Database failure returns
503 from order requests and `/ready`, while `/health` stays live. Cart transport
failure is 503, an actual empty cart remains 400. Startup/reconnection never
clears orders.

Without configuration, SQLite in-memory is an explicit single-process developer
default only. To retain local orders use a file URL such as
`sqlite:////tmp/aegisshop-orders.db`, or configure `postgresql+psycopg`.
No real payment is performed. No retry/idempotency-key checkout contract is
claimed; a caller retry after a lost response can create a second order.

Native tests cover file-backed restart persistence, bound queries, failure
responses and closed-port PostgreSQL connection failure. Successful actual
PostgreSQL restart/outage proof belongs to the hosted owned-kind gate.
