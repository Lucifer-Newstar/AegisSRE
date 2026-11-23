#!/usr/bin/env python3
"""Actual authenticated policy update/restart proof, not action success evaluation."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/ci"))
import kind_platform_gate as fixture  # noqa: E402


def main() -> None:
    if not fixture.owned():
        raise RuntimeError("Refusing unowned cluster")
    os.environ.update(fixture.FIXTURE)
    from check_gateway_stack import request
    from check_runtime_stack import wait_for

    forwards = fixture.Forwards()
    try:
        forwards.start("api-gateway", 8080, 8000)
        try:
            wait_for(lambda: request("/api/v1/ready")["status"] == "ready", "gateway")
        except AssertionError:
            # Retain read-only worker/source status instead of losing the reason
            # behind a generic ready503. No action or policy write has run yet.
            forwards.start("incidents-service", 8201, 8201)
            from check_runtime_stack import api
            try:
                status = api("/runtime")
            except Exception as error:
                status = {"read_error": type(error).__name__}
            (fixture.directory() / "diagnostics" / "policy-readiness-failure.json").write_text(
                json.dumps(status, indent=2)
            )
            raise
        original = request("/api/v1/policy")
        mode = request("/api/v1/autonomy")["mode"]
        request("/api/v1/autonomy", body={"mode": "observe", "actor": "not-trusted"})
        updated = {**original, "version": "owned-ci-policy-update"}
        request("/api/v1/policy", body={"expected_version": original["version"],
            "policy": updated, "actor": "not-trusted"})
        assert request("/api/v1/policy") == updated
        fixture.kubectl("rollout", "restart", "deployment/incidents-service", "-n", fixture.NS)
        fixture.kubectl("rollout", "status", "deployment/incidents-service", "-n", fixture.NS,
                        "--timeout=180s", timeout=200)
        wait_for(lambda: request("/api/v1/ready")["status"] == "ready", "restarted runtime", 120)
        assert request("/api/v1/policy") == updated
        assert request("/api/v1/autonomy")["mode"] == "observe"
        def policy_audit() -> dict[str, object] | None:
            # The gateway may have an old keepalive to the replaced API Pod.
            # Retry this read only; never replay the policy write.
            entries = request("/api/v1/audit?limit=200")
            return next((e for e in entries if e["action"] == "policy.updated"), None)

        change = wait_for(policy_audit, "policy audit after runtime replacement", 120)
        assert change["actor"] == "token:operator"
        request("/api/v1/autonomy", body={"mode": mode, "actor": "not-trusted"})
        (fixture.directory() / "diagnostics" / "policy-update-proof.json").write_text(json.dumps({
            "before": original, "after_restart": updated, "audit": change,
            "observe_retained_during_update": True, "original_mode_restored": mode,
            "not_action_success_evaluation": True,
        }, indent=2))
    finally:
        forwards.close()
    print("Actual gateway-authored policy update and application-restart persistence passed")


if __name__ == "__main__":
    main()
