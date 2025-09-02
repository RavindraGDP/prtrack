from __future__ import annotations

import pytest

from prtrack.tui import PRTrackApp


def test_select_repo_calls_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    app = PRTrackApp()

    called: dict[str, str] = {}

    def fake_loader(repo_name: str) -> None:
        called["repo"] = repo_name

    monkeypatch.setattr(app, "_load_repo_prs", fake_loader)

    app._select_repo("owner/repo")

    assert called.get("repo") == "owner/repo"


def test_select_account_calls_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    app = PRTrackApp()

    called: dict[str, str] = {}

    def fake_loader(account: str) -> None:
        called["account"] = account

    monkeypatch.setattr(app, "_load_account_prs", fake_loader)

    app._select_account("alice")

    assert called.get("account") == "alice"
