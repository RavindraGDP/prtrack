from __future__ import annotations

from prtrack.config import AppConfig
from prtrack.github import PullRequest, filter_prs


def test_app_config_from_to_dict_handles_missing_fields() -> None:
    # Missing optional fields should not crash and should default properly
    data = {"repositories": [{"name": "o/r"}]}
    cfg = AppConfig.from_dict(data)
    assert cfg.auth_token is None
    assert cfg.global_users == []
    assert len(cfg.repositories) == 1 and cfg.repositories[0].name == "o/r"

    # to_dict should serialize back with expected keys
    d2 = cfg.to_dict()
    assert "auth_token" in d2 and "global_users" in d2 and "repositories" in d2


def test_filter_prs_empty_users_returns_all() -> None:
    # Arrange
    prs = [
        PullRequest("o/r", 1, "t1", "a", [], "b", False, 0, "http://example.com/1"),
        PullRequest("o/r", 2, "t2", "c", ["d"], "b", False, 0, "http://example.com/2"),
    ]
    expected_pr_count = 2

    # Act
    out = filter_prs(prs, set())

    # Assert
    assert len(out) == expected_pr_count
