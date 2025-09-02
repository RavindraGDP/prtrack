from __future__ import annotations

import json
from pathlib import Path

import pytest

from prtrack.config import AppConfig, RepoConfig
from prtrack.github import PullRequest, filter_prs


def test_config_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Write a config, then serialize/deserialize and compare
    cfg = AppConfig(
        auth_token="ghp_xxx",
        global_users=["u1", "u2"],
        repositories=[RepoConfig(name="a/b"), RepoConfig(name="c/d", users=["u3"])],
    )
    data = cfg.to_dict()
    cfg2 = AppConfig.from_dict(json.loads(json.dumps(data)))

    assert cfg2.auth_token == cfg.auth_token
    assert cfg2.global_users == cfg.global_users
    assert [r.name for r in cfg2.repositories] == [r.name for r in cfg.repositories]
    assert [r.users for r in cfg2.repositories] == [r.users for r in cfg.repositories]


def make_pr(repo: str, number: int, author: str, assignees: list[str]) -> PullRequest:
    return PullRequest(
        repo=repo,
        number=number,
        title=f"PR {number}",
        author=author,
        assignees=assignees,
        branch="feature",
        draft=False,
        approvals=0,
        html_url="http://example.com",
    )


def test_filter_prs_by_author_and_assignees() -> None:
    prs = [
        make_pr("o/r", 1, "alice", ["bob"]),
        make_pr("o/r", 2, "carol", ["dave"]),
        make_pr("o/r", 3, "eve", ["frank"]),
    ]
    users = {"carol", "bob"}
    filtered = filter_prs(prs, users)
    # should include PR #1 (assignee bob) and PR #2 (author carol)
    nums = {p.number for p in filtered}
    assert nums == {1, 2}
