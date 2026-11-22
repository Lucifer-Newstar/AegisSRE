# cart-service

AegisShop cart service, port 9002. Contract: `docs/contracts/cart-service.yaml`.

Compose/kind configure `SHOP_REDIS_URL` to separate `shop-redis`, never the
platform event-stream server. Carts use atomic Redis hash quantity increments
and AOF persistence. The fixed demo catalogue determines unit prices.
Redis failure returns 503 from `/ready` and cart operations, not an empty cart;
`/health` stays live. Empty URL enables the standalone developer-only local
store. There is no write fallback during an outage and startup never clears data.
The test reset helper refuses to flush configured Redis. No idempotency-key
contract is claimed for client retries after an uncertain write response.

Hosted owned-kind CI must prove the same cart survives application restart and
an actual shop Redis outage/restoration without taking down platform transport.
Native mock and closed-port tests do not establish successful Redis persistence.
