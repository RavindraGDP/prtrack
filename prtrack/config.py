from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "prtrack"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class RepoConfig:
    name: str
    users: list[str] | None = None


@dataclass
class AppConfig:
    auth_token: str | None = None
    global_users: list[str] = field(default_factory=list)
    repositories: list[RepoConfig] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> AppConfig:
        """Create an `AppConfig` instance from a plain dictionary.

        Args:
            data: A mapping parsed from JSON containing optional keys
                `auth_token` (str | None), `global_users` (list[str]) and
                `repositories` (list[{"name": str, "users"?: list[str]}]).

        Returns:
            A populated `AppConfig` object.
        """
        repos_data = data.get("repositories", [])
        repos = [RepoConfig(**r) for r in repos_data]
        return AppConfig(
            auth_token=data.get("auth_token"),
            global_users=list(data.get("global_users", []) or []),
            repositories=repos,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this configuration to a JSON-safe dictionary.

        Returns:
            A dictionary suitable for `json.dump`.
        """
        return {
            "auth_token": self.auth_token,
            "global_users": self.global_users,
            "repositories": [
                {"name": r.name, **({"users": r.users} if r.users else {})}
                for r in self.repositories
            ],
        }


def ensure_config_dir() -> None:
    """Ensure the configuration directory exists.

    Creates `CONFIG_DIR` with parents if it does not already exist.

    Raises:
        OSError: If the directory cannot be created.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    """Load configuration from `CONFIG_PATH`, creating a default if missing.

    If the config file does not exist, an empty default config is created and
    saved first, then returned.

    Returns:
        The loaded or newly created `AppConfig` instance.

    Raises:
        OSError: If reading the file fails.
        json.JSONDecodeError: If the file exists but contains invalid JSON.
    """
    ensure_config_dir()
    if not CONFIG_PATH.exists():
        # Create an empty default config
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return AppConfig.from_dict(data)


def save_config(cfg: AppConfig) -> None:
    """Persist configuration to `CONFIG_PATH` as JSON.

    Args:
        cfg: The configuration to save.

    Raises:
        OSError: If writing the file fails.
    """
    ensure_config_dir()
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2)
