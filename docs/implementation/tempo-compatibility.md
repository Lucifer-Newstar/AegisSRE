# Tempo trace identifier compatibility

The collector accepts strict 32-character hexadecimal IDs or 16-byte base64 IDs
from OTLP trace bodies and logs. Tempo search is a separate format: its search
metadata can omit leading zeroes. Only that fixed response field is validated as
1..32 hex digits, then left-padded before lookup and correlation. It does not
relax URL/path validation or other identifier parsing.

A regression test covers a zero-prefixed trace found through trimmed search
metadata, full trace lookup and the stable canonical evidence identifier.

Upstream compatibility evidence, inspected November 23, 2026:
https://github.com/grafana/tempo/issues/5395

This is a confirmed protocol incompatibility in our parser. Earlier retained
collector failures were recorded only as `Error`; those records alone do not
prove this was their cause. Precise failure classes and bounded convergence
remain in the fixture checks. A passing rerun is required, not assumed.
