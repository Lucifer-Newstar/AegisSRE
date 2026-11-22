"""Static/bootstrap guardrails, not substitutes for the actual kind CI gate."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "kind_platform_gate", ROOT / "scripts/ci/kind_platform_gate.py"
)
assert SPEC is not None and SPEC.loader is not None
DRIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)


@pytest.fixture
def driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_RUN_ID": "fixture-run",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_JOB": "kind-platform",
    }.items():
        monkeypatch.setenv(name, value)
    return DRIVER


def test_platform_driver_refuses_non_ci_and_ambient_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("KUBECONFIG", "/never-use/ambient")
    with pytest.raises(RuntimeError, match="disposable GitHub"):
        DRIVER.directory()


def test_platform_kubectl_requires_current_owner_and_explicit_context(
    driver: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = Mock(return_value="ok")
    monkeypatch.setattr(driver, "run", call)
    monkeypatch.setenv("KUBECONFIG", "/never-use/ambient")
    with pytest.raises(RuntimeError, match="unowned"):
        driver.kubectl("get", "pods")
    call.assert_not_called()
    (driver.directory() / "owned").write_text(driver.owner())
    assert driver.kubectl("get", "pods", capture=True) == "ok"
    argv = call.call_args.args[0]
    assert argv[1:5] == [
        "--kubeconfig",
        str(driver.directory() / "kubeconfig"),
        "--context",
        "kind-aegis-platform",
    ]
    assert "/never-use/ambient" not in argv


def test_platform_refuses_preexisting_cluster(
    driver: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = Mock(return_value="aegis-platform\n")
    monkeypatch.setattr(driver, "run", call)
    with pytest.raises(RuntimeError, match="pre-existing"):
        driver.create()
    assert call.call_count == 1 and not driver.owned()


def test_platform_cleanup_never_adopts_stale_or_unowned_cluster(
    driver: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = Mock()
    monkeypatch.setattr(driver, "run", call)
    driver.cleanup()
    marker = driver.directory() / "owned"
    marker.write_text("another-run:1:kind-platform")
    driver.cleanup()
    call.assert_not_called()
    marker.write_text(driver.owner())
    driver.cleanup()
    assert call.call_args.args[0][1:] == ["delete", "cluster", "--name", "aegis-platform"]
    assert not marker.exists()


def test_platform_rejects_unverified_tool_download(
    driver: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        driver.urllib.request, "urlopen", Mock(return_value=io.BytesIO(b"not-the-pinned-binary"))
    )
    call = Mock()
    monkeypatch.setattr(driver, "run", call)
    with pytest.raises(ValueError, match="checksum mismatch"):
        driver.install()
    call.assert_not_called()
    assert not (driver.directory() / "bin/kind").exists()


def manifests() -> list[dict[str, Any]]:
    return [
        yaml.safe_load(path.read_text())
        for directory in ("base", "platform")
        for path in (ROOT / "infra/k8s" / directory).glob("*.yaml")
        if path.name != "kustomization.yaml"
    ]


def test_full_platform_has_compose_image_parity_and_only_internal_services() -> None:
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    documents = manifests()
    workloads = {
        doc["metadata"]["name"]: doc
        for doc in documents
        if doc["kind"] in {"Deployment", "StatefulSet"}
    }
    assert set(workloads) == set(services) and len(workloads) == 17
    for name, doc in workloads.items():
        image = services[name]["image"]
        if image.startswith("${AEGIS_POSTGRES_IMAGE:-"):
            image = image[len("${AEGIS_POSTGRES_IMAGE:-") : -1]
        containers = doc["spec"]["template"]["spec"]["containers"]
        assert containers[0]["image"] == image
        for container in containers:
            names = [entry["name"] for entry in container.get("env", [])]
            assert len(names) == len(set(names)), f"Duplicate environment names in {name}"
    assert all(
        doc["spec"].get("type", "ClusterIP") == "ClusterIP"
        for doc in documents
        if doc["kind"] == "Service"
    )
    assert all(doc["kind"] != "Secret" for doc in documents)


def test_persistent_stores_and_shared_configs_are_not_silently_ephemeral() -> None:
    documents = manifests()
    claims = {
        doc["metadata"]["name"] for doc in documents if doc["kind"] == "PersistentVolumeClaim"
    }
    assert claims == {
        name + "-data" for name in ("postgres", "shop-postgres", "redis", "prometheus", "grafana", "loki", "tempo")
    }
    for doc in documents:
        if doc["kind"] not in {"Deployment", "StatefulSet"}:
            continue
        name = doc["metadata"]["name"]
        if name + "-data" not in claims:
            continue
        assert any(
            volume.get("persistentVolumeClaim", {}).get("claimName") == name + "-data"
            for volume in doc["spec"]["template"]["spec"]["volumes"]
        )
    top = yaml.safe_load((ROOT / "infra/kustomization.yaml").read_text())
    assert top["namespace"] == "aegissre-demo"
    assert top["resources"] == ["k8s/base", "k8s/platform"]
    for config in top["configMapGenerator"]:
        for entry in config["files"]:
            path = (ROOT / "infra" / entry.split("=", 1)[-1]).resolve()
            assert path.is_relative_to(ROOT / "infra") and path.is_file()


def test_platform_runtime_is_readonly_evidence_not_live_executor() -> None:
    documents = manifests()
    workloads = [doc for doc in documents if doc["kind"] in {"Deployment", "StatefulSet"}]
    for doc in workloads:
        pod = doc["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is (
            doc["metadata"]["name"] == "incidents-service"
        )
    runtime = next(doc for doc in workloads if doc["metadata"]["name"] == "incidents-service")[
        "spec"
    ]["template"]["spec"]
    env = {entry["name"]: entry for entry in runtime["containers"][0]["env"]}
    assert env["AEGIS_EXECUTOR"]["value"] == "simulation"
    assert env["AEGIS_LLM_PROVIDER"]["value"] == "disabled"
    assert env["AEGIS_METADATA_TOKEN"]["valueFrom"]["secretKeyRef"]["key"] == "read-token"
    assert runtime["serviceAccountName"] == "aegissre-evidence"
    role = next(doc for doc in documents if doc["kind"] == "Role")
    assert all(rule["verbs"] == ["list"] for rule in role["rules"])
    assert {
        (group, resource)
        for rule in role["rules"]
        for group in rule["apiGroups"]
        for resource in rule["resources"]
    } == {
        ("", "pods"),
        ("apps", "deployments"),
        ("apps", "replicasets"),
        ("events.k8s.io", "events"),
    }


def test_shop_order_database_is_not_the_platform_evidence_dependency() -> None:
    documents = manifests()
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    assert "ports" not in compose["shop-postgres"]
    assert compose["shop-postgres"]["volumes"] != compose["postgres"]["volumes"]
    assert "@shop-postgres:" in compose["order-service"]["environment"]["SHOP_DATABASE_URL"]
    order = next(doc for doc in documents if doc["kind"] == "Deployment"
                 and doc["metadata"]["name"] == "order-service")
    env = {entry["name"]: entry for entry in order["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["SHOP_DATABASE_URL"]["valueFrom"]["secretKeyRef"]["name"] == "aegisshop-database"
    postgres = next(doc for doc in documents if doc["kind"] == "StatefulSet"
                    and doc["metadata"]["name"] == "shop-postgres")
    pod = postgres["spec"]["template"]["spec"]
    assert not pod["automountServiceAccountToken"]
    assert any(volume.get("persistentVolumeClaim", {}).get("claimName") == "shop-postgres-data"
               for volume in pod["volumes"])
    assert all(entry.get("valueFrom", {}).get("secretKeyRef", {}).get("name") != "aegissre-postgres"
               for entry in pod["containers"][0]["env"])
