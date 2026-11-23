from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import local_identity


def test_local_identity_never_adopts_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_identity, "base", lambda: tmp_path)
    identity = local_identity.initialize()
    assert len(identity) == 32 and local_identity.owner() == identity
    with pytest.raises(RuntimeError, match="takeover"):
        local_identity.initialize()
    monkeypatch.setattr(local_identity, "node_identity", lambda: "a" * 64)
    assert local_identity.verify_node() is False
    local_identity.record_node()
    assert local_identity.verify_node() is True
    monkeypatch.setattr(local_identity, "node_identity", lambda: "b" * 64)
    assert local_identity.verify_node() is False


def test_tampered_owner_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_identity, "base", lambda: tmp_path)
    (tmp_path / "local-owner.json").write_text(json.dumps({"owner": "a" * 32, "cluster": "other"}))
    with pytest.raises(RuntimeError, match="Invalid local identity"):
        local_identity.owner()
