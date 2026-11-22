#!/usr/bin/env python3
"""Full platform proof in a newly owned, disposable GitHub-runner kind cluster.

Never selects an ambient context or reuses an existing cluster. No model inference
or real remediation is enabled. Data is retained across Pod/application restart,
then destroyed only with this fixture's own cluster at cleanup.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
NAME = "aegis-platform"
NS = "aegissre-demo"
APPS = [
    "catalog-service",
    "cart-service",
    "order-service",
    "payment-service",
    "registry-service",
    "deployments-service",
    "incidents-service",
    "api-gateway",
    "console",
]
FIXTURE = {
    "AEGIS_API_TOKEN": "ci-disposable-runtime-token",
    "AEGIS_METADATA_API_TOKEN": "ci-disposable-metadata-operator",
    "AEGIS_METADATA_READ_TOKEN": "ci-disposable-metadata-reader",
}


def directory() -> Path:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("RUNNER_TEMP"):
        raise RuntimeError("Only a disposable GitHub runner may use this fixture")
    base = Path(os.environ["RUNNER_TEMP"]) / "aegis-kind-platform"
    base.mkdir(parents=True, exist_ok=True)
    return base


def owner() -> str:
    return ":".join(
        os.environ[key] for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")
    )


def owned() -> bool:
    marker = directory() / "owned"
    return marker.is_file() and marker.read_text() == owner()


def run(
    args: list[str], *, capture: bool = False, timeout: int = 180, body: str | None = None
) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        env={**os.environ, **FIXTURE},
        input=body,
        text=True,
        check=True,
        capture_output=capture,
        timeout=timeout,
    )
    return result.stdout if capture else ""


def kubectl(*args: str, capture: bool = False, timeout: int = 180, body: str | None = None) -> str:
    if not owned():
        raise RuntimeError("Refusing an unowned cluster")
    base = directory()
    return run(
        [
            str(base / "bin/kubectl"),
            "--kubeconfig",
            str(base / "kubeconfig"),
            "--context",
            "kind-" + NAME,
            *args,
        ],
        capture=capture,
        timeout=timeout,
        body=body,
    )


def install() -> None:
    base = directory()
    pins = json.loads((ROOT / "infra/kind/ci-versions.json").read_text())
    for tool in ("kind", "kubectl"):
        url, digest = str(pins[tool + "_url"]), str(pins[tool + "_sha256"])
        prefix = (
            "https://github.com/kubernetes-sigs/kind/releases/download/"
            if tool == "kind"
            else "https://dl.k8s.io/release/"
        )
        if not url.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid tool pin")
        target = base / "bin" / tool
        target.parent.mkdir(exist_ok=True)
        data = bytearray()
        with urllib.request.urlopen(url, timeout=60) as response:
            while chunk := response.read(65536):
                data.extend(chunk)
                if len(data) > 120_000_000:
                    raise ValueError("Tool download exceeds bound")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Tool checksum mismatch")
        target.write_bytes(data)
        target.chmod(0o755)
    run([str(base / "bin/kind"), "version"])
    run([str(base / "bin/kubectl"), "version", "--client"])


def images() -> dict[str, str]:
    # Read only image identities from the resolved config. Never log raw config.
    services = json.loads(run(["docker", "compose", "config", "--format", "json"], capture=True))[
        "services"
    ]
    return {name: str(service["image"]) for name, service in services.items()}


def build() -> None:
    directory()
    run(["docker", "compose", "build", *APPS], timeout=1200)
    run(["docker", "build", "-f", "chaoslab/images/catalog-faulty.Dockerfile",
         "-t", "aegisshop/catalog-service:ci-faulty", "."], timeout=240)


def create() -> None:
    base = directory()
    binary = str(base / "bin/kind")
    if NAME in run([binary, "get", "clusters"], capture=True).splitlines():
        raise RuntimeError("Refusing to adopt or delete a pre-existing cluster")
    node = str(json.loads((ROOT / "infra/kind/ci-versions.json").read_text())["node_image"])
    if not re.fullmatch(r"kindest/node:v[0-9.]+@sha256:[0-9a-f]{64}", node):
        raise ValueError("Require a digest-pinned kind node")
    run(
        [
            binary,
            "create",
            "cluster",
            "--name",
            NAME,
            "--image",
            node,
            "--kubeconfig",
            str(base / "kubeconfig"),
            "--wait",
            "180s",
        ],
        timeout=300,
    )
    (base / "owned").write_text(owner())
    selected = images()
    run(
        [binary, "load", "docker-image", *(selected[name] for name in APPS), "--name", NAME],
        timeout=600,
    )
    run([binary, "load", "docker-image", "aegisshop/catalog-service:ci-faulty",
         "--name", NAME], timeout=120)
    kubectl("create", "namespace", NS)
    secrets = {
        "aegissre-console": {"session-secret": "ci-disposable-console-session-secret-value"},
        "aegisshop-postgres": {
            "username": "shop", "password": "ci-disposable-shop", "database": "aegisshop"
        },
        "aegisshop-database": {
            "url": "postgresql+psycopg://shop:ci-disposable-shop@shop-postgres:5432/aegisshop"
        },
        "aegissre-postgres": {
            "username": "aegis",
            "password": "ci-disposable-database",
            "database": "aegissre",
        },
        "aegissre-database": {
            "url": "postgresql+psycopg://aegis:ci-disposable-database@postgres:5432/aegissre"
        },
        "aegissre-metadata": {
            "api-token": FIXTURE["AEGIS_METADATA_API_TOKEN"],
            "read-token": FIXTURE["AEGIS_METADATA_READ_TOKEN"],
        },
        "aegissre-operator": {
            "token": FIXTURE["AEGIS_API_TOKEN"],
            "incidents-token": FIXTURE["AEGIS_API_TOKEN"],
        },
        "aegissre-grafana": {"username": "admin", "password": "ci-disposable-grafana"},
    }
    for name, values in secrets.items():
        document = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": name, "namespace": NS},
            "type": "Opaque",
            "stringData": values,
        }
        kubectl("apply", "-f", "-", body=json.dumps(document))
    kubectl("apply", "-k", str(ROOT / "infra"))
    for kind, name in [
        ("statefulset", "postgres"),
        ("statefulset", "shop-postgres"),
        ("statefulset", "redis"),
        ("statefulset", "shop-redis"),
        *[
            ("deployment", name)
            for name in [*APPS, "prometheus", "grafana", "loki", "tempo", "otel-collector"]
        ],
    ]:
        kubectl(
            "rollout", "status", kind + "/" + name, "--namespace", NS, "--timeout=300s", timeout=320
        )
    print("All eighteen actual platform/workload Pods rolled out in the fixture-owned cluster")


class Forwards:
    def __init__(self) -> None:
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.files: list[Any] = []

    def start(self, name: str, local: int, remote: int) -> None:
        self.stop(name)
        base = directory()
        output = (base / ("forward-" + name + ".log")).open("a")
        self.files.append(output)
        command = [
            str(base / "bin/kubectl"),
            "--kubeconfig",
            str(base / "kubeconfig"),
            "--context",
            "kind-" + NAME,
            "port-forward",
            "--namespace",
            NS,
            "--address",
            "127.0.0.1",
            "service/" + name,
            str(local) + ":" + str(remote),
        ]
        self.processes[name] = subprocess.Popen(
            command, stdout=output, stderr=subprocess.STDOUT, text=True
        )

    def stop(self, name: str) -> None:
        process = self.processes.pop(name, None)
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

    def close(self) -> None:
        for name in list(self.processes):
            self.stop(name)
        for output in self.files:
            output.close()


def verify() -> None:
    if not owned():
        raise RuntimeError("Refusing an unowned cluster")
    sys.path.insert(0, str(ROOT))
    os.environ.update(FIXTURE)
    from scripts.check_gateway_stack import request
    from scripts.check_runtime_stack import api, wait_for

    forwards = Forwards()
    try:
        for name, local, remote in [
            ("incidents-service", 8201, 8201),
            ("api-gateway", 8080, 8000),
            ("registry-service", 8101, 8101),
            ("deployments-service", 8701, 8701),
            ("redis", 6379, 6379),
            ("catalog-service", 9001, 9001),
            ("console", 3030, 3030),
            ("order-service", 9003, 9003),
            ("cart-service", 9002, 9002),
            ("prometheus", 19090, 9090),
            ("grafana", 13000, 3000),
        ]:
            forwards.start(name, local, remote)
        wait_for(
            lambda: request("/api/v1/ready")["status"] == "ready",
            "actual in-cluster gateway readiness",
            seconds=120,
        )

        def restart_api() -> None:
            consumer = api("/runtime")["delivery_consumer"]
            kubectl("rollout", "restart", "deployment/incidents-service", "--namespace", NS)
            kubectl(
                "rollout",
                "status",
                "deployment/incidents-service",
                "--namespace",
                NS,
                "--timeout=180s",
                timeout=200,
            )
            forwards.start("incidents-service", 8201, 8201)
            wait_for(
                lambda: api("/ready")["status"] == "ready", "restarted in-cluster API", seconds=120
            )
            assert api("/runtime")["delivery_consumer"] != consumer

        run([sys.executable, str(ROOT / "scripts/check_runtime_stack.py"), "seed"], timeout=240)
        restart_api()
        run([sys.executable, str(ROOT / "scripts/check_runtime_stack.py"), "verify"], timeout=180)
        scripts = [
            ("check_gateway_stack.py",),
            ("check_observability_stack.py",),
            ("check_knowledge_stack.py",),
            ("check_intelligence_stack.py",),
            ("check_slo_stack.py",),
            ("check_deployment_windows_stack.py", "seed"),
        ]
        for command in scripts:
            run([sys.executable, str(ROOT / "scripts" / command[0]), *command[1:]], timeout=240)
        visual = directory() / "diagnostics" / "visual"
        run(["env", "AEGIS_VISUAL_OUTPUT=" + str(visual), "node",
             str(ROOT / "scripts/visual/grafana.mjs")], timeout=90)
        status = api("/runtime")["kubernetes"]
        assert status["enabled"] and status["succeeded_at"] and status["error"] is None, status
        assert status["health_verdict"] == "unknown"
        # Do not grant executor permissions to the evidence reader.
        subject = "system:serviceaccount:" + NS + ":aegissre-evidence"
        for verb, resource, namespace in [
            ("create", "pods", NS),
            ("create", "pods/exec", NS),
            ("patch", "deployments.apps", NS),
            ("get", "secrets", NS),
            ("list", "secrets", NS),
            ("list", "pods", "kube-system"),
        ]:
            result = subprocess.run(
                [
                    str(directory() / "bin/kubectl"),
                    "--kubeconfig",
                    str(directory() / "kubeconfig"),
                    "--context",
                    "kind-" + NAME,
                    "auth",
                    "can-i",
                    verb,
                    resource,
                    "--namespace",
                    namespace,
                    "--as",
                    subject,
                ],
                text=True,
                capture_output=True,
                timeout=30,
            )
            assert result.returncode == 1 and result.stdout.strip() == "no", (verb, resource)
        restart_api()
        run(
            [sys.executable, str(ROOT / "scripts/check_deployment_windows_stack.py"), "verify"],
            timeout=180,
        )
        # Delete only this fixture's Postgres Pod, not its PVC. Check the same
        # metadata envelope through HTTP after the StatefulSet recreates it.
        kubectl("delete", "pod", "postgres-0", "--namespace", NS, "--wait=true", timeout=90)
        wait_for(
            lambda: (
                api("/deployments/ci-runtime-deploy", port=8701)["revision"]
                == "ci-observed-revision"
            ),
            "actual Postgres PVC data after Pod replacement",
            seconds=180,
        )
        wait_for(
            lambda: request("/api/v1/ready")["status"] == "ready",
            "platform reconnection after Postgres replacement",
            seconds=120,
        )
        records = api("/services", port=8101)
        for service_name in ("registry-service", "deployments-service"):
            row = next(item for item in records if item["id"] == service_name)
            assert row["status"] == "healthy" and row["last_heartbeat_at"], row
        print("Actual authenticated built-in metadata readiness probes passed; arbitrary endpoints receive no credential")
        # Real shop data and dependency failure, isolated from platform storage.
        from scripts.check_shop_stack import request as shop_request
        from scripts.check_shop_stack import retained, seed, unavailable

        wait_for(lambda: shop_request(9003, "/ready")[0] == 200, "shop DB readiness", 120)
        order = seed()
        kubectl("rollout", "restart", "deployment/order-service", "--namespace", NS)
        kubectl("rollout", "status", "deployment/order-service", "--namespace", NS,
                "--timeout=180s", timeout=200)
        forwards.start("order-service", 9003, 9003)
        wait_for(lambda: retained(order), "order retained across actual application restart", 120)
        try:
            kubectl("scale", "statefulset/shop-postgres", "--replicas=0", "--namespace", NS)
            kubectl("wait", "--for=delete", "pod/shop-postgres-0", "--namespace", NS,
                    "--timeout=90s", timeout=100)
            wait_for(unavailable, "actual shop DB outage gives readiness/domain 503", 90)
            assert request("/api/v1/ready")["status"] == "ready"
            assert api("/deployments/ci-runtime-deploy", port=8701)["revision"] == "ci-observed-revision"
        finally:
            kubectl("scale", "statefulset/shop-postgres", "--replicas=1", "--namespace", NS)
        wait_for(lambda: shop_request(9003, "/ready")[0] == 200 and retained(order),
                 "same persisted order after actual shop database restoration", 180)
        print("Actual shop order survived app restart and isolated database outage/restoration; platform stayed ready")
        cart_before = shop_request(9002, "/cart/ci-persistent-order")[1]
        kubectl("rollout", "restart", "deployment/cart-service", "--namespace", NS)
        kubectl("rollout", "status", "deployment/cart-service", "--namespace", NS,
                "--timeout=180s", timeout=200)
        forwards.start("cart-service", 9002, 9002)
        wait_for(lambda: shop_request(9002, "/cart/ci-persistent-order") == (200, cart_before),
                 "Redis cart retained after actual app restart", 120)
        try:
            kubectl("scale", "statefulset/shop-redis", "--replicas=0", "--namespace", NS)
            kubectl("wait", "--for=delete", "pod/shop-redis-0", "--namespace", NS,
                    "--timeout=90s", timeout=100)
            wait_for(lambda: (
                shop_request(9002, "/health")[0] == 200
                and shop_request(9002, "/ready")[0] == 503
                and shop_request(9002, "/cart/ci-persistent-order")[0] == 503
                and shop_request(9003, "/orders", {"user_id": "ci-persistent-order"})[0] == 503
            ), "real Redis outage affects cart/checkout but not process liveness", 90)
            assert request("/api/v1/ready")["status"] == "ready"
            assert retained(order)
        finally:
            kubectl("scale", "statefulset/shop-redis", "--replicas=1", "--namespace", NS)
        wait_for(lambda: (
            shop_request(9002, "/ready")[0] == 200
            and shop_request(9002, "/cart/ci-persistent-order") == (200, cart_before)
        ), "same AOF-persisted cart after Redis outage/restoration", 180)
        print("Actual Redis cart survived app restart and isolated Redis outage/restoration; platform stayed ready")
        # Enable hooks only in this newly owned demo fixture, not base manifests.
        kubectl("set", "env", "deployment/catalog-service", "AEGIS_SHOP_FAULTS_ENABLED=true",
                "--namespace", NS)
        kubectl("rollout", "status", "deployment/catalog-service", "--namespace", NS,
                "--timeout=180s", timeout=200)
        forwards.start("catalog-service", 9001, 9001)
        wait_for(lambda: shop_request(9001, "/products")[0] == 200,
                 "catalog normal before real hook experiment", 120)
        experiment_dir = directory() / "diagnostics" / "experiments"
        experiment_dir.mkdir(parents=True, exist_ok=True)
        with (experiment_dir / "runner.log").open("w") as output:
            experiment = subprocess.Popen(
                [sys.executable, "-m", "chaoslab", "http-5xx", "--seconds", "5",
                 "--output", str(experiment_dir)],
                cwd=ROOT, env={**os.environ, **FIXTURE}, stdout=output, stderr=subprocess.STDOUT,
            )
            try:
                wait_for(lambda: shop_request(9001, "/products")[0] == 503,
                         "actual HTTP fault from CLI", 30)
                assert shop_request(9001, "/health")[0] == 200
                assert experiment.wait(timeout=60) == 0
            finally:
                if experiment.poll() is None:
                    experiment.terminate()
                    experiment.wait(timeout=30)
                    # SIGTERM may skip Python finally; explicit runner cleanup
                    # remains scoped to this owned, identity-checked workload.
                    kubectl("exec", "deployment/catalog-service", "--namespace", NS, "--",
                            "python", "-c",
                            "from pathlib import Path;Path('/tmp/aegisshop-fault.json').unlink(missing_ok=True)")
        wait_for(lambda: shop_request(9001, "/products")[0] == 200,
                 "catalog restored after actual CLI experiment", 60)
        journal_files = list(experiment_dir.glob("*.jsonl"))
        assert len(journal_files) == 1
        stages = [json.loads(line)["stage"] for line in journal_files[0].read_text().splitlines()]
        assert stages == ["prepared", "injection_requested", "injection_applied",
                          "restoration_requested", "restored_control_state"]
        print("Actual opt-in HTTP fault CLI injected/restored with durable ground truth; not ten-fault acceptance")
        # Exercise remaining existing hooks through their actual CLI, with
        # independent domain/resource observations instead of journal truth.
        import time
        for operation in ("network-latency", "cpu-saturation", "memory-pressure"):
            target_dir = experiment_dir / operation
            target_dir.mkdir(exist_ok=True)
            def process_sample() -> dict[str, float]:
                with urllib.request.urlopen("http://127.0.0.1:9001/metrics", timeout=10) as response:
                    lines = response.read().decode().splitlines()
                wanted = {"process_cpu_seconds_total", "process_resident_memory_bytes"}
                return {line.split()[0]: float(line.split()[1]) for line in lines
                        if line and not line.startswith("#") and line.split()[0] in wanted}
            baseline = process_sample()
            start = time.monotonic()
            assert shop_request(9001, "/products")[0] == 200
            baseline_latency = time.monotonic() - start
            samples: list[dict[str, float]] = []
            with (target_dir / "runner.log").open("w") as output:
                experiment = subprocess.Popen(
                    [sys.executable, "-m", "chaoslab", operation, "--seconds", "15",
                     "--output", str(target_dir)],
                    cwd=ROOT, env={**os.environ, **FIXTURE}, stdout=output, stderr=subprocess.STDOUT,
                )
                try:
                    def observed_effect(operation: str = operation, baseline: dict[str, float] = baseline,
                                        samples: list[dict[str, float]] = samples,
                                        baseline_latency: float = baseline_latency) -> bool:
                        from concurrent.futures import ThreadPoolExecutor
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            started = time.monotonic()
                            pending = pool.submit(shop_request, 9001, "/products")
                            time.sleep(0.15)
                            resource = process_sample()
                            assert pending.result(timeout=5)[0] == 200
                            elapsed = time.monotonic() - started
                        samples.append({**resource, "request_seconds": elapsed})
                        if operation == "network-latency":
                            return elapsed >= 0.9 and elapsed > baseline_latency + 0.5
                        if operation == "cpu-saturation":
                            return resource["process_cpu_seconds_total"] > baseline["process_cpu_seconds_total"] + 0.3
                        return resource["process_resident_memory_bytes"] > baseline["process_resident_memory_bytes"] + 20 * 1024 * 1024
                    wait_for(observed_effect, "independent effect of " + operation, 12)
                    assert experiment.wait(timeout=60) == 0
                finally:
                    if experiment.poll() is None:
                        experiment.terminate()
                        experiment.wait(timeout=30)
            started = time.monotonic()
            assert shop_request(9001, "/products")[0] == 200
            restored_latency = time.monotonic() - started
            if operation == "network-latency":
                assert restored_latency < 0.7
            (target_dir / "independent-proof.json").write_text(json.dumps({
                "operation": operation, "baseline": baseline,
                "baseline_request_seconds": baseline_latency, "samples": samples,
                "restored_request_seconds": restored_latency,
                "caveat": "Observed bounded effect; CPU delta is not sustained saturation and memory pressure is not OOM",
                "not_evaluation_accuracy": True,
            }, indent=2))
        print("Actual CLI latency/CPU-work/memory-pressure effects independently observed; no sustained-saturation or detection-accuracy claim")
        def catalog_container() -> dict[str, Any]:
            pods = json.loads(kubectl("get", "pods", "--namespace", NS, "-l",
                "app.kubernetes.io/name=catalog-service", "-o", "json", capture=True))["items"]
            assert len(pods) == 1
            pod = pods[0]
            statuses = pod["status"].get("containerStatuses", [])
            assert len(statuses) == 1
            return {"uid":pod["metadata"]["uid"], **statuses[0]}

        before_crash = catalog_container()
        crash_dir = experiment_dir / "container-crash"
        run([sys.executable, "-m", "chaoslab", "container-crash", "--seconds", "5",
             "--output", str(crash_dir)], timeout=240)
        def restarted_container() -> Any:
            item = catalog_container()
            return item if item["restartCount"] > before_crash["restartCount"] and item.get("ready") else None

        after_crash = wait_for(restarted_container, "independent restarted container readiness", 180)
        assert after_crash["uid"] == before_crash["uid"]
        assert after_crash["restartCount"] > before_crash["restartCount"]
        terminated = after_crash["lastState"]["terminated"]
        assert terminated["exitCode"] == 70 and terminated.get("finishedAt")
        forwards.start("catalog-service", 9001, 9001)
        wait_for(lambda: shop_request(9001, "/products")[0] == 200,
                 "catalog domain recovery after actual process crash", 120)
        proof = {"pod_uid":after_crash["uid"], "restart_count_before":before_crash["restartCount"],
                 "restart_count_after":after_crash["restartCount"], "terminated":terminated,
                 "domain_recovery_observed":True, "not_evaluation_accuracy":True}
        (crash_dir / "independent-proof.json").write_text(json.dumps(proof, indent=2))
        print("Actual immediate process-exit crash, same-Pod restart/70 and domain recovery verified independently of runner journal")
        oom_dir = experiment_dir / "memory-exhaustion"
        oom_dir.mkdir(exist_ok=True)
        before_oom = catalog_container()
        with (oom_dir / "runner.log").open("w") as output:
            experiment = subprocess.Popen(
                [sys.executable, "-m", "chaoslab", "memory-exhaustion", "--seconds", "30",
                 "--output", str(oom_dir)],
                cwd=ROOT, env={**os.environ, **FIXTURE}, stdout=output, stderr=subprocess.STDOUT,
            )
            try:
                def observe_oom() -> Any:
                    item = catalog_container()
                    if item["restartCount"] > before_oom["restartCount"]:
                        return item
                    # Connection loss alone is not OOM proof.
                    with suppress(OSError):
                        shop_request(9001, "/products")
                    return None
                wait_for(observe_oom, "actual memory-exhaustion process restart", 60)
                assert experiment.wait(timeout=210) == 0
            finally:
                if experiment.poll() is None:
                    experiment.terminate()
                    experiment.wait(timeout=210)
        def oom_recovered() -> Any:
            item = catalog_container()
            return item if item["restartCount"] > before_oom["restartCount"] and item.get("ready") else None
        after_oom = wait_for(oom_recovered, "OOM container readiness", 180)
        assert after_oom["uid"] == before_oom["uid"]
        ended = after_oom["lastState"]["terminated"]
        assert ended["reason"] == "OOMKilled" and ended["exitCode"] == 137, ended
        forwards.start("catalog-service", 9001, 9001)
        wait_for(lambda: shop_request(9001, "/products")[0] == 200,
                 "catalog domain recovery after real cgroup OOM", 120)
        (oom_dir / "independent-proof.json").write_text(json.dumps({
            "pod_uid": after_oom["uid"], "terminated": ended,
            "restart_count_before": before_oom["restartCount"],
            "restart_count_after": after_oom["restartCount"],
            "domain_recovery_observed": True, "not_evaluation_accuracy": True,
        }, indent=2))
        print("Actual cgroup OOMKilled/137, same-Pod restart and business recovery independently observed")

        config_dir = experiment_dir / "config-error"
        config_dir.mkdir(exist_ok=True)
        before_config = json.loads(kubectl("get", "deployment", "catalog-service",
            "--namespace", NS, "-o", "json", capture=True))["spec"]["template"]
        with (config_dir / "runner.log").open("w") as output:
            experiment = subprocess.Popen(
                [sys.executable, "-m", "chaoslab", "config-error", "--seconds", "60",
                 "--output", str(config_dir)],
                cwd=ROOT, env={**os.environ, **FIXTURE}, stdout=output, stderr=subprocess.STDOUT,
            )
            def rejected_configuration() -> Any:
                pods = json.loads(kubectl("get", "pods", "--namespace", NS, "-l",
                    "app.kubernetes.io/name=catalog-service", "-o", "json", capture=True))["items"]
                for pod in pods:
                    values = pod["spec"]["containers"][0].get("env", [])
                    if not any(e.get("name") == "CATALOG_MAX_PRODUCTS" and e.get("value") == "0" for e in values):
                        continue
                    for status in pod["status"].get("containerStatuses", []):
                        ended = status.get("lastState", {}).get("terminated") or status.get("state", {}).get("terminated")
                        if ended and ended["exitCode"] != 0 and not status["ready"]:
                            try:
                                logs = kubectl("logs", pod["metadata"]["name"], "--namespace", NS,
                                               "--tail=80", *( ["--previous"] if status["restartCount"] else []),
                                               capture=True)
                            except subprocess.CalledProcessError:
                                continue
                            if "catalog_max_products" in logs and "ValidationError" in logs:
                                return {"pod_uid": pod["metadata"]["uid"], "exit": ended,
                                        "startup_configuration_rejected": True}
                return None
            try:
                config_proof = wait_for(rejected_configuration,
                    "actual invalid configuration rejected by new process", 55)
                # RollingUpdate normally preserves the healthy prior replica.
                # This fault is failed rollout, not assumed service outage.
                config_proof["old_replica_domain_status"] = shop_request(9001, "/products")[0]
                assert experiment.wait(timeout=210) == 0
            finally:
                if experiment.poll() is None:
                    experiment.terminate()
                    experiment.wait(timeout=210)
        after_config = json.loads(kubectl("get", "deployment", "catalog-service",
            "--namespace", NS, "-o", "json", capture=True))["spec"]["template"]
        assert before_config == after_config
        forwards.start("catalog-service", 9001, 9001)
        wait_for(lambda: shop_request(9001, "/products")[0] == 200,
                 "domain ready after exact configuration restoration", 120)
        config_proof["exact_template_restored"] = True
        config_proof["domain_recovery_observed"] = True
        config_proof["not_evaluation_accuracy"] = True
        (config_dir / "independent-proof.json").write_text(json.dumps(config_proof, indent=2))
        print("Actual invalid catalog setting rejected on startup; exact Pod template restored and domain ready, no outage assumed")

        traffic_dir = experiment_dir / "traffic-spike"
        def catalog_requests() -> float:
            import urllib.parse
            expression = 'sum(http_server_requests_total{service="catalog-service",path="/products"})'
            with urllib.request.urlopen("http://127.0.0.1:19090/api/v1/query?" +
                    urllib.parse.urlencode({"query": expression}), timeout=10) as response:
                result = json.load(response)["data"]["result"]
            assert len(result) == 1
            return float(result[0]["value"][1])
        before_load = catalog_requests()
        run([sys.executable, "-m", "chaoslab", "traffic-spike", "--seconds", "10",
             "--output", str(traffic_dir)], timeout=60)
        after_load = wait_for(lambda: (value if (value := catalog_requests()) >= before_load + 100 else None),
                             "independently scraped request counter increase", 60)
        assert shop_request(9001, "/products")[0] == 200
        (traffic_dir / "independent-proof.json").write_text(json.dumps({
            "prometheus_requests_before": before_load, "prometheus_requests_after": after_load,
            "window_seconds": 10, "minimum_request_delta": 100,
            "domain_response_after": 200, "not_evaluation_accuracy": True,
            "caveat": "Counter difference includes background traffic and scrape timing, not an exact generator RPS measurement",
        }, indent=2))
        print("Actual bounded traffic CLI and independent Prometheus counter growth verified; not sustained capacity or detection acceptance")
        release_dir = experiment_dir / "faulty-deployment"
        release_dir.mkdir(exist_ok=True)
        original_template = json.loads(kubectl("get", "deployment", "catalog-service",
            "--namespace", NS, "-o", "json", capture=True))["spec"]["template"]
        with (release_dir / "runner.log").open("w") as output:
            experiment = subprocess.Popen(
                [sys.executable, "-m", "chaoslab", "faulty-deployment", "--seconds", "30",
                 "--output", str(release_dir)],
                cwd=ROOT, env={**os.environ, **FIXTURE}, stdout=output, stderr=subprocess.STDOUT,
            )
            try:
                forwarded_faulty_uid: str | None = None
                def faulty_rollout_serving() -> Any:
                    nonlocal forwarded_faulty_uid
                    pods = json.loads(kubectl("get", "pods", "--namespace", NS, "-l",
                        "app.kubernetes.io/name=catalog-service", "-o", "json", capture=True))["items"]
                    ready = [p for p in pods if not p["metadata"].get("deletionTimestamp") and
                        p["spec"]["containers"][0]["image"] == "aegisshop/catalog-service:ci-faulty" and
                        any(c.get("ready") for c in p["status"].get("containerStatuses", []))]
                    if len(ready) != 1:
                        return None
                    if forwarded_faulty_uid != ready[0]["metadata"]["uid"]:
                        forwards.start("catalog-service", 9001, 9001)
                        forwarded_faulty_uid = ready[0]["metadata"]["uid"]
                    if shop_request(9001, "/products")[0] == 503 and shop_request(9001, "/health")[0] == 200:
                        return {"pod_uid": ready[0]["metadata"]["uid"],
                                "image": ready[0]["spec"]["containers"][0]["image"],
                                "container_status": ready[0]["status"]["containerStatuses"][0]}
                    return None
                release_proof = wait_for(faulty_rollout_serving,
                    "actual separately built faulty revision serving domain503 with liveness200", 180)
                assert experiment.wait(timeout=240) == 0
            finally:
                if experiment.poll() is None:
                    experiment.terminate()
                    experiment.wait(timeout=210)
        restored_template = json.loads(kubectl("get", "deployment", "catalog-service",
            "--namespace", NS, "-o", "json", capture=True))["spec"]["template"]
        assert original_template == restored_template
        forwards.start("catalog-service", 9001, 9001)
        wait_for(lambda: shop_request(9001, "/products")[0] == 200,
                 "original image business response restored", 120)
        release_proof.update({"faulty_domain_status": 503, "faulty_liveness_status": 200,
                              "exact_template_restored": True, "restored_domain_status": 200,
                              "not_evaluation_accuracy": True})
        (release_dir / "independent-proof.json").write_text(json.dumps(release_proof, indent=2))
        print("Actual separately built faulty release503 and original-image restoration200 independently verified")
        run([sys.executable, str(ROOT / "scripts/check_console_stack.py")], timeout=240)
        with urllib.request.urlopen("http://127.0.0.1:3030/login", timeout=15) as response:
            assert response.status == 200
        print(
            json.dumps(
                {
                    "result": "passed",
                    "actual_kind_platform": True,
                    "services": 18,
                    "actual_shop_redis_outage_restored": True,
                    "actual_shop_postgres_outage_restored": True,
                    "actual_postgres_pvc_replacement": True,
                    "actual_projected_sa_tls": True,
                    "evidence_mutations_denied": True,
                    "simulation_only": True,
                    "model_inference": False,
                    "synthetic_history_is_not_chaos_acceptance": True,
                }
            )
        )
    finally:
        # Preserve bounded, non-secret source readiness state before closing
        # forwards. HTTP503 alone cannot distinguish a worker/source failure.
        try:
            state = api("/runtime")
            diagnostic_dir = directory() / "diagnostics"
            diagnostic_dir.mkdir(exist_ok=True)
            (diagnostic_dir / "runtime-status.json").write_text(json.dumps(state, sort_keys=True))
        except (OSError, ValueError):
            print("Runtime status unavailable while collecting final diagnostics")
        forwards.close()


def diagnostics() -> None:
    output = directory() / "diagnostics"
    output.mkdir(exist_ok=True)
    for source in directory().glob("forward-*.log"):
        (output / source.name).write_text(source.read_text(errors="replace")[-10000:])
    if not owned():
        (output / "state.txt").write_text("No fixture-owned cluster was created.\n")
        return
    commands = {
        "resources.txt": [
            "get",
            "pods,services,pvc,deployments,statefulsets",
            "--namespace",
            NS,
            "-o",
            "wide",
        ],
        "events.txt": ["get", "events", "--namespace", NS],
        "pods.txt": ["describe", "pods", "--namespace", NS],
    }
    for name in [
        *APPS,
        "postgres",
        "redis",
        "prometheus",
        "grafana",
        "loki",
        "tempo",
        "otel-collector",
    ]:
        commands[name + ".log"] = [
            "logs",
            "--namespace",
            NS,
            "--selector",
            "app.kubernetes.io/name=" + name,
            "--all-containers=true",
            "--tail=150",
        ]
    for name, args in commands.items():
        try:
            text = kubectl(*args, capture=True, timeout=30)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            text = type(error).__name__ + " while collecting fixture diagnostics\n"
        (output / name).write_text(text)


def cleanup() -> None:
    if owned():
        run([str(directory() / "bin/kind"), "delete", "cluster", "--name", NAME], timeout=180)
        (directory() / "owned").unlink()


if __name__ == "__main__":
    actions = {
        "install": install,
        "build": build,
        "create": create,
        "verify": verify,
        "diagnostics": diagnostics,
        "cleanup": cleanup,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit("Choose install/build/create/verify/diagnostics/cleanup")
    actions[sys.argv[1]]()
