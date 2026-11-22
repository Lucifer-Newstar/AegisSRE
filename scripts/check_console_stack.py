#!/usr/bin/env python3
"""Actual Next session/read-only pages against the running gateway, not mocks."""

from __future__ import annotations

import http.cookiejar
import os
import urllib.error
import urllib.parse
import urllib.request

ORIGIN = "http://localhost:3030"


def main() -> None:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with opener.open(ORIGIN + "/", timeout=15) as response:
        assert response.url == ORIGIN + "/login"
        assert "Connect to your control plane" in response.read().decode()
    body = urllib.parse.urlencode({"token": os.environ["AEGIS_API_TOKEN"]}).encode()
    request = urllib.request.Request(
        ORIGIN + "/api/session", data=body,
        headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with opener.open(request, timeout=30) as response:
        text = response.read().decode()
        assert response.url == ORIGIN + "/" and "Command Center" in text
        assert os.environ["AEGIS_API_TOKEN"] not in text
        assert "ci-runtime" in text and "simulation" in text
    assert any(cookie.name == "aegis_session" and cookie.has_nonstandard_attr("HttpOnly")
               for cookie in jar)
    from scripts.check_runtime_stack import api
    incidents=api("/incidents?service=ci-runtime")
    assert incidents, "Expected persisted transport-fixture incident"
    identity=incidents[0]["id"]
    for path, heading in [
        ("/services", "Services"), ("/incidents", "Incidents"),
        ("/approvals", "Approvals"), ("/postmortems", "Postmortems"),
        ("/runbooks", "Runbooks"), ("/ask", "Ask Aegis"),
        ("/deployments", "Deployments"), ("/audit", "Audit log"),
        ("/services/catalog-service", "Registry and SLO configuration"),
        ("/incidents/"+urllib.parse.quote(identity,safe=""), "Incident timeline"),
    ]:
        with opener.open(ORIGIN + path, timeout=30) as response:
            text = response.read().decode()
            assert response.status == 200 and heading in text
            assert os.environ["AEGIS_API_TOKEN"] not in text
            assert "Mock data" not in text and "mock payload" not in text
            assert "No data substituted" not in text and "API connection failed" not in text
            assert "API unavailable" not in text and "Incident unavailable" not in text
    try:
        opener.open(urllib.request.Request(
            ORIGIN + "/api/decision", data=b"id=fixture&decision=approve",
            headers={"Origin": "https://not-this-console.invalid"},
        ), timeout=15)
    except urllib.error.HTTPError as error:
        assert error.code == 403
    else:
        raise AssertionError("Console accepted a cross-origin decision")
    print("Actual Next encrypted login and authenticated live read pages passed; cross-origin decision denied; no UI mutation or model call")


if __name__ == "__main__":
    main()
