from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
)

from . import storage
from .config import AppConfig, RepoConfig, load_config
from .config_manager import ConfigManager
from .event_handler import EventHandler
from .github import GITHUB_API, GitHubClient, PullRequest, filter_prs
from .markdown_manager import MarkdownManager
from .navigation import NavigationManager
from .ui import MenuManager, OverlayManager, PromptManager, PRTable, StatusManager


@dataclass
class MenuItem:
    """Menu item dataclass."""

    key: str
    label: str


MAIN_MENU: list[MenuItem] = [
    MenuItem("list_all_prs", "List tracked PRs"),
    MenuItem("list_repos", "List tracked repos"),
    MenuItem("list_accounts", "List tracked accounts"),
    MenuItem("prs_per_repo", "List PRs per repo"),
    MenuItem("prs_per_account", "List PRs per account"),
    MenuItem("save_markdown", "Save PRs to Markdown"),
    MenuItem("config", "Settings"),
    MenuItem("exit", "Exit"),
]


class PRTrackApp(App):
    """Textual TUI application for tracking GitHub pull requests."""

    CSS = """
    #table-title { padding: 1 0; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "go_home", "Home"),
        Binding("backspace", "go_back", "Back"),
        Binding("r", "refresh_current", "Refresh"),
        Binding("]", "next_page", "Next Page"),
        Binding("[", "prev_page", "Prev Page"),
        Binding("m", "toggle_markdown_pr", "Mark for MD"),
        Binding("enter", "accept_markdown_selection", "Accept (MD)"),
        Binding("?", "show_keymap_overlay", "Help/Keys"),
    ]

    screen_mode = reactive("menu")

    def __init__(self) -> None:
        """Initialize application state and widgets.

        Initializes configuration, API client, UI widgets, and cache/refresh state.
        """
        super().__init__()
        self.cfg: AppConfig = load_config()
        self.client = GitHubClient(self.cfg.auth_token)
        self._menu = ListView(*[ListItem(Label(mi.label), id=mi.key) for mi in MAIN_MENU])
        # Prefer native wrap if the Textual version supports it
        with contextlib.suppress(Exception):
            self._menu.wrap = True
        with contextlib.suppress(Exception):
            # Enable circular navigation if supported by Textual version
            self._menu.wrap = True  # type: ignore[attr-defined]
        self._table = PRTable("Pull Requests")
        self._status = Label("", id="status")
        # Refresh state
        self._current_scope: tuple[str, str | None] = ("menu", None)  # (kind, value)
        self._stale_after_seconds: int = self.cfg.staleness_threshold_seconds
        self._refresh_task: asyncio.Task | None = None
        # Pagination state
        self._page_size: int = int(getattr(self.cfg, "pr_page_size", 10) or 10)
        self._page: int = 1
        self._current_prs: list[PullRequest] = []
        # Overlay selection context (for repo/account lists, config lists, etc.)
        self._overlay_container: Vertical | None = None
        self._overlay_list: ListView | None = None
        self._overlay_select_action: Callable[[str], None] | None = None
        # Navigation stack to track previous screens
        self._navigation_stack: list[str] = []
        # Markdown selection state
        self._md_mode: bool = False
        self._md_selected: dict[tuple[str, int], PullRequest] = {}
        self._md_scope: tuple[str, str | None] | None = None  # (kind, value)
        self._settings_page_index: int = 0
        # Key mapping (defaults in code, optional overrides from cfg)
        self._keymap_defaults: dict[str, str] = {
            "next_page": "]",
            "prev_page": "[",
            "open_pr": "enter",
            "mark_markdown": "m",
            "back": "backspace",
        }
        self._keymap: dict[str, str] = {
            **self._keymap_defaults,
            **getattr(self.cfg, "keymap", {}),
        }
        # Initialize UI managers
        self._menu_manager = MenuManager(self)
        self._overlay_manager = OverlayManager(self)
        self._prompt_manager = PromptManager(self)
        self._status_manager = StatusManager(self)
        self._navigation_manager = NavigationManager(self)
        self._config_manager = ConfigManager(self)
        self._markdown_manager = MarkdownManager(self)
        self._event_handler = EventHandler(self)

    def compose(self) -> ComposeResult:
        """Compose the main layout containing header, menu, status, table, and footer."""
        yield Header(show_clock=False)
        with Vertical():
            yield self._menu
            yield self._status
            yield self._table
        yield Footer()

    def on_mount(self) -> None:
        """Show the menu on startup."""
        self._show_menu()

    def action_go_home(self) -> None:
        """Keyboard action to return to the home screen and clear overlays."""
        # Remove any overlay container if present
        if self._overlay_container is not None:
            with contextlib.suppress(Exception):
                self._overlay_container.remove()
            self._overlay_container = None
            self._overlay_list = None
            self._overlay_select_action = None
        # Ensure any prompt overlays are removed to avoid duplicate IDs
        self._remove_all_prompts()
        # Exit markdown mode if active
        self._md_mode = False
        self._md_scope = None
        self._show_menu()

    def action_go_back(self) -> None:
        """Context back: close overlays or return to previous selection menu."""
        self._remove_all_prompts()
        if self._close_overlay_if_open():
            return
        if self._navigation_manager.handle_markdown_back_if_needed():
            return
        self._navigation_manager.navigate_back_or_home()

    def action_accept_markdown_selection(self) -> None:
        """In markdown selection mode, return to the markdown menu."""
        if not self._md_mode:
            return
        # Return to the markdown menu without clearing selection
        self._markdown_manager.show_markdown_menu()

    def _show_menu(self) -> None:
        """Display the main menu and hide the table."""
        self._menu_manager.show_menu()

    def action_refresh_current(self) -> None:
        """Refresh the data for the current view.

        Depending on the active scope (all, repo, or account), schedule a background
        refresh and update the status indicator. No-op on the menu screen.
        """
        kind, value = self._current_scope
        if kind == "all":
            self._schedule_refresh_all()
        elif kind == "repo" and value:
            self._schedule_refresh_repo(value)
        elif kind == "account" and value:
            self._schedule_refresh_account(value)

    async def _load_all_prs(self) -> list[PullRequest]:
        """Fetch open PRs from all configured repositories from GitHub.

        This is a network call; prefer using cache-first helpers for UI flows.

        Returns:
            List of `PullRequest` objects sorted by descending PR number.
        """
        all_prs: list[PullRequest] = []
        global_users = set(self.cfg.global_users)
        # Prepare tasks per valid repo
        tasks: list[tuple[RepoConfig, asyncio.Task[list[PullRequest]]]] = []
        for rc in self.cfg.repositories:
            try:
                owner, repo = rc.name.split("/", 1)
            except ValueError:
                continue
            task = asyncio.create_task(self.client.list_open_prs(owner, repo))
            tasks.append((rc, task))

        if not tasks:
            return []

        # Await all repo requests concurrently
        results = await asyncio.gather(*[t for _, t in tasks], return_exceptions=True)

        # Apply per-repo filters and collect, ignoring failed repos
        for (rc, _), result in zip(tasks, results, strict=False):
            if isinstance(result, Exception):
                continue
            prs = result
            users = set(rc.users or []) or global_users
            if users:
                prs = filter_prs(prs, users)
            all_prs.extend(prs)
        # sort newest first by number (approx)
        all_prs.sort(key=lambda p: p.number, reverse=True)
        return all_prs

    async def _load_prs_by_repo(self, repo_name: str) -> list[PullRequest]:
        """Fetch open PRs for a single repository from GitHub, applying user filters.

        Args:
            repo_name: The repository in "owner/repo" format.

        Returns:
            List of `PullRequest` objects sorted by descending PR number.
        """
        try:
            owner, repo = repo_name.split("/", 1)
        except ValueError:
            return []
        prs = await self.client.list_open_prs(owner, repo)
        users = set(next((r.users or [] for r in self.cfg.repositories if r.name == repo_name), [])) or set(
            self.cfg.global_users
        )
        if users:
            prs = filter_prs(prs, users)
        prs.sort(key=lambda p: p.number, reverse=True)
        return prs

    async def _load_prs_by_account(self, account: str) -> list[PullRequest]:
        """Fetch open PRs authored by or assigned to a given account from GitHub.

        Args:
            account: GitHub username to filter by.

        Returns:
            A filtered list of `PullRequest` objects.
        """
        prs = await self._load_all_prs()
        return filter_prs(prs, {account})

    async def _load_single_pr(self, owner: str, repo: str, pr_number: int) -> PullRequest | None:
        """Fetch a single PR from GitHub.

        Args:
            owner: Repository owner/org login.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            A `PullRequest` object or None if not found.
        """
        try:
            data = await self.client._get(f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}")
            pr = PullRequest(
                repo=f"{owner}/{repo}",
                number=data["number"],
                title=data["title"],
                author=data["user"]["login"],
                assignees=[a["login"] for a in data.get("assignees", [])],
                branch=data["head"]["ref"],
                draft=bool(data.get("draft", False)),
                approvals=0,  # Will be filled below
                html_url=data["html_url"],
            )
            # Fetch approvals
            approvals = await self.client._count_approvals(owner, repo, pr.number)
            pr.approvals = approvals
            return pr
        except Exception:
            return None

    async def _show_prs(self, loader) -> None:
        """Execute a loader coroutine and display results in the table.

        Args:
            loader: An async callable returning `list[PullRequest]`.
        """
        prs = await loader()
        self._table.set_prs(prs)
        self._menu.display = False
        self._table.display = True
        self._status.display = True
        self._table.focus()

    # ---------------- Cache-first helpers ----------------

    def _update_status_label(self, scope: str, refreshing: bool) -> None:
        """Update status label with last refreshed info and refreshing indicator.

        Args:
            scope: Scope key as used for refresh records.
            refreshing: Whether a background refresh is running.
        """
        self._status_manager.update_status_label(scope, refreshing)

    def _render_current_page(self) -> None:
        """Render the current page from `_current_prs` into the table."""
        # Calculate start and end indices for the current page
        start_idx = (self._page - 1) * self._page_size
        end_idx = start_idx + self._page_size
        # Get the PRs for the current page
        page_prs = self._current_prs[start_idx:end_idx]
        self._table.set_prs(page_prs)
        # Update status in markdown mode
        if self._md_mode:
            self._update_markdown_status()

    def _current_scope_key(self) -> str:
        """Return the current scope key used for refresh metadata."""
        kind, value = self._current_scope
        if kind == "all":
            return "all"
        if kind == "repo" and value:
            return f"repo:{value}"
        if kind == "account" and value:
            return f"account:{value}"
        return "menu"

    def _show_cached_all(self) -> None:
        """Display cached PRs for 'all' scope, applying config filters, and maybe refresh."""
        self._current_scope = ("all", None)
        # Aggregate per-repo from cache to apply per-repo/global filters
        all_prs: list[PullRequest] = []
        global_users = set(self.cfg.global_users)
        for rc in self.cfg.repositories:
            repo_prs = storage.get_cached_prs_by_repo(rc.name)
            users = set(rc.users or []) or global_users
            if users:
                repo_prs = filter_prs(repo_prs, users)
            all_prs.extend(repo_prs)
        # Sort newest first
        all_prs.sort(key=lambda p: p.number, reverse=True)
        self._current_prs = all_prs
        self._page = 1
        self._render_current_page()
        self._menu.display = False
        self._table.display = True
        scope = "all"
        should_refresh = self._is_stale(scope)
        self._update_status_label(scope, refreshing=should_refresh)
        if should_refresh:
            self._schedule_refresh_all()

    def _show_cached_repo(self, repo_name: str) -> None:
        """Display cached PRs for a repository and schedule refresh if stale."""
        self._current_scope = ("repo", repo_name)
        cached = storage.get_cached_prs_by_repo(repo_name)
        self._current_prs = cached
        self._page = 1
        self._render_current_page()
        self._menu.display = False
        self._table.display = True
        scope = f"repo:{repo_name}"
        should_refresh = self._is_stale(scope)
        self._update_status_label(scope, refreshing=should_refresh)
        if should_refresh:
            self._schedule_refresh_repo(repo_name)

    def _show_cached_account(self, account: str) -> None:
        """Display cached PRs for an account and schedule refresh if stale."""
        self._current_scope = ("account", account)
        cached = storage.get_cached_prs_by_account(account)
        self._current_prs = cached
        self._page = 1
        self._render_current_page()
        self._menu.display = False
        self._table.display = True
        scope = f"account:{account}"
        should_refresh = self._is_stale(scope)
        self._update_status_label(scope, refreshing=should_refresh)
        if should_refresh:
            self._schedule_refresh_account(account)

    def _is_stale(self, scope: str) -> bool:
        """Check if data is stale based on configured threshold.

        Args:
            scope: Scope key for last refresh lookup.

        Returns:
            True if no refresh timestamp or older than threshold.
        """
        last = storage.get_last_refresh(scope)
        if last is None:
            return True
        return (int(time.time()) - int(last)) > self._stale_after_seconds

    def _refresh_table_with_updated_pr(self, updated_pr: PullRequest) -> None:
        """Refresh the table with the updated PR data."""
        # Get current PRs from the table
        # For now, we'll just refresh the entire table
        # In a more sophisticated implementation, we could update just the specific row
        kind, value = self._current_scope
        if kind == "all":
            self._show_cached_all()
        elif kind == "repo" and value:
            self._show_cached_repo(value)
        elif kind == "account" and value:
            self._show_cached_account(value)

    # ---------------- Background refresh scheduling ----------------
    def _cancel_existing_refresh(self) -> None:
        """Cancel any in-flight background refresh task safely."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = None

    def _schedule_refresh_all(self) -> None:
        """Schedule background refresh for all repositories."""
        self._cancel_existing_refresh()
        scope = "all"
        self._update_status_label(scope, refreshing=True)

        async def runner() -> None:
            try:
                await self._refresh_all_repositories(scope)
            except Exception:
                # On error, don't update the cache, keep existing data
                # Re-aggregate current cached data to ensure consistency
                await self._refresh_error_handling()
            finally:
                self._update_status_label(scope, refreshing=False)

        self._refresh_task = asyncio.create_task(runner())

    async def _refresh_all_repositories(self, scope: str) -> None:
        """Refresh all repositories with concurrent requests."""
        global_users = set(self.cfg.global_users)

        # Prepare tasks per valid repo
        tasks: list[tuple[RepoConfig, asyncio.Task[list[PullRequest]]]] = []
        for rc in self.cfg.repositories:
            try:
                owner, repo = rc.name.split("/", 1)
            except ValueError:
                continue
            task = asyncio.create_task(self.client.list_open_prs(owner, repo))
            tasks.append((rc, task))

        if not tasks:
            # No valid repositories to refresh
            # Re-aggregate current cached data
            self._refresh_no_valid_repos(global_users)
            return

        # Await all repo requests concurrently
        results = await asyncio.gather(*[t for _, t in tasks], return_exceptions=True)

        # Process each repo's results individually using sync_repo_prs
        for (rc, _), result in zip(tasks, results, strict=False):
            if isinstance(result, Exception):
                # Skip failed repos, keep their existing cache
                continue
            prs = result
            users = set(rc.users or []) or global_users
            if users:
                prs = filter_prs(prs, users)
            # Use sync_repo_prs to replace all PRs for this repo with new data
            storage.sync_repo_prs(rc.name, prs)

        storage.record_last_refresh(scope)

        # Re-aggregate current cached data after all sync operations
        all_prs: list[PullRequest] = self._reaggregate_cached_data(global_users)
        self._current_prs = all_prs
        self._render_current_page()

    def _refresh_no_valid_repos(self, global_users: set[str]) -> None:
        """Handle case where no valid repositories exist."""
        all_prs: list[PullRequest] = self._reaggregate_cached_data(global_users)
        self._current_prs = all_prs
        self._render_current_page()

    def _reaggregate_cached_data(self, global_users: set[str]) -> list[PullRequest]:
        """Re-aggregate current cached data."""
        all_prs: list[PullRequest] = []
        for rc in self.cfg.repositories:
            repo_prs = storage.get_cached_prs_by_repo(rc.name)
            users = set(rc.users or []) or global_users
            if users:
                repo_prs = filter_prs(repo_prs, users)
            all_prs.extend(repo_prs)
        all_prs.sort(key=lambda p: p.number, reverse=True)
        return all_prs

    async def _refresh_error_handling(self) -> None:
        """Handle errors during refresh by re-aggregating cached data."""
        global_users = set(self.cfg.global_users)
        all_prs: list[PullRequest] = self._reaggregate_cached_data(global_users)
        self._current_prs = all_prs
        self._render_current_page()

    def _schedule_refresh_repo(self, repo_name: str) -> None:
        """Schedule background refresh for a repository."""
        self._cancel_existing_refresh()
        scope = f"repo:{repo_name}"
        self._update_status_label(scope, refreshing=True)

        async def runner() -> None:
            try:
                prs = await self._load_prs_by_repo(repo_name)
                # Use sync_repo_prs to replace all PRs for this repo with new data
                storage.sync_repo_prs(repo_name, prs)
                storage.record_last_refresh(scope)
                self._current_prs = storage.get_cached_prs_by_repo(repo_name)
                self._render_current_page()
            except Exception:
                # On error, don't update the cache, keep existing data
                # Re-get cached data to ensure consistency
                self._current_prs = storage.get_cached_prs_by_repo(repo_name)
                self._render_current_page()
            finally:
                self._update_status_label(scope, refreshing=False)

        self._refresh_task = asyncio.create_task(runner())

    def _schedule_refresh_account(self, account: str) -> None:
        """Schedule background refresh for an account."""
        self._cancel_existing_refresh()
        scope = f"account:{account}"
        self._update_status_label(scope, refreshing=True)

        async def runner() -> None:
            try:
                # First, get all repositories that might have PRs for this account
                # by using the existing load method which aggregates from all repos
                prs = await self._load_prs_by_account(account)

                # Group PRs by repository to sync each repo individually
                repo_prs_map: dict[str, list[PullRequest]] = {}
                for pr in prs:
                    if pr.repo not in repo_prs_map:
                        repo_prs_map[pr.repo] = []
                    repo_prs_map[pr.repo].append(pr)

                # Sync each repository that has PRs for this account
                for repo_name, repo_prs in repo_prs_map.items():
                    storage.sync_repo_prs(repo_name, repo_prs)

                storage.record_last_refresh(scope)
                self._current_prs = storage.get_cached_prs_by_account(account)
                self._render_current_page()
            except Exception:
                # On error, don't update the cache, keep existing data
                # Re-get cached data to ensure consistency
                self._current_prs = storage.get_cached_prs_by_account(account)
                self._render_current_page()
            finally:
                self._update_status_label(scope, refreshing=False)

        self._refresh_task = asyncio.create_task(runner())

    def _schedule_refresh_single_pr(self, pr: PullRequest) -> None:
        """Schedule background refresh for a single PR."""
        self._cancel_existing_refresh()
        scope = f"pr:{pr.repo}/{pr.number}"
        self._update_status_label(scope, refreshing=True)

        async def runner() -> None:
            # Parse repo owner and name
            try:
                owner, repo_name = pr.repo.split("/", 1)
            except ValueError:
                self._update_status_label(scope, refreshing=False)
                return

            # Load the specific PR
            try:
                # We need to create a new method to fetch a single PR
                single_pr = await self._load_single_pr(owner, repo_name, pr.number)
                if single_pr:
                    # Update the PR in storage using upsert_prs since it's just one PR
                    storage.upsert_prs([single_pr])
                    # Update the table with the refreshed PR
                    self._refresh_table_with_updated_pr(single_pr)
                    # Show toast notification
                    self._show_toast(f"PR {pr.repo}#{pr.number} refreshed")
            except Exception:
                # On error, don't update the cache, keep existing data
                pass  # Silently fail for now
            finally:
                self._update_status_label(scope, refreshing=False)

        self._refresh_task = asyncio.create_task(runner())

    def _show_toast(self, message: str) -> None:
        """Show a toast notification for a short time."""
        # Use Textual's built-in notification system
        self.notify(message, title="PR Tracker", timeout=3)

    # ---------- Pagination actions and wrap workaround ----------

    def action_next_page(self) -> None:
        """Move to the next page of PRs."""
        if not self._current_prs:
            return
        # Calculate total number of pages
        total_pages = max(1, (len(self._current_prs) + self._page_size - 1) // self._page_size)
        # Move to next page, wrapping to first page if at the end
        self._page = (self._page % total_pages) + 1
        self._render_current_page()
        scope = self._current_scope_key()
        self._update_status_label(scope, refreshing=False)

    def action_prev_page(self) -> None:
        """Move to the previous page of PRs."""
        if not self._current_prs:
            return
        # Calculate total number of pages
        total_pages = max(1, (len(self._current_prs) + self._page_size - 1) // self._page_size)
        # Move to previous page, wrapping to last page if at the beginning
        self._page = (self._page - 2 + total_pages) % total_pages + 1
        self._render_current_page()
        scope = self._current_scope_key()
        self._update_status_label(scope, refreshing=False)

    def _show_list(self, title: str, items: list[str], select_action=None) -> None:
        """Display a list overlay for selecting an item.

        Args:
            title: Title displayed above the list.
            items: Items to display (also used as their IDs).
            select_action: Callback invoked with the selected item ID.
        """
        self._menu_manager.show_list(title, items, select_action)

    def _table_has_focus(self) -> bool:
        """Return True if the inner DataTable currently has keyboard focus."""
        try:
            return bool(getattr(self._table.table, "has_focus", False))
        except Exception:
            return False

    def _select_repo(self, repo_name: str) -> None:
        """Handle repo selection by displaying PRs for the chosen repo.

        Args:
            repo_name: Repository in "owner/repo" format.
        """
        self._load_repo_prs(repo_name)

    def _select_account(self, account: str) -> None:
        """Handle account selection by displaying PRs for the account.

        Args:
            account: GitHub username.
        """
        self._load_account_prs(account)

    def _load_repo_prs(self, repo_name: str) -> None:
        """Trigger loading and displaying PRs for the selected repo.

        Args:
            repo_name: Repository in "owner/repo" format.
        """
        self._show_cached_repo(repo_name)

    def _load_account_prs(self, account: str) -> None:
        """Trigger loading and displaying PRs for the selected account.

        Args:
            account: GitHub username.
        """
        self._show_cached_account(account)

    # ---------------- Config menu ----------------

    def _show_config_menu(self, is_from_main_menu: bool = False) -> None:
        """Display Settings menu as an overlay list."""
        self._config_manager.show_config_menu(is_from_main_menu)

    def _show_choice_menu(self, title: str, actions: list[tuple[str, str]]) -> None:
        """Show a simple menu of labeled actions.

        Args:
            title: Menu title.
            actions: List of (key, label) tuples used to build the list.
        """
        self._menu_manager.show_choice_menu(title, actions)

    # ---------- Markdown selection & export ----------

    def _show_markdown_menu(self) -> None:
        """Display the markdown menu and handle markdown actions."""
        self._markdown_manager.show_markdown_menu()

    def _handle_markdown_action(self, action: str) -> None:
        """Route a selected markdown action to its handler.

        Args:
            action: Action key from the markdown menu.
        """
        self._markdown_manager.handle_markdown_action(action)

    def _update_markdown_status(self) -> None:
        """Update the markdown status display."""
        self._status_manager.update_markdown_status()

    def _enter_md_mode(self, kind: str, value: str | None) -> None:
        """Enter markdown selection mode for a specific scope.

        Args:
            kind: The type of scope ("repo" or "account").
            value: The specific repo or account name.
        """
        self._markdown_manager.enter_md_mode(kind, value)

    def _md_select_repo(self, repo_name: str) -> None:
        """Handle repo selection in markdown mode.

        Args:
            repo_name: Repository in "owner/repo" format.
        """
        self._markdown_manager.md_select_repo(repo_name)

    def _md_select_account(self, account: str) -> None:
        """Handle account selection in markdown mode.

        Args:
            account: GitHub username.
        """
        self._markdown_manager.md_select_account(account)

    def action_toggle_markdown_pr(self) -> None:
        """Toggle PR selection in markdown mode."""
        self._markdown_manager.toggle_markdown_pr()

    def _md_review_selection(self) -> None:
        """Review the current markdown selection."""
        self._markdown_manager.md_review_selection()

    def _md_deselect(self, label: str) -> None:
        """Deselect a PR from the markdown selection.

        Args:
            label: Label of the PR to deselect in format "owner/repo#num - title".
        """
        self._markdown_manager.md_deselect(label)

    def _prompt_save_markdown(self) -> None:
        """Prompt for markdown save path."""
        self._markdown_manager.prompt_save_markdown()

    def _do_save_markdown(self, path: str) -> None:
        """Save selected PRs to a markdown file.

        Args:
            path: Path to save the markdown file.
        """
        self._markdown_manager.do_save_markdown(path)

    def _handle_config_action(self, action: str) -> None:
        """Route a selected config action to its handler.

        Args:
            action: Action key from the config menu.
        """
        self._config_manager.handle_config_action(action)

    def action_show_keymap_overlay(self) -> None:
        """Show an overlay with current key bindings; selecting any item closes it."""
        items: list[str] = []
        items.append("Key bindings (press Back or select any item to close):")
        for k in sorted(self._keymap.keys()):
            ov = self.cfg.keymap.get(k) if hasattr(self.cfg, "keymap") else None
            mark = " (default)" if ov is None else ""
            items.append(f"{k}: {self._keymap[k]}{mark}")
        self._show_list("Help / Key bindings", items, select_action=lambda _val: self.action_go_back())

    def _remove_all_prompts(self) -> None:
        """Remove all prompt overlays (one and two-field) if present."""
        self._overlay_manager.remove_all_prompts()

    # ---------------- Small helpers extracted to reduce branching ----------------

    def _close_overlay_if_open(self) -> bool:
        """Close overlay if present and navigate back.

        Returns:
            True if an overlay was closed and navigation occurred; False otherwise.
        """
        return self._overlay_manager.close_overlay_if_open()

    # ---------------- Event handler delegation ----------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle item selection from either the main menu or overlays."""
        self._event_handler.on_list_view_selected(event)

    def on_key(self, event) -> None:  # type: ignore[override]
        """Key handling: wrapping for lists and custom key mappings."""
        self._event_handler.on_key(event)

    def on_pr_table_open_requested(self, message: PRTable.OpenRequested) -> None:
        """Open the selected PR in the default web browser."""
        self._event_handler.on_pr_table_open_requested(message)

    def on_pr_table_pr_refresh_requested(self, message: PRTable.PRRefreshRequested) -> None:
        """Refresh the selected PR."""
        self._event_handler.on_pr_table_pr_refresh_requested(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle OK/Cancel button presses for prompt overlays."""
        self._event_handler.on_button_pressed(event)
