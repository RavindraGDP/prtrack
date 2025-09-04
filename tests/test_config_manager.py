from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

import prtrack.config_manager as cm


@dataclass
class RepoCfg:
    name: str
    users: list[str] | None = None


@dataclass
class AppCfg:
    repositories: list[RepoCfg] = field(default_factory=list)
    global_users: list[str] = field(default_factory=list)
    keymap: dict[str, str] = field(default_factory=dict)
    staleness_threshold_seconds: int = 3600
    pr_page_size: int = 10
    menu_page_size: int = 3
    auth_token: str | None = None


class SpyNav:
    def __init__(self) -> None:
        self.stack: list[str] = []

    def clear_stack(self) -> None:
        self.stack.clear()

    def push_screen(self, name: str) -> None:
        self.stack.append(name)

    def pop_screen(self) -> str | None:
        return self.stack.pop() if self.stack else None

    def peek_screen(self) -> str | None:
        return self.stack[-1] if self.stack else None

    # Used by _do_add_account and _do_remove_account_select
    def navigate_back_or_home(self) -> None:
        self.stack.append("nav_back_or_home")


class SpyApp:
    def __init__(self) -> None:
        self.cfg = AppCfg(repositories=[RepoCfg("o/r", ["alice"])], global_users=["bob"])
        # Provide RepoConfig alias used by ConfigManager
        self.RepoConfig = RepoCfg
        self._settings_page_index = 0
        self._keymap_defaults = {
            "next_page": "]",
            "prev_page": "[",
            "open_pr": "enter",
            "mark_markdown": "space",
            "back": "esc",
        }
        self._keymap = dict(self._keymap_defaults)
        self._overlay_select_action = None
        self._menu_shown_titles: list[tuple[str, list[tuple[str, str]]]] = []
        self._lists_shown: list[tuple[str, list[str]]] = []
        self._toasts: list[str] = []
        self._page_size = 10
        self._stale_after_seconds = self.cfg.staleness_threshold_seconds
        self._navigation_manager = SpyNav()
        self._prompt_manager = SimpleNamespace(
            prompt_one_field=lambda *a, **k: self._captured_prompt(a, k),
            prompt_two_fields=lambda *a, **k: self._captured_prompt(a, k),
        )
        self.storage = SimpleNamespace(delete_prs_by_repo=lambda *_: None, delete_prs_by_account=lambda *a, **k: None)
        self.GitHubClient = lambda token: f"client:{token}"
        self.client: Any = None

    def _captured_prompt(self, args, kwargs):
        self._last_prompt = (args, kwargs)

    def _show_choice_menu(self, title, actions):
        self._menu_shown_titles.append((title, actions))

    def _show_list(self, title, items, select_action=None):
        self._lists_shown.append((title, list(items)))

    def _show_toast(self, msg):
        self._toasts.append(str(msg))

    def _show_menu(self):
        self._menu_shown_titles.append(("main", []))

    def action_go_back(self):
        self._navigation_manager.stack.append("back")


@pytest.fixture(autouse=True)
def no_save(monkeypatch):
    calls: list[Any] = []
    monkeypatch.setattr(cm, "save_config", lambda cfg: calls.append(cfg))
    return calls


def test_show_config_menu_pagination_and_nav():
    app = SpyApp()
    mgr = cm.ConfigManager(app)
    app.cfg.menu_page_size = 2
    mgr.show_config_menu(is_from_main_menu=True)
    assert app._navigation_manager.stack[:2] == ["main_menu"]
    # Menu shown with pagination title
    assert app._menu_shown_titles[-1][0].startswith("Settings (Page 1/")
    # Next page
    mgr.handle_config_action("settings_next")
    assert app._menu_shown_titles[-1][0].startswith("Settings (Page 2/")
    # Prev page
    mgr.handle_config_action("settings_prev")
    assert app._menu_shown_titles[-1][0].startswith("Settings (Page 1/")


def test_keymap_show_and_update_and_reset(monkeypatch):
    app = SpyApp()
    mgr = cm.ConfigManager(app)
    # Show current keymap pushes to stack
    mgr._show_current_keymap()
    assert app._navigation_manager.peek_screen() == "config_menu"
    # Show keymap menu and trigger back
    mgr._show_keymap_menu()
    assert callable(app._overlay_select_action)
    app._overlay_select_action("back")
    assert app._navigation_manager.stack[-1] == "back"
    # Reset all
    mgr._show_keymap_menu()
    app._overlay_select_action("reset_all")
    assert app._keymap == app._keymap_defaults
    # Set back key via key_back path
    mgr._show_keymap_menu()
    app._overlay_select_action("key_back")
    title, placeholder, cb = app._last_prompt[0][0], app._last_prompt[0][1], app._last_prompt[0][2]
    assert "Set key for back" in title and placeholder == app._keymap.get("back")
    cb("B")
    assert app._keymap["back"] == "b"
    # Set other key via general path
    mgr._show_keymap_menu()
    app._overlay_select_action("open_pr")
    _, _, cb2 = app._last_prompt[0]
    cb2("X")
    assert app._keymap["open_pr"] == "x"
    # Duplicate resolution: set same key to another action resets previous to default
    mgr._do_set_keymap("next_page", "x")
    assert app._keymap["open_pr"] == app._keymap_defaults["open_pr"]


def test_add_remove_repo_and_accounts_and_token_flow():
    app = SpyApp()
    mgr = cm.ConfigManager(app)
    # Add repo prompt
    mgr._prompt_add_repo()
    assert app._navigation_manager.peek_screen() == "config_menu"
    # Do add repo and return to menu via stack
    mgr._do_add_repo("new/repo", "u1, u2 ")
    assert any(r.name == "new/repo" and r.users == ["u1", "u2"] for r in app.cfg.repositories)
    assert app._menu_shown_titles[-1][0].startswith("Settings")
    # Remove repo prompt and remove
    mgr._prompt_remove_repo()
    mgr._do_remove_repo("new/repo")
    assert all(r.name != "new/repo" for r in app.cfg.repositories)
    # Add account global
    mgr._prompt_add_account()
    mgr._do_add_account("bob2", "")
    assert "bob2" in app.cfg.global_users
    # Add account repo scoped
    mgr._do_add_account("alice2", "o/r")
    repo = next(r for r in app.cfg.repositories if r.name == "o/r")
    assert "alice2" in (repo.users or [])
    # Remove account select listing
    mgr._prompt_remove_account_select()
    assert any("global:" in item for _, items in [app._lists_shown[-1]] for item in items)
    # Remove account by key
    mgr._do_remove_account_select("o/r:alice2")
    repo = next(r for r in app.cfg.repositories if r.name == "o/r")
    assert (repo.users or []) == ["alice"]
    # Invalid key path falls back
    mgr._do_remove_account_select("invalid")
    assert app._navigation_manager.stack[-1] in {"nav_back_or_home", "back"}
    # Update token prompt and apply
    mgr._prompt_update_token()
    mgr._do_update_token("tok123")
    assert app.cfg.auth_token == "tok123"
    assert app.client == "client:tok123"
    # Update token path when not returning to config menu
    app._navigation_manager.clear_stack()
    mgr._do_update_token("")
    assert app.cfg.auth_token is None


def test_set_threshold_and_page_sizes_validation():
    app = SpyApp()
    mgr = cm.ConfigManager(app)
    # Staleness threshold set then back to menu
    mgr._prompt_set_staleness_threshold()
    _, _, cb = app._last_prompt[0]
    cb("7200")
    assert app.cfg.staleness_threshold_seconds == 7200
    assert app._stale_after_seconds == 7200
    # PR page size valid positive
    mgr._prompt_set_pr_page_size()
    _, _, cb2 = app._last_prompt[0]
    cb2("25")
    assert app.cfg.pr_page_size == 25 and app._page_size == 25
    # Settings menu page size valid
    mgr._prompt_set_settings_menu_page_size()
    _, _, cb3 = app._last_prompt[0]
    cb3("4")
    assert app.cfg.menu_page_size == 4 and app._settings_page_index == 0
    # Settings menu page size invalid -> toast, but still shows menu
    mgr._prompt_set_settings_menu_page_size()
    _, _, cb4 = app._last_prompt[0]
    cb4("0")
    assert any("Invalid number" in t for t in app._toasts)
