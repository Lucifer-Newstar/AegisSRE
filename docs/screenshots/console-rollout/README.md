# Rollout analytics visual check

`fixture.png` shows an authored synthetic HTTP fixture, not live platform data or
a real faulty deployment. Captured by `scripts/visual/console-fixture.mjs` after
a production Next build. Inspected for layout, readable labels, null CFR as
Unknown, missing flag latency and distinction between producer phase and
observed window. Actual owned-kind capture remains required before merge.
