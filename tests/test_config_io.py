from __future__ import annotations

import json
from pathlib import Path

import pytest

import prtrack.config as cfgmod
from prtrack.config import AppConfig, RepoConfig, load_config, save_config


def test_save_and_load_config_uses_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conf_dir = tmp_path / ".config" / "prtrack"
    conf_path = conf_dir / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", conf_dir)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", conf_path)

    cfg = AppConfig(
        auth_token="tok",
        global_users=["alice"],
        repositories=[RepoConfig(name="o/r", users=["bob"])],
    )
    save_config(cfg)

    assert conf_path.exists()
    data = json.loads(conf_path.read_text())
    assert data["auth_token"] == "tok"
    assert data["global_users"] == ["alice"]
    assert data["repositories"][0]["name"] == "o/r"
    assert data["repositories"][0]["users"] == ["bob"]

    loaded = load_config()
    assert loaded.auth_token == "tok"
    assert loaded.global_users == ["alice"]
    assert len(loaded.repositories) == 1 and loaded.repositories[0].name == "o/r"
    assert loaded.repositories[0].users == ["bob"]


def test_load_config_creates_default_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conf_dir = tmp_path / ".config" / "prtrack"
    conf_path = conf_dir / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", conf_dir)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", conf_path)

    # No file exists; load should create a default empty config
    loaded = load_config()
    assert loaded.auth_token is None
    assert loaded.global_users == []
    assert loaded.repositories == []
    assert conf_path.exists()
