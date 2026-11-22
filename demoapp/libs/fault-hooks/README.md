# AegisShop demo fault hooks

This library is used only by the four shop services. It adds no HTTP control
route. Faults are disabled unless `AEGIS_SHOP_FAULTS_ENABLED=true` is present when
the app is assembled. The default Compose and kind workload configuration does
not enable them. A future isolated experiment runner writes a bounded local
control file, never an HTTP request header/body/query.

The file path is fixed at `/tmp/aegisshop-fault.json`. Only a regular non-symlink
file of at most 1024 bytes is accepted, with exactly kind/until/magnitude fields.
Future expiry is bounded to ten minutes. Unsupported, malformed, stale, oversized
or unsafe file state injects nothing. Removing the file restores future requests;
already-running bounded work finishes. Health/readiness/metrics/docs bypass the
hook. Control files are not telemetry and no fault labels are added to responses.

Implemented hook primitives are HTTP 503, actual request-boundary delay, bounded
CPU work, and bounded memory pressure. CPU/memory work is serialized and capped.
Delay is an application-boundary effect, not packet-level network shaping.
Memory pressure is not memory exhaustion/OOM. These distinctions remain open
acceptance work, not alternate names for the missing experiments.

Native tests check opt-in, no HTTP control route, actual failure/delay, expiry,
restoration and malformed/symlink/FIFO/size rejection. They do not establish the
A11 CLI, ten fault coverage, real cluster injection/restoration or research
accuracy/MTTR. The experiment runner and actual-cluster proof remain to build.
