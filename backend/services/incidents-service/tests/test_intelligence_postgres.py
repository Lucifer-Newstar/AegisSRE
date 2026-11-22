from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from incidents_service.config import Settings
from incidents_service.intelligence import Intelligence, IntelligenceError
from incidents_service.repository import Repository


@pytest.mark.skipif(
    not os.environ.get("AEGIS_TEST_DATABASE_URL"), reason="Requires isolated actual PostgreSQL"
)
def test_actual_postgres_quota_is_atomic_across_process_repositories() -> None:
    # The CI URL is a disposable database, never a deployment database.
    url = os.environ["AEGIS_TEST_DATABASE_URL"]
    repositories = [Repository(url), Repository(url)]
    config = Settings(dev_mode=True, llm_requests_per_day=3, llm_requests_per_hour=3)
    agents = [Intelligence(repo, config, None) for repo in repositories]
    with repositories[0].transaction() as tx:
        previous = tx.get_state("inference:quota", {})
        tx.put_state("inference:quota", {})
    try:

        def attempt(index: int) -> bool:
            try:
                agents[index % 2].reserve()
            except IntelligenceError as exc:
                assert exc.status == 429
                return False
            return True

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(12)))
        assert sum(results) == 3
        with repositories[1].transaction() as tx:
            quota = tx.get_state("inference:quota")
            assert quota["daily"] == quota["hourly"] == 3
        repositories[1].close()
        repositories[1] = Repository(url)
        reopened = Intelligence(repositories[1], config, None)
        with pytest.raises(IntelligenceError, match="quota_exhausted"):
            reopened.reserve()
    finally:
        with repositories[0].transaction() as tx:
            tx.put_state("inference:quota", previous)
        for repo in repositories:
            repo.close()
