# Request-SLO evidence panel

The service page reads a fixed authenticated SLO API. The objective is the
versioned99.9% request-success objective used by Prometheus rules, independent of
editable registry objectives. Burn queries expose actual5m/1h-selector values
with source expressions. A fresh server can have values without complete window
coverage, and the panel says so.

The30d budget is withheld unless sufficient successful15s scrapes and request
counter samples cover the full expected count, data is fresh, and a positive
request denominator and bounded error count exist. This intentionally returns
unknown on a fresh CI cluster. Tests cover missing/partial/failed scrapes, missing
counters, stale data and zero traffic. Actual hosted API checks require that
honest partial state alongside the observed burn. This is not a guarantee of
retention, zero scrape jitter or production-grade accounting across changing
scrape topology. No execution permission is returned.
