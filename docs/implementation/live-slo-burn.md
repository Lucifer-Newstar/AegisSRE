# Live HTTP error burn proof

The full owned-kind gate injects the actual opt-in HTTP503 fault for120 seconds,
sends real products requests, then inspects Prometheus for a firing
`AegisShopRequestErrorBudgetFastBurn` alert and the actual recorded burn series.
The unchanged rule must spend two minutes pending before firing. The CLI restores
the fault control and a separate request must return200. Diagnostics retain the
journal, response counts, alert labels/state/timing and query sample.

A fresh runner has less than one hour of history. The1h selector can still produce
a value from available observations; this proof is not complete1h coverage, a
long-window budget measurement or acceptance accuracy. Missing/zero traffic is
not healthy. Alert resolution is not inferred from domain recovery because the
rate window can continue to burn after the fault ends.
