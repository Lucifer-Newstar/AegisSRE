# Request-SLO observability foundation

The shared Prometheus config defines a versioned **demo request-success objective
of 99.9%**, independent of editable service-registry objectives. It is not a
claim of measured uptime. Four shop services get observed 5-minute/1-hour error
ratios and burn rates. A fast-burn alert requires both windows above 14.4x for
2 minutes. Missing/zero request traffic yields no SLO verdict. A zero 5xx
numerator is filled only when real positive request traffic exists.

The provisioned Grafana dashboard shows observed request success, both burn
windows and traffic. It does not invent a 30-day error budget remaining. Early
stacks have partial rolling-window coverage and are labeled accordingly.

Validation is deliberately separate:

- Actual Prometheus 2.53 `promtool` parses the rules and evaluates normal,
  sustained-error and zero-traffic fixtures. CI runs the same checks.
- The owned-kind gate must query running rule health, an actual catalog burn
  series and the provisioned Grafana dashboard. This must pass before merge.
- The dashboard still needs pixel inspection from the actual running Grafana UI.
  JSON/provisioning success is not visual acceptance.
- A real chaoslab alert firing/restoration scenario and a supported full-window
  budget calculation remain. D6 is not complete from these fixtures or panels.

No alert authorizes remediation, and no missing series is treated as healthy.
