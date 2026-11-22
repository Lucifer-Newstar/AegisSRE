from __future__ import annotations

import urllib.error
from typing import Any

import pytest

from scripts import check_metadata_stack


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError("restarting"),
        TimeoutError("starting"),
        urllib.error.URLError("not listening"),
    ],
)
def test_restart_probe_retries_transient_socket_errors(
    error: OSError, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def request(port: int, *args: Any, **kwargs: Any) -> dict[str, str]:
        calls.append(port)
        if len(calls) == 1:
            raise error
        return {"status": "ready"}

    monkeypatch.setattr(check_metadata_stack, "request", request)
    monkeypatch.setattr(check_metadata_stack.time, "sleep", sleeps.append)
    check_metadata_stack.ready()
    assert calls == [8101, 8101, 8701]
    assert sleeps == [1]
