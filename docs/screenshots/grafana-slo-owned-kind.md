# Observed SLO dashboard

`grafana-slo-owned-kind.png` is an actual Grafana capture from the disposable
owned-kind integration gate, not a rendered fixture or mock API.

- Source head: `5c5981de3dc6ff084d4dbbcea69445a60caef257`.
- Run: https://github.com/Lucifer-Newstar/AegisSRE/actions/runs/45072737154/job/137363120407
- Captured by `scripts/visual/grafana.mjs`; manually inspected after download.
- Success-axis range is 0..100%. Panels, labels and measurement limits are
  readable without overlap. The fixture has only a short telemetry history.
- This image demonstrates the actual provisioned dashboard, not full-window
  SLO compliance, alert firing under a real fault or evaluation acceptance.
