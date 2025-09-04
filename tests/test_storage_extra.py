from __future__ import annotations

import time
from pathlib import Path

import pytest

from prtrack import storage
from prtrack.github import PullRequest


def _pr(n: int, fetched_at: int) -> PullRequest:
    return PullRequest(
        repo="o/r",
        number=n,
        title=f"T{n}",
        author="a",
        assignees=[],
        branch="b",
        draft=False,
        approvals=0,
        html_url="u",
    )


@pytest.fixture
def temp_storage_dir(monkeypatch, tmp_path: Path):
    config_dir = tmp_path / "prtrack"
    monkeypatch.setattr(storage, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(storage, "DB_PATH", config_dir / "cache.sqlite3")
    return config_dir


def test_cleanup_and_stats(temp_storage_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Insert some PRs with older fetched_at by monkeypatching time.time during upsert
    now = int(time.time())

    p1 = _pr(1, now - 90 * 24 * 60 * 60)
    p2 = _pr(2, now - 1 * 24 * 60 * 60)

    # upsert with specific timestamps via fetched_at
    storage.upsert_prs([p1], fetched_at=now - 90 * 24 * 60 * 60)
    storage.upsert_prs([p2], fetched_at=now - 1 * 24 * 60 * 60)

    # record last refresh values
    storage.record_last_refresh("all", ts=now - 90 * 24 * 60 * 60)
    storage.record_last_refresh("repo:o/r", ts=now - 90 * 24 * 60 * 60)

    # stats before cleanup
    stats = storage.get_cache_stats()
    assert stats["total_prs"] == 2 and stats["repositories"] == 1

    # cleanup items older than 30 days should remove p1 and old metadata
    storage.cleanup_old_cache(max_age_days=30)

    stats2 = storage.get_cache_stats()
    assert stats2["total_prs"] == 1

    # last_refresh for old entries should be removed
    assert storage.get_last_refresh("all") is None or storage.get_last_refresh("all") >= now - 30 * 24 * 60 * 60
