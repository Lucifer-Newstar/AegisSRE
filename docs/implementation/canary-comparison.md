# Read-only canary comparison

The authenticated API and deployments console compare separately scraped stable
and canary tracks for catalog products requests. Queries and origin are fixed by
operator configuration, not request-supplied expressions or URLs. Each track must
have100 observed requests, complete error/latency data and fresh scrape samples.
Missing, stale, non-finite, duplicate or partial query data is insufficient or
unavailable, never healthy. Comparison thresholds are versioned in code and
returned with the result. No regression observed is not permission to release.

The owned-kind gate creates new normal and faulty catalog deployments/services,
adds temporary explicit scrape labels, sends direct traffic to both, and verifies
normal200 versus faulty503 independently of Prometheus. It checks an observed
regression through the real authenticated API and captures actual console pixels.
Cleanup removes only newly created resources and restores the exact Prometheus
configuration. This fixture uses approximately equal direct traffic, not a
production weighted-routing system or research evaluation accuracy.
