#!/usr/bin/env python3
"""Read actual owned-kind Prometheus rules/Grafana provisioning, no fault claim."""
from __future__ import annotations

import base64
import json
import time
import urllib.parse
import urllib.request
from typing import Any


def read(port: int, path: str, authenticated: bool = False) -> Any:
    headers = {}
    if authenticated:
        # Public disposable fixture identity, never a user's saved login.
        value = base64.b64encode(b"admin:ci-disposable-grafana").decode()
        headers["Authorization"] = "Basic " + value
    with urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{port}"+path,headers=headers),timeout=10) as response:
        return json.load(response)


def main() -> None:
    rules=read(19090,"/api/v1/rules")
    group=next(g for g in rules["data"]["groups"] if g["name"]=="aegisshop-request-slo")
    assert len(group["rules"])==5
    assert all(r["health"]=="ok" for r in group["rules"]),group
    alert=next(r for r in group["rules"] if r["name"]=="AegisShopRequestErrorBudgetFastBurn")
    assert alert["duration"]==120 and alert["labels"]["objective"]=="request-success-99.9-v1"
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        result=read(19090,"/api/v1/query?"+urllib.parse.urlencode({"query":"aegisshop:slo_burn_rate:5m{service=\"catalog-service\",environment=\"dev\"}"}))["data"]["result"]
        if result:
            assert all(float(r["value"][1])>=0 for r in result)
            break
        time.sleep(1)
    else:
        raise AssertionError("No actual catalog request-SLO series observed")
    from check_runtime_stack import api
    observed = api("/slo?service=catalog-service")
    assert observed["objective"] == "request-success-99.9-v1"
    assert observed["budget_remaining_fraction"] is None
    assert observed["status"] == "partial_or_missing_window"
    assert observed["measurements"]["burn_5m"] is not None
    dashboard=read(13000,"/api/dashboards/uid/aegisshop-slo",True)["dashboard"]
    assert len(dashboard["panels"])==5
    assert any("Missing/zero traffic" in p.get("options",{}).get("content","") for p in dashboard["panels"])
    print("Actual owned-kind SLO rules healthy, observed catalog burn series and provisioned Grafana dashboard verified; no live fault alert or full-window budget acceptance claimed")


if __name__=="__main__":
    main()
