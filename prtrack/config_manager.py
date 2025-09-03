from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING

from .config import save_config

if TYPE_CHECKING:
    from .tui import PRTrackApp


class ConfigManager:
    """Manages configuration-related functionality for the PRTrack TUI application."""

    def __init__(self, app: PRTrackApp) -> None:
        """Initialize the ConfigManager with a reference to the main application.

        Args:
            app: The main PRTrackApp instance.
        """
        self.app = app

    def show_config_menu(self, is_from_main_menu: bool = False) -> None:
        """Display Settings menu as an overlay list.

        Args:
            is_from_main_menu: Whether the config menu is being shown from the main menu.
        """
        # Push to navigation stack if coming from main menu
        if is_from_main_menu:
            # Clear the navigation stack when coming from main menu to avoid accumulation
            self.app._navigation_manager.clear_stack()
            self.app._navigation_manager.push_screen("main_menu")
            self.app._settings_page_index = 0

        actions = [
            ("add_repo", "Add repo"),
            ("remove_repo", "Remove repo"),
            ("add_account", "Add account"),
            ("remove_account", "Remove account"),
            ("set_stale", "Set staleness threshold (seconds)"),
            ("set_page_size", "Set PRs per page"),
            ("set_settings_page_size", "Set Settings menu page size"),
            ("update_token", "Update GitHub token"),
            ("keymap_menu", "Set Key bindings"),
            ("show_keymap", "Show current key bindings"),
            ("show_config", "Show current config"),
        ]
        # Paginate actions
        page_size = max(1, int(getattr(self.app.cfg, "menu_page_size", 5)))
        total = len(actions)
        pages = max(1, (total + page_size - 1) // page_size)
        index = max(0, min(self.app._settings_page_index, pages - 1))
        start = index * page_size
        end = min(start + page_size, total)
        page_actions = actions[start:end]
        # Navigation controls
        if pages > 1:
            if index > 0:
                page_actions.append(("settings_prev", "Previous"))
            if index < pages - 1:
                page_actions.append(("settings_next", "Next"))
        # Always include Back at the end
        page_actions.append(("back", "Back"))
        title = f"Settings (Page {index+1}/{pages})" if pages > 1 else "Settings"
        self.app._show_choice_menu(title, page_actions)

    def handle_config_action(self, action: str) -> None:
        """Route a selected config action to its handler.

        Args:
            action: Action key from the config menu.
        """
        handlers: dict[str, Callable[[], None]] = {
            "add_repo": self._prompt_add_repo,
            "remove_repo": self._prompt_remove_repo,
            "add_account": self._prompt_add_account,
            "remove_account": self._prompt_remove_account_select,
            "set_stale": self._prompt_set_staleness_threshold,
            "set_page_size": self._prompt_set_pr_page_size,
            "set_settings_page_size": self._prompt_set_settings_menu_page_size,
            "update_token": self._prompt_update_token,
            "keymap_menu": self._show_keymap_menu,
            "show_keymap": self._show_current_keymap,
            "show_config": self._show_current_config,
            "settings_next": lambda: (
                setattr(self.app, "_settings_page_index", self.app._settings_page_index + 1),
                self.show_config_menu(),
            ),
            "settings_prev": lambda: (
                setattr(self.app, "_settings_page_index", max(0, self.app._settings_page_index - 1)),
                self.show_config_menu(),
            ),
            "back": self.app.action_go_back,
        }
        handlers.get(action, self.app._show_menu)()

    # ---------- Keymap settings ----------

    def _show_current_keymap(self) -> None:
        lines = ["Current Key Bindings (overrides shown; defaults in code):"]
        for k, v in self.app._keymap.items():
            ov = self.app.cfg.keymap.get(k) if hasattr(self.app.cfg, "keymap") else None
            mark = " (default)" if ov is None else ""
            lines.append(f"{k}: {v}{mark}")
        # Add instruction for user to press back to close
        lines.append("")
        lines.append("(Press Back or select any item to close)")
        self.app._show_list("Help / Key bindings", lines, select_action=lambda _val: self.app.action_go_back())
        # Add to navigation stack so back button works correctly
        if self.app._navigation_manager.peek_screen() != "config_menu":
            self.app._navigation_manager.push_screen("config_menu")

    def _show_keymap_menu(self) -> None:
        items = [
            ("next_page", f"next_page → '{self.app._keymap.get('next_page', '')}'"),
            ("prev_page", f"prev_page → '{self.app._keymap.get('prev_page', '')}'"),
            ("open_pr", f"open_pr → '{self.app._keymap.get('open_pr', '')}'"),
            ("mark_markdown", f"mark_markdown → '{self.app._keymap.get('mark_markdown', '')}'"),
            ("key_back", f"back → '{self.app._keymap.get('back', '')}'"),
            ("reset_all", "Reset all to defaults"),
            ("back", "Back"),
        ]
        self.app._show_choice_menu("Set Key bindings", items)
        self.app._overlay_select_action = lambda key: self._handle_keymap_action(key)
        # Add to navigation stack so back button works correctly
        if self.app._navigation_manager.peek_screen() != "config_menu":
            self.app._navigation_manager.push_screen("config_menu")

    def _handle_keymap_action(self, action: str) -> None:
        # Handle navigation actions first
        if action == "back":
            self.app.action_go_back()
            return
        if action == "reset_all":
            self.app.cfg.keymap = {}
            save_config(self.app.cfg)
            self.app._keymap = {**self.app._keymap_defaults}
            self._show_keymap_menu()
            return
        if action == "key_back":
            # Handle the back key binding action
            current = self.app._keymap.get("back", "")
            self.app._prompt_manager.prompt_one_field(
                "Set key for back (empty to reset)\nPress the key you want to use, then Enter/OK",
                current,
                lambda v: self._do_set_keymap("back", v),
            )
            return
        if action in self.app._keymap_defaults:
            current = self.app._keymap.get(action, "")
            self.app._prompt_manager.prompt_one_field(
                f"Set key for {action} (empty to reset)\nPress the key you want to use, then Enter/OK",
                current,
                lambda v, a=action: self._do_set_keymap(a, v),
            )
            return
        # Only add to navigation stack if it's not already there
        if self.app._navigation_manager.peek_screen() != "config_menu":
            self.app._navigation_manager.push_screen("config_menu")
        self.show_config_menu()

    def _do_set_keymap(self, action: str, value: str) -> None:
        key = value.strip().lower()
        # Empty value resets to default by removing override
        if not key:
            with contextlib.suppress(Exception):
                if action in self.app.cfg.keymap:
                    del self.app.cfg.keymap[action]
            self.app._keymap[action] = self.app._keymap_defaults.get(action, key)
        else:
            # Prevent duplicate bindings across actions to avoid conflicts
            for act, mapped in list(self.app._keymap.items()):
                if act != action and mapped == key:
                    self.app._keymap[act] = self.app._keymap_defaults.get(act, mapped)
                    with contextlib.suppress(Exception):
                        if act in self.app.cfg.keymap:
                            del self.app.cfg.keymap[act]
            self.app.cfg.keymap[action] = key
            self.app._keymap[action] = key
        save_config(self.app.cfg)
        self._show_keymap_menu()

    def _prompt_add_repo(self) -> None:
        """Prompt the user to add a repository and optional users."""
        # Push current screen to navigation stack
        self.app._navigation_manager.push_screen("config_menu")
        self.app._prompt_manager.prompt_two_fields(
            "Add Repo", "owner/repo", "optional users (comma)", self._do_add_repo
        )

    def _do_add_repo(self, repo: str, users_csv: str) -> None:
        """Add a repository to the config.

        Args:
            repo: Repository in "owner/repo" format.
            users_csv: Optional comma-separated usernames to restrict tracking.
        """
        repo = repo.strip()
        users = [u.strip() for u in users_csv.split(",") if u.strip()] if users_csv else []
        if repo:
            self.app.cfg.repositories.append(self.app.RepoConfig(name=repo, users=users or None))
            save_config(self.app.cfg)
        # Go back to the previous screen using navigation stack
        prev_screen = self.app._navigation_manager.pop_screen()
        if prev_screen == "config_menu":
            self.show_config_menu()
        else:
            self.app._show_menu()

    def _prompt_remove_repo(self) -> None:
        """Prompt for selecting a repository to remove from the config."""
        # Push current screen to navigation stack
        self.app._navigation_manager.push_screen("config_menu")
        names = [r.name for r in self.app.cfg.repositories]
        self.app._show_list("Remove Repo - select", names, select_action=self._do_remove_repo)

    def _do_remove_repo(self, repo_name: str) -> None:
        """Remove a repository from the configuration.

        Args:
            repo_name: Repository in "owner/repo" format to remove.
        """
        self.app.cfg.repositories = [r for r in self.app.cfg.repositories if r.name != repo_name]
        # Purge cached PRs for this repo immediately
        with contextlib.suppress(Exception):
            self.app.storage.delete_prs_by_repo(repo_name)
        save_config(self.app.cfg)
        # Go back to the previous screen using navigation stack
        prev_screen = self.app._navigation_manager.pop_screen()
        if prev_screen == "config_menu":
            self.show_config_menu()
        else:
            self.app._show_menu()

    def _prompt_add_account(self) -> None:
        """Prompt to add an account globally or scoped to a repository."""
        # Push current screen to navigation stack
        self.app._navigation_manager.push_screen("config_menu")
        self.app._prompt_manager.prompt_two_fields(
            "Add Account", "username", "repo (owner/repo or empty=global)", self._do_add_account
        )

    def _do_add_account(self, username: str, repo_name: str) -> None:
        """Add an account to global or per-repo tracked users.

        Args:
            username: GitHub username to add.
            repo_name: "owner/repo" to scope the username, or empty for global.
        """
        username = username.strip()
        repo_name = repo_name.strip()
        if not username:
            self.app._navigation_manager.navigate_back_or_home()
            return
        if repo_name:
            for r in self.app.cfg.repositories:
                if r.name == repo_name:
                    users = set(r.users or [])
                    users.add(username)
                    r.users = sorted(users)
                    break
        else:
            users = set(self.app.cfg.global_users)
            users.add(username)
            self.app.cfg.global_users = sorted(users)
        save_config(self.app.cfg)
        self.app._navigation_manager.navigate_back_or_home()

    def _prompt_remove_account_select(self) -> None:
        """Show a list of accounts (global and per-repo) to remove via selection."""
        # Push current screen to navigation stack
        self.app._navigation_manager.push_screen("config_menu")
        items: list[str] = []
        # Global users
        for u in sorted(set(self.app.cfg.global_users)):
            items.append(f"global:{u}")
        # Per-repo users
        for r in self.app.cfg.repositories:
            for u in sorted(set(r.users or [])):
                items.append(f"{r.name}:{u}")
        if not items:
            self.app._show_menu()
            return
        self.app._show_list(
            "Remove Account - select",
            items,
            select_action=self._do_remove_account_select,
        )

    def _do_remove_account_select(self, key: str) -> None:
        """Handle selection of an account removal entry.

        Key format:
          - "global:username" for global users
          - "owner/repo:username" for repo-scoped users
        """
        try:
            prefix, username = key.split(":", 1)
        except ValueError:
            self.app._navigation_manager.navigate_back_or_home()
            return
        username = username.strip()
        if prefix == "global":
            self.app.cfg.global_users = [u for u in self.app.cfg.global_users if u != username]
            with contextlib.suppress(Exception):
                self.app.storage.delete_prs_by_account(username)
        else:
            repo_name = prefix
            for r in self.app.cfg.repositories:
                if r.name == repo_name and r.users:
                    r.users = [u for u in r.users if u != username] or None
            with contextlib.suppress(Exception):
                self.app.storage.delete_prs_by_account(username, repo_name)
        save_config(self.app.cfg)
        self.app._navigation_manager.navigate_back_or_home()

    def _prompt_update_token(self) -> None:
        """Prompt to update the stored GitHub personal access token."""
        # Push current screen to navigation stack
        self.app._navigation_manager.push_screen("config_menu")
        self.app._prompt_manager.prompt_one_field("Update GitHub Token", "token", self._do_update_token)

    def _do_update_token(self, token: str) -> None:
        """Store a new GitHub token and refresh the client.

        Args:
            token: The new token value; empty string clears the token.
        """
        self.app.cfg.auth_token = token.strip() or None
        save_config(self.app.cfg)
        # refresh client headers
        self.app.client = self.app.GitHubClient(self.app.cfg.auth_token)
        # Go back to the previous screen using navigation stack
        prev_screen = self.app._navigation_manager.pop_screen()
        if prev_screen == "config_menu":
            self.show_config_menu()
        elif self.app._navigation_manager.peek_screen() == "config_menu":
            self.app._navigation_manager.pop_screen()
            self.show_config_menu()
        else:
            self.app._show_menu()

    def _show_current_config(self) -> None:
        """Display a transient view of the current configuration."""
        lines = ["Current Config:"]
        lines.append(f"Token: {'set' if self.app.cfg.auth_token else 'not set'}")
        users = ", ".join(self.app.cfg.global_users) if self.app.cfg.global_users else "(none)"
        lines.append(f"Global users: {users}")
        lines.append(f"Staleness threshold (s): {self.app.cfg.staleness_threshold_seconds}")
        lines.append(f"PRs per page: {getattr(self.app.cfg, 'pr_page_size', 10)}")
        for r in self.app.cfg.repositories:
            users = ", ".join(r.users) if r.users else "(inherit globals)"
            lines.append(f"Repo: {r.name} | users: {users}")
        # Add instruction for user to press back to close
        lines.append("")
        lines.append("(Press Back or select any item to close)")
        self.app._show_list("Current Config", lines, select_action=lambda _val: self.app.action_go_back())
        # Add to navigation stack so back button works correctly
        if self.app._navigation_manager.peek_screen() != "config_menu":
            self.app._navigation_manager.push_screen("config_menu")

    # ---------- Prompt helpers ----------

    def _prompt_set_staleness_threshold(self) -> None:
        """Prompt for staleness threshold in seconds."""
        # Push current screen to navigation stack
        self.app._navigation_manager.push_screen("config_menu")
        self.app._prompt_manager.prompt_one_field(
            "Set staleness threshold (seconds)",
            str(self.app.cfg.staleness_threshold_seconds),
            self._do_set_staleness_threshold,
        )

    def _do_set_staleness_threshold(self, value: str) -> None:
        with contextlib.suppress(Exception):
            seconds = max(0, int(value.strip()))
            self.app.cfg.staleness_threshold_seconds = seconds
            self.app._stale_after_seconds = seconds
            save_config(self.app.cfg)
        # Go back to the previous screen using navigation stack
        prev_screen = self.app._navigation_manager.pop_screen()
        if prev_screen == "config_menu":
            self.show_config_menu()
        else:
            self.app._show_menu()

    def _prompt_set_pr_page_size(self) -> None:
        """Prompt for PRs per page size."""
        # Push current screen to navigation stack
        self.app._navigation_manager.push_screen("config_menu")
        self.app._prompt_manager.prompt_one_field(
            "Set PRs per page",
            str(getattr(self.app.cfg, "pr_page_size", 10)),
            self._do_set_pr_page_size,
        )

    def _do_set_pr_page_size(self, value: str) -> None:
        with contextlib.suppress(Exception):
            size = int(value.strip())
            if size <= 0:
                raise ValueError("page size must be > 0")
            self.app.cfg.pr_page_size = size  # type: ignore[attr-defined]
            self.app._page_size = size
            save_config(self.app.cfg)
        self.app._show_menu()

    def _prompt_set_settings_menu_page_size(self) -> None:
        """Prompt for Settings menu page size."""
        # Push current screen to navigation stack
        self.app._navigation_manager.push_screen("config_menu")
        self.app._prompt_manager.prompt_one_field(
            "Set Settings menu page size",
            str(getattr(self.app.cfg, "menu_page_size", 5)),
            self._do_set_settings_menu_page_size,
        )

    def _do_set_settings_menu_page_size(self, value: str) -> None:
        try:
            size = int(value.strip())
            if size <= 0:
                raise ValueError
            self.app.cfg.menu_page_size = size
            save_config(self.app.cfg)
            self.app._settings_page_index = 0
        except Exception as e:
            self.app._show_toast(f"Invalid number (> 0): {e}")
        # Only add to navigation stack if it's not already there
        if self.app._navigation_manager.peek_screen() != "config_menu":
            self.app._navigation_manager.push_screen("config_menu")
        self.show_config_menu()
