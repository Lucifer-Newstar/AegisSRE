from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from evaluation.timing import TimingJournal, verify


def test_journal_sequence_monotonic_and_external_digest(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    writer = TimingJournal(path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: writer.record("authored-test", value=i), range(40)))
    final = writer.close()
    assert verify(path, final) == 40
    with pytest.raises(ValueError, match="retained final"):
        verify(path, "f" * 64)
    rows = path.read_text().splitlines()
    value = json.loads(rows[2])
    value["data"]["value"] = "changed"
    rows[2] = json.dumps(value)
    path.write_text("\n".join(rows))
    with pytest.raises(ValueError, match="integrity"):
        verify(path, final)


def test_truncation_and_reordering_fail(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    writer = TimingJournal(path)
    writer.record("first")
    writer.record("second")
    final = writer.close()
    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n")
    with pytest.raises(ValueError, match="retained final"):
        verify(path, final)
    path.write_text("\n".join(reversed(lines)))
    with pytest.raises(ValueError, match="integrity"):
        verify(path, final)
