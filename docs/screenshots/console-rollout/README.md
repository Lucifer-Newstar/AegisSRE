# Rollout analytics visual check

`fixture.png` shows an authored synthetic HTTP fixture, not live platform data or
a real faulty deployment. Captured by `scripts/visual/console-fixture.mjs` after
a production Next build. Inspected for layout, readable labels, null CFR as
Unknown, missing flag latency and distinction between producer phase and
observed window. Actual owned-kind capture remains required before merge.

`owned-kind.png` is the actual running console against the owned platform APIs.
Source head: `1d4aab23c0ac820b9ebdd288c7f6fede446ec476`.
Run: https://github.com/Lucifer-Newstar/AegisSRE/actions/runs/45074221444/job/137367730104
Inspected actual pixels: readable labels, unknown CFR/coverage when identity is
incomplete, insufficient window separated from producer succeeded, no invented
flag latency. This screenshot is not a faulty-deployment evaluation result.
