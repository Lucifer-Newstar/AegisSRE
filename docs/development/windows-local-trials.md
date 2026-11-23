# Windows16GB local trial setup

Status: local-owned path prepared, not yet tested on Navin's laptop. Do not treat
passing CI/unit tests as a completed local comparison or capacity guarantee.

## One-time checks

1. Docker Desktop must be running Linux containers using WSL2. In PowerShell,
   check `wsl --version`, `wsl -l -v` and `docker info`. The Ubuntu distribution
   should use version2. Enable hardware virtualization if Docker reports it missing.
2. Use the WSL2 Ubuntu shell for this runbook. Install Git and Python3.12 with venv
   support. Keep the checkout in the Linux home directory, not `/mnt/c`.
3. Starting allocation for a16GB laptop: Docker/WSL at least8GiB RAM and4CPUs,
   at least30GiB free in its Linux filesystem. Close heavy apps and run one trial
   at a time. Actual sustained usage must be checked during the first smoke.
   The4GB GPU is not needed. Do not install a model or GPU inference runtime.
4. Docker Desktop's built-in Kubernetes is not needed. The wrapper creates its
   own disposable single-node kind cluster, not an existing personal cluster.

Official setup sources:
[Docker Windows](https://docs.docker.com/desktop/setup/install/windows-install/),
[WSL2 backend](https://docs.docker.com/desktop/features/wsl/),
[kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/).

## Prepare the owned cluster

From the clean committed checkout in WSL2:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/local_evaluation.py check
python scripts/local_evaluation.py prepare
python scripts/local_evaluation.py up
python scripts/local_evaluation.py hooks
python scripts/local_evaluation.py status
```

`check` is read-only. `prepare` records a fresh local owner and downloads the
checksum-pinned Linuxamd64 kind/kubectl from the repository pins. `up` builds the
application/faulty images and creates only the new `aegis-local-eval` cluster.
No paid/cloud resources are used. Image/tool downloads use bandwidth and disk.
The default development credentials are disposable and publicly known. Never
expose the cluster/services to an untrusted network or use production data.

State lives in `~/.local/state/aegissre-evaluation`. The wrapper rejects remote
Docker endpoints, insufficient starting resources, an existing named node or
existing local owner state. It records the new Docker node ID and rechecks it
before cluster operations. It uses an explicit private kubeconfig and context;
it does not select or modify the ambient context. Do not fake CI environment
variables, edit ownership markers or bypass a mismatch. Stop and inspect it.

## One bounded capture smoke before observer sessions

```sh
export AEGIS_LOCAL_EVALUATION=1
python -m evaluation.capture freeze /tmp/aegis-local-manifest.json --corpus docs/operations
python -m evaluation.capture trial /tmp/aegis-local-manifest.json /tmp/aegis-local-smoke \
  --fault http-5xx --seconds 5
```

The frozen corpus in this example is not claimed to be reviewed held-out truth.
Start with this one smoke, not thirty trials. Inspect actual resource use with
`docker stats --no-stream`, Pod health, request responses and restoration before
proceeding. A Pod restart can break a forward, and such read errors remain in the
capture. Control-runner cleanup must never count as Aegis recovery.

The30-pair small-sample profile is a separate approved evaluation change, not
implied by this smoke. Actual manual observer identity, schedule, reviewed truth
and observed manual response must still be recorded. No simulated human delays.
Do not run the comparative cohort until both observer and independent review
procedures are ready.

## Stop only this owned cluster

```sh
python scripts/local_evaluation.py down
```

This deletes only the node whose name and recorded ID both match the newly owned
local cluster. It never runs `docker system prune` or deletes other clusters.
Local logs and identity state are retained for inspection. A subsequent fresh
session must use a deliberate reviewed reset; automatic takeover is not supported.
If setup is interrupted, stop and inspect ownership/node state before retrying.

## Fresh baseline between comparative workflows

Do not reuse the preceding workflow's database/detector history or cooldowns.
After preserving its output outside the state directory and checking cleanup,
explicitly reset only this newly owned local fixture:

```sh
python scripts/local_evaluation.py reset --confirm-owned-reset
```

This is destructive to this disposable cluster, not to other clusters or Docker
images. It rechecks the owner and exact Docker node ID, refuses active/stale trial
locks, checks clean source and binary checksums, collects diagnostics and deletes
only the matching node. It archives the entire old state directory next to the
fresh one, with a unique archive name, rather than overwriting prior evidence.
It then creates a new owner/node, new databases/PVCs, fresh telemetry/history,
the same fault hooks and restricted executor in observe mode. It does not seed
an incident or change policy. Images are reused, not rebuilt. Keep all archives.

Run the same fresh-baseline procedure before BOTH workflows, including the first
workflow of a study, then recheck health/resources and use the same warm-up. New
UIDs are expected. Configuration/hardware/image and load equivalence must still
be reviewed. Do not copy whole-environment digests across pairs just because the
command finished; record the actual evidence and the equivalence review.

A fresh cluster costs several minutes per workflow in addition to session time.
Sixty workflows with isolated resets can take much of a day or longer on the
actual laptop. Run a single smoke/reset first and use its observed duration to
plan the cohort. No fixed completion estimate is certified here. If interrupted,
inspect retained identity/node/logs; do not remove locks or ownership records to
force it onward. The reset is unit-tested but still needs actual local validation.
