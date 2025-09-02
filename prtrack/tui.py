from __future__ import annotations

import asyncio
import contextlib
import os
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

from . import storage
from .config import AppConfig, RepoConfig, load_config, save_config
from .github import GITHUB_API, GitHubClient, PullRequest, filter_prs
from .ui import PRTable
from .utils.markdown import write_prs_markdown
from .utils.time import format_time_ago


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
        if self._handle_markdown_back_if_needed():
            return
        self._navigate_back_or_home()

    def action_accept_markdown_selection(self) -> None:
        """In markdown selection mode, return to the markdown menu."""
        if not self._md_mode:
            return
        # Return to the markdown menu without clearing selection
        self._show_markdown_menu()

    def _show_menu(self) -> None:
        """Display the main menu and hide the table."""
        self.screen_mode = "menu"
        self._menu.display = True
        self._table.display = False
        self._status.display = False
        self._menu.focus()
        # Clear navigation stack when going back to main menu
        self._navigation_stack.clear()

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
        last = storage.get_last_refresh(scope)
        if last is None:
            text = "Last refresh: never"
        else:
            ago = max(0, int(time.time()) - int(last))
            text = f"Last refresh: {format_time_ago(ago)}"
        if refreshing:
            text += " • Refreshing…"
        # Append pagination info when applicable
        total = len(self._current_prs)
        if total:
            pages = max(1, (total + self._page_size - 1) // self._page_size)
            text += f" • Page {self._page}/{pages} ({total} PRs)"
        self._status.update(text)
        self._status.display = True

    def _render_current_page(self) -> None:
        """Render the current page from `_current_prs` into the table."""
        total = len(self._current_prs)
        if total == 0:
            self._table.set_prs([])
            return
        pages = max(1, (total + self._page_size - 1) // self._page_size)
        self._page = max(1, min(self._page, pages))
        start = (self._page - 1) * self._page_size
        end = start + self._page_size
        self._table.set_prs(self._current_prs[start:end])
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
            prs = await self._load_all_prs()
            storage.upsert_prs(prs)
            storage.record_last_refresh(scope)
            # Re-aggregate to apply current filters and pagination
            all_prs: list[PullRequest] = []
            global_users = set(self.cfg.global_users)
            for rc in self.cfg.repositories:
                repo_prs = storage.get_cached_prs_by_repo(rc.name)
                users = set(rc.users or []) or global_users
                if users:
                    repo_prs = filter_prs(repo_prs, users)
                all_prs.extend(repo_prs)
            all_prs.sort(key=lambda p: p.number, reverse=True)
            self._current_prs = all_prs
            self._render_current_page()
            self._update_status_label(scope, refreshing=False)

        self._refresh_task = asyncio.create_task(runner())

    def _schedule_refresh_repo(self, repo_name: str) -> None:
        """Schedule background refresh for a repository."""
        self._cancel_existing_refresh()
        scope = f"repo:{repo_name}"
        self._update_status_label(scope, refreshing=True)

        async def runner() -> None:
            prs = await self._load_prs_by_repo(repo_name)
            storage.upsert_prs(prs)
            storage.record_last_refresh(scope)
            self._current_prs = storage.get_cached_prs_by_repo(repo_name)
            self._render_current_page()
            self._update_status_label(scope, refreshing=False)

        self._refresh_task = asyncio.create_task(runner())

    def _schedule_refresh_account(self, account: str) -> None:
        """Schedule background refresh for an account."""
        self._cancel_existing_refresh()
        scope = f"account:{account}"
        self._update_status_label(scope, refreshing=True)

        async def runner() -> None:
            prs = await self._load_prs_by_account(account)
            storage.upsert_prs(prs)
            storage.record_last_refresh(scope)
            self._current_prs = storage.get_cached_prs_by_account(account)
            self._render_current_page()
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
                    # Update the PR in storage
                    storage.upsert_prs([single_pr])
                    # Update the table with the refreshed PR
                    self._refresh_table_with_updated_pr(single_pr)
                    # Show toast notification
                    self._show_toast(f"PR {pr.repo}#{pr.number} refreshed")
            except Exception:
                pass  # Silently fail for now
            finally:
                self._update_status_label(scope, refreshing=False)

        self._refresh_task = asyncio.create_task(runner())

    def _show_toast(self, message: str) -> None:
        """Show a toast notification for a short time."""
        # Use Textual's built-in notification system
        self.notify(message, title="PR Tracker", timeout=3)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle item selection from either the main menu or overlays.

        Args:
            event: The selection event emitted by `ListView`.
        """
        if self._handle_overlay_selection_if_any(event):
            return
        self._handle_main_menu_selection_if_any(event)

    # ---------- Pagination actions and wrap workaround ----------

    def action_next_page(self) -> None:
        if not self._current_prs:
            return
        total = len(self._current_prs)
        pages = max(1, (total + self._page_size - 1) // self._page_size)
        if self._page < pages:
            self._page += 1
        else:
            self._page = 1
        self._render_current_page()
        scope = self._current_scope_key()
        self._update_status_label(scope, refreshing=False)

    def action_prev_page(self) -> None:
        if not self._current_prs:
            return
        total = len(self._current_prs)
        pages = max(1, (total + self._page_size - 1) // self._page_size)
        if self._page > 1:
            self._page -= 1
        else:
            self._page = pages
        self._render_current_page()
        scope = self._current_scope_key()
        self._update_status_label(scope, refreshing=False)

    def on_key(self, event) -> None:  # type: ignore[override]
        """Key handling: wrapping for lists and custom key mappings."""
        key = getattr(event, "key", None)
        if key is None:
            return
        if self._handle_custom_keymap(key, event):
            return
        self._handle_list_wrap_key(key, event)

    @staticmethod
    def _maybe_wrap_index(count: int, idx: int, key: str) -> int | None:
        """Return wrapped index if at boundary for key, otherwise None.

        Args:
            count: Number of items.
            idx: Current index.
            key: 'up' or 'down'.

        Returns:
            New index if wrapping should occur; otherwise None.
        """
        if count <= 0:
            return None
        if key == "up" and idx == 0:
            return count - 1
        if key == "down" and idx == count - 1:
            return 0
        return None

    def _show_list(self, title: str, items: list[str], select_action=None) -> None:
        """Display a list overlay for selecting an item.

        Args:
            title: Title displayed above the list.
            items: Items to display (also used as their IDs).
            select_action: Callback invoked with the selected item ID.
        """
        self._menu.display = False
        self._table.display = False
        # Clear any stray prompts before mounting an overlay
        self._remove_all_prompts()
        # Replace existing overlay container if present (avoid stacking)
        if self._overlay_container is not None:
            with contextlib.suppress(Exception):
                self._overlay_container.remove()
            self._overlay_container = None
            self._overlay_list = None
            self._overlay_select_action = None
        # Build items without IDs (some values contain slashes or spaces). Store original value.
        li_items: list[ListItem] = []
        for it in items:
            li = ListItem(Label(it))
            li._value = it
            li_items.append(li)
        list_view = ListView(*li_items)
        with contextlib.suppress(Exception):
            list_view.wrap = True
        list_view.can_focus = True
        with contextlib.suppress(Exception):
            list_view.wrap = True  # type: ignore[attr-defined]
        container = Vertical(Label(title), list_view)
        self.mount(container)
        # Ensure keyboard focus is on the overlay list (not hidden widgets)
        self.set_focus(list_view)
        # Ensure a valid starting selection for keyboard navigation
        with contextlib.suppress(Exception):
            if list_view.children:
                list_view.index = 0
        # Store overlay context; selection will be handled in on_list_view_selected
        self._overlay_container = container
        self._overlay_list = list_view
        self._overlay_select_action = select_action

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

    def on_pr_table_open_requested(self, message: PRTable.OpenRequested) -> None:
        """Open the selected PR in the default web browser.

        Args:
            message: Message carrying the `PullRequest` to open.
        """
        # In markdown selection mode, ignore open on Enter
        if self._md_mode:
            return
        webbrowser.open(message.pr.html_url)

    def on_pr_table_pr_refresh_requested(self, message: PRTable.PRRefreshRequested) -> None:
        """Refresh the selected PR.

        Args:
            message: Message carrying the `PullRequest` to refresh.
        """
        self._schedule_refresh_single_pr(message.pr)

    # ---------------- Config menu ----------------

    def _show_config_menu(self, is_from_main_menu: bool = False) -> None:
        """Display Settings menu as an overlay list."""
        # Push to navigation stack if coming from main menu
        if is_from_main_menu:
            # Clear the navigation stack when coming from main menu to avoid accumulation
            self._navigation_stack.clear()
            self._navigation_stack.append("main_menu")
            self._settings_page_index = 0

        actions = [
            ("add_repo", "Add repo"),
            ("remove_repo", "Remove repo"),
            ("add_account", "Add account"),
            ("remove_account", "Remove account"),
            ("set_stale", "Set staleness threshold (seconds)"),
            ("set_page_size", "Set PRs per page"),
            ("set_settings_page_size", "Set Settings menu page size"),
            ("update_token", "Update GitHub token"),
            ("keymap_menu", "Key bindings"),
            ("show_keymap", "Show current key bindings"),
            ("show_config", "Show current config"),
        ]
        # Paginate actions
        page_size = max(1, int(getattr(self.cfg, "menu_page_size", 5)))
        total = len(actions)
        pages = max(1, (total + page_size - 1) // page_size)
        index = max(0, min(self._settings_page_index, pages - 1))
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
        self._show_choice_menu(title, page_actions)

    def _show_choice_menu(self, title: str, actions: list[tuple[str, str]]) -> None:
        """Show a simple menu of labeled actions.

        Args:
            title: Menu title.
            actions: List of (key, label) tuples used to build the list.
        """
        self._menu.display = False
        self._table.display = False
        # Build items without IDs; keep the action key on the item
        # Replace existing overlay container if present (avoid stacking)
        if self._overlay_container is not None:
            with contextlib.suppress(Exception):
                self._overlay_container.remove()
            self._overlay_container = None
            self._overlay_list = None
            self._overlay_select_action = None
        li_actions: list[ListItem] = []
        for key, lbl in actions:
            li = ListItem(Label(lbl))
            li._value = key
            li_actions.append(li)
        list_view = ListView(*li_actions)
        with contextlib.suppress(Exception):
            list_view.wrap = True
        list_view.can_focus = True
        with contextlib.suppress(Exception):
            list_view.wrap = True  # type: ignore[attr-defined]
        container = Vertical(Label(title), list_view)
        self.mount(container)
        # Ensure keyboard focus is on the overlay list
        self.set_focus(list_view)
        # Ensure a valid starting selection for keyboard navigation
        with contextlib.suppress(Exception):
            if list_view.children:
                list_view.index = 0
        # Use overlay selection context; selection handled in on_list_view_selected
        self._overlay_container = container
        self._overlay_list = list_view
        # Wrap to route to config action handler
        self._overlay_select_action = lambda key: self._handle_config_action(key)

    # ---------- Markdown selection & export ----------

    def _show_markdown_menu(self) -> None:
        actions = [
            ("md_by_repo", "Select PRs by Repo"),
            ("md_by_account", "Select PRs by Account"),
            ("md_review", f"Review Selection ({len(self._md_selected)})"),
            ("md_save", "Save Selected to Markdown"),
            ("back", "Back"),
        ]
        self._show_choice_menu("Save PRs to Markdown", actions)
        # Rewire overlay handler to markdown actions
        self._overlay_select_action = lambda key: self._handle_markdown_action(key)

    def _handle_markdown_action(self, action: str) -> None:
        match action:
            case "md_by_repo":
                # Push current screen to navigation stack before showing repo list
                self._navigation_stack.append("markdown_menu")
                self._show_list(
                    "Repos",
                    [r.name for r in self.cfg.repositories],
                    select_action=self._md_select_repo,
                )
            case "md_by_account":
                # Push current screen to navigation stack before showing account list
                self._navigation_stack.append("markdown_menu")
                accounts = sorted(
                    set(self.cfg.global_users) | {u for r in self.cfg.repositories for u in (r.users or [])}
                )
                self._show_list(
                    "Accounts",
                    accounts,
                    select_action=self._md_select_account,
                )
            case "md_review":
                self._md_review_selection()
            case "md_save":
                self._prompt_save_markdown()
            case "back":
                self.action_go_back()
            case _:
                self._show_menu()

    def _update_markdown_status(self) -> None:
        scope = self._current_scope_key()
        count = len(self._md_selected)
        base = "Selecting for Markdown"
        mk = self._keymap.get("mark_markdown", "m")
        bk = self._keymap.get("back", "backspace")
        # Keep line length under 100 chars
        msg = f"{base} • Selected: {count} • Scope: {scope} • Keys: " f"mark='{mk}', back='{bk}', accept='enter'"
        self._status.update(msg)
        self._status.display = True

    def _enter_md_mode(self, kind: str, value: str | None) -> None:
        self._md_mode = True
        self._md_scope = (kind, value)
        self._update_markdown_status()

    def _md_select_repo(self, repo_name: str) -> None:
        # Push the repo selection screen to navigation stack so backspace works correctly
        self._navigation_stack.append("repo_selection")
        self._show_cached_repo(repo_name)
        self._enter_md_mode("repo", repo_name)

    def _md_select_account(self, account: str) -> None:
        # Push the account selection screen to navigation stack so backspace works correctly
        self._navigation_stack.append("account_selection")
        self._show_cached_account(account)
        self._enter_md_mode("account", account)

    def action_toggle_markdown_pr(self) -> None:
        # Only allow marking when in markdown mode AND table is active and focused
        if not (self._md_mode and self._table.display and self._overlay_container is None and self._table_has_focus()):
            return
        pr = self._table.get_selected_pr()
        if not pr:
            return
        key = (pr.repo, pr.number)
        if key in self._md_selected:
            del self._md_selected[key]
            self._show_toast(f"Unmarked {pr.repo}#{pr.number}")
        else:
            self._md_selected[key] = pr
            self._show_toast(f"Marked {pr.repo}#{pr.number}")
        self._update_markdown_status()

    def _md_review_selection(self) -> None:
        items = [f"{repo}#{num} - {pr.title}" for (repo, num), pr in self._md_selected.items()]
        if not items:
            self._show_toast("No PRs selected")
            self._show_markdown_menu()
            return
        # Selecting an item will deselect it
        self._show_list("Review Selection - select to remove", items, select_action=self._md_deselect)

    def _md_deselect(self, label: str) -> None:
        # label format: "owner/repo#num - title"
        try:
            left = label.split(" - ", 1)[0]
            repo, num_str = left.split("#", 1)
            key = (repo, int(num_str))
            if key in self._md_selected:
                del self._md_selected[key]
                self._show_toast(f"Removed {repo}#{num_str}")
        except Exception:
            pass
        self._show_markdown_menu()

    def _prompt_save_markdown(self) -> None:
        if not self._md_selected:
            self._show_toast("No PRs selected")
            self._show_markdown_menu()
            return
        default_path = os.path.join(os.getcwd(), "pr-track.md")
        # Reuse one-field prompt
        self._prompt_one_field("Output markdown path (empty = CWD/pr-track.md)", default_path, self._do_save_markdown)

    def _do_save_markdown(self, path: str) -> None:
        outfile = path.strip() or os.path.join(os.getcwd(), "pr-track.md")
        # Create parent dirs if needed
        with contextlib.suppress(Exception):
            os.makedirs(os.path.dirname(outfile) or ".", exist_ok=True)
        try:
            count = len(self._md_selected)
            write_prs_markdown(self._md_selected.values(), outfile)
            self._show_toast(f"Saved {count} PR(s) to {outfile}")
        except Exception:
            self._show_toast("Failed to save markdown")
        # Exit md mode back to menu but keep selection for convenience
        self._md_mode = False
        self._md_scope = None
        # Check if we should return to markdown menu
        if self._navigation_stack and self._navigation_stack[-1] == "markdown_menu":
            # Remove the markdown_menu entry from stack and show markdown menu
            self._navigation_stack.pop()
            self._show_markdown_menu()
        else:
            self._show_menu()

    def _handle_config_action(self, action: str) -> None:
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
                setattr(self, "_settings_page_index", self._settings_page_index + 1),
                self._show_config_menu(),
            ),
            "settings_prev": lambda: (
                setattr(self, "_settings_page_index", max(0, self._settings_page_index - 1)),
                self._show_config_menu(),
            ),
            "back": self.action_go_back,
        }
        handlers.get(action, self._show_menu)()

    def action_show_keymap_overlay(self) -> None:
        """Show an overlay with current key bindings; selecting any item closes it."""
        items: list[str] = []
        items.append("Key bindings (press Back or select any item to close):")
        for k in sorted(self._keymap.keys()):
            ov = self.cfg.keymap.get(k) if hasattr(self.cfg, "keymap") else None
            mark = " (default)" if ov is None else ""
            items.append(f"{k}: {self._keymap[k]}{mark}")
        self._show_list("Help / Key bindings", items, select_action=lambda _val: self.action_go_back())

    # ---------- Keymap settings ----------

    def _show_current_keymap(self) -> None:
        lines = ["Current Key Bindings (overrides shown; defaults in code):"]
        for k, v in self._keymap.items():
            ov = self.cfg.keymap.get(k) if hasattr(self.cfg, "keymap") else None
            mark = " (default)" if ov is None else ""
            lines.append(f"{k}: {v}{mark}")
        static = Static("\n".join(lines))
        self.mount(static)

        def close_and_back():
            static.remove()
            # Only add to navigation stack if it's not already there
            if not self._navigation_stack or self._navigation_stack[-1] != "config_menu":
                self._navigation_stack.append("config_menu")
            self._show_config_menu()

        self.set_timer(2.0, close_and_back)

    def _show_keymap_menu(self) -> None:
        items = [
            ("next_page", f"next_page → '{self._keymap.get('next_page', '')}'"),
            ("prev_page", f"prev_page → '{self._keymap.get('prev_page', '')}'"),
            ("open_pr", f"open_pr → '{self._keymap.get('open_pr', '')}'"),
            ("mark_markdown", f"mark_markdown → '{self._keymap.get('mark_markdown', '')}'"),
            ("back_key", f"back → '{self._keymap.get('back', '')}'"),
            ("reset_all", "Reset all to defaults"),
            ("back", "Back"),
        ]
        self._show_choice_menu("Key bindings", items)
        self._overlay_select_action = lambda key: self._handle_keymap_action(key)

    def _handle_keymap_action(self, action: str) -> None:
        if action == "reset_all":
            self.cfg.keymap = {}
            save_config(self.cfg)
            self._keymap = {**self._keymap_defaults}
            self._show_keymap_menu()
            return
        if action in self._keymap_defaults:
            current = self._keymap.get(action, "")
            self._prompt_one_field(
                f"Set key for {action} (empty to reset)",
                current,
                lambda v, a=action: self._do_set_keymap(a, v),
            )
            return
        # Only add to navigation stack if it's not already there
        if action == "back":
            self.action_go_back()
        else:
            # Only add to navigation stack if it's not already there
            if not self._navigation_stack or self._navigation_stack[-1] != "config_menu":
                self._navigation_stack.append("config_menu")
            self._show_config_menu()

    def _do_set_keymap(self, action: str, value: str) -> None:
        key = value.strip().lower()
        # Empty value resets to default by removing override
        if not key:
            with contextlib.suppress(Exception):
                if action in self.cfg.keymap:
                    del self.cfg.keymap[action]
            self._keymap[action] = self._keymap_defaults.get(action, key)
        else:
            # Prevent duplicate bindings across actions to avoid conflicts
            for act, mapped in list(self._keymap.items()):
                if act != action and mapped == key:
                    self._keymap[act] = self._keymap_defaults.get(act, mapped)
                    with contextlib.suppress(Exception):
                        if act in self.cfg.keymap:
                            del self.cfg.keymap[act]
            self.cfg.keymap[action] = key
            self._keymap[action] = key
        save_config(self.cfg)
        self._show_keymap_menu()

    def _prompt_add_repo(self) -> None:
        """Prompt the user to add a repository and optional users."""
        # Push current screen to navigation stack
        self._navigation_stack.append("config_menu")
        self._prompt_two_fields("Add Repo", "owner/repo", "optional users (comma)", self._do_add_repo)

    def _do_add_repo(self, repo: str, users_csv: str) -> None:
        """Add a repository to the config.

        Args:
            repo: Repository in "owner/repo" format.
            users_csv: Optional comma-separated usernames to restrict tracking.
        """
        repo = repo.strip()
        users = [u.strip() for u in users_csv.split(",") if u.strip()] if users_csv else []
        if repo:
            self.cfg.repositories.append(RepoConfig(name=repo, users=users or None))
            save_config(self.cfg)
        # Go back to the previous screen using navigation stack
        if self._navigation_stack:
            prev_screen = self._navigation_stack.pop()
            if prev_screen == "config_menu":
                self._show_config_menu()
            else:
                self._show_menu()
        else:
            self._show_menu()

    def _prompt_remove_repo(self) -> None:
        """Prompt for selecting a repository to remove from the config."""
        # Push current screen to navigation stack
        self._navigation_stack.append("config_menu")
        names = [r.name for r in self.cfg.repositories]
        self._show_list("Remove Repo - select", names, select_action=self._do_remove_repo)

    def _do_remove_repo(self, repo_name: str) -> None:
        """Remove a repository from the configuration.

        Args:
            repo_name: Repository in "owner/repo" format to remove.
        """
        self.cfg.repositories = [r for r in self.cfg.repositories if r.name != repo_name]
        # Purge cached PRs for this repo immediately
        with contextlib.suppress(Exception):
            storage.delete_prs_by_repo(repo_name)
        save_config(self.cfg)
        # Go back to the previous screen using navigation stack
        if self._navigation_stack:
            prev_screen = self._navigation_stack.pop()
            if prev_screen == "config_menu":
                self._show_config_menu()
            else:
                self._show_menu()
        else:
            self._show_menu()

    def _prompt_add_account(self) -> None:
        """Prompt to add an account globally or scoped to a repository."""
        # Push current screen to navigation stack
        self._navigation_stack.append("config_menu")
        self._prompt_two_fields("Add Account", "username", "repo (owner/repo or empty=global)", self._do_add_account)

    def _do_add_account(self, username: str, repo_name: str) -> None:
        """Add an account to global or per-repo tracked users.

        Args:
            username: GitHub username to add.
            repo_name: "owner/repo" to scope the username, or empty for global.
        """
        username = username.strip()
        repo_name = repo_name.strip()
        if not username:
            self._navigate_back_or_home()
            return
        if repo_name:
            for r in self.cfg.repositories:
                if r.name == repo_name:
                    users = set(r.users or [])
                    users.add(username)
                    r.users = sorted(users)
                    break
        else:
            users = set(self.cfg.global_users)
            users.add(username)
            self.cfg.global_users = sorted(users)
        save_config(self.cfg)
        self._navigate_back_or_home()

    def _prompt_remove_account_select(self) -> None:
        """Show a list of accounts (global and per-repo) to remove via selection."""
        # Push current screen to navigation stack
        self._navigation_stack.append("config_menu")
        items: list[str] = []
        # Global users
        for u in sorted(set(self.cfg.global_users)):
            items.append(f"global:{u}")
        # Per-repo users
        for r in self.cfg.repositories:
            for u in sorted(set(r.users or [])):
                items.append(f"{r.name}:{u}")
        if not items:
            self._show_menu()
            return
        self._show_list(
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
            self._navigate_back_or_home()
            return
        username = username.strip()
        if prefix == "global":
            self.cfg.global_users = [u for u in self.cfg.global_users if u != username]
            with contextlib.suppress(Exception):
                storage.delete_prs_by_account(username)
        else:
            repo_name = prefix
            for r in self.cfg.repositories:
                if r.name == repo_name and r.users:
                    r.users = [u for u in r.users if u != username] or None
            with contextlib.suppress(Exception):
                storage.delete_prs_by_account(username, repo_name)
        save_config(self.cfg)
        self._navigate_back_or_home()

    def _prompt_update_token(self) -> None:
        """Prompt to update the stored GitHub personal access token."""
        # Push current screen to navigation stack
        self._navigation_stack.append("config_menu")
        self._prompt_one_field("Update GitHub Token", "token", self._do_update_token)

    def _do_update_token(self, token: str) -> None:
        """Store a new GitHub token and refresh the client.

        Args:
            token: The new token value; empty string clears the token.
        """
        self.cfg.auth_token = token.strip() or None
        save_config(self.cfg)
        # refresh client headers
        self.client = GitHubClient(self.cfg.auth_token)
        # Go back to the previous screen using navigation stack
        if self._navigation_stack:
            prev_screen = self._navigation_stack.pop()
            if prev_screen == "config_menu":
                self._show_config_menu()
            elif self._navigation_stack:
                prev_screen = self._navigation_stack.pop()
                if prev_screen == "config_menu":
                    self._show_config_menu()
                else:
                    self._show_menu()
            else:
                self._show_menu()
        else:
            self._show_menu()

    def _show_current_config(self) -> None:
        """Display a transient view of the current configuration."""
        lines = ["Current Config:"]
        lines.append(f"Token: {'set' if self.cfg.auth_token else 'not set'}")
        users = ", ".join(self.cfg.global_users) if self.cfg.global_users else "(none)"
        lines.append(f"Global users: {users}")
        lines.append(f"Staleness threshold (s): {self.cfg.staleness_threshold_seconds}")
        lines.append(f"PRs per page: {getattr(self.cfg, 'pr_page_size', 10)}")
        for r in self.cfg.repositories:
            users = ", ".join(r.users) if r.users else "(inherit globals)"
            lines.append(f"Repo: {r.name} | users: {users}")
        static = Static("\n".join(lines))
        self.mount(static)

        def close_and_back():
            static.remove()
            # Go back to the previous screen using navigation stack
            if self._navigation_stack:
                prev_screen = self._navigation_stack.pop()
                if prev_screen == "config_menu":
                    self._show_config_menu()
                else:
                    self._show_menu()
            else:
                self._show_menu()

        self.set_timer(2.0, close_and_back)

    # ---------- Prompt helpers ----------

    def _prompt_one_field(self, title: str, placeholder: str, cb) -> None:
        """Create a one-field input prompt overlay.

        Args:
            title: Title displayed above the input.
            placeholder: Placeholder text for the input field.
            cb: Callback invoked with the input string upon confirmation.
        """
        # Remove existing prompt containers if any to ensure unique IDs
        self._remove_all_prompts()
        container = Vertical(Label(title), Input(placeholder=placeholder), Horizontal(Button("OK"), Button("Cancel")))
        container.id = "prompt_one"
        container.data_cb = cb  # type: ignore[attr-defined]
        self.mount(container)

    def _prompt_set_staleness_threshold(self) -> None:
        """Prompt for staleness threshold in seconds."""
        # Push current screen to navigation stack
        self._navigation_stack.append("config_menu")
        self._prompt_one_field(
            "Set staleness threshold (seconds)",
            str(self.cfg.staleness_threshold_seconds),
            self._do_set_staleness_threshold,
        )

    def _do_set_staleness_threshold(self, value: str) -> None:
        with contextlib.suppress(Exception):
            seconds = max(0, int(value.strip()))
            self.cfg.staleness_threshold_seconds = seconds
            self._stale_after_seconds = seconds
            save_config(self.cfg)
        # Go back to the previous screen using navigation stack
        if self._navigation_stack:
            prev_screen = self._navigation_stack.pop()
            if prev_screen == "config_menu":
                self._show_config_menu()
            else:
                self._show_menu()
        else:
            self._show_menu()

    def _prompt_set_pr_page_size(self) -> None:
        """Prompt for PRs per page size."""
        # Push current screen to navigation stack
        self._navigation_stack.append("config_menu")
        self._prompt_one_field(
            "Set PRs per page",
            str(getattr(self.cfg, "pr_page_size", 10)),
            self._do_set_pr_page_size,
        )

    def _do_set_pr_page_size(self, value: str) -> None:
        with contextlib.suppress(Exception):
            size = int(value.strip())
            if size <= 0:
                raise ValueError("page size must be > 0")
            self.cfg.pr_page_size = size  # type: ignore[attr-defined]
            self._page_size = size
            save_config(self.cfg)
        self._show_menu()

    def _prompt_set_settings_menu_page_size(self) -> None:
        """Prompt for Settings menu page size."""
        # Push current screen to navigation stack
        self._navigation_stack.append("config_menu")
        self._prompt_one_field(
            "Set Settings menu page size",
            str(getattr(self.cfg, "menu_page_size", 5)),
            self._do_set_settings_menu_page_size,
        )

    def _do_set_settings_menu_page_size(self, value: str) -> None:
        try:
            size = int(value.strip())
            if size <= 0:
                raise ValueError
            self.cfg.menu_page_size = size
            save_config(self.cfg)
            self._settings_page_index = 0
        except Exception:
            self._show_toast("Invalid number (> 0)")
        # Only add to navigation stack if it's not already there
        if not self._navigation_stack or self._navigation_stack[-1] != "config_menu":
            self._navigation_stack.append("config_menu")
        self._show_config_menu()

    def _prompt_two_fields(self, title: str, ph1: str, ph2: str, cb) -> None:
        """Create a two-field input prompt overlay.

        Args:
            title: Title displayed above the inputs.
            ph1: Placeholder for the first input field.
            ph2: Placeholder for the second input field.
            cb: Callback invoked with both input strings upon confirmation.
        """
        # Remove existing prompt containers if any to ensure unique IDs
        for pid in ("prompt_one", "prompt_two"):
            with contextlib.suppress(Exception):
                self.query_one(f"#{pid}").remove()
        container = Vertical(
            Label(title),
            Input(placeholder=ph1, id="f1"),
            Input(placeholder=ph2, id="f2"),
            Horizontal(Button("OK"), Button("Cancel")),
        )
        container.id = "prompt_two"
        container.data_cb = cb  # type: ignore[attr-defined]
        self.mount(container)

    def _remove_all_prompts(self) -> None:
        """Remove all prompt overlays (one and two-field) if present."""
        try:
            for pid in ("prompt_one", "prompt_two"):
                for node in list(self.query(f"#{pid}")):
                    with contextlib.suppress(Exception):
                        node.remove()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:  # Textual event handler
        """Handle OK/Cancel button presses for prompt overlays.

        Args:
            event: Button press event emitted by Textual.
        """
        label = event.button.label or ""
        container = event.button.parent and event.button.parent.parent  # Horizontal -> Vertical
        if not container:
            return
        if getattr(container, "id", None) not in {"prompt_one", "prompt_two"}:  # type: ignore[attr-defined]
            return
        cb = getattr(container, "data_cb", None)
        if not cb:
            return
        if container.id == "prompt_one":  # type: ignore[union-attr]
            self._handle_prompt_one(container, label, cb)
            return
        if container.id == "prompt_two":  # type: ignore[union-attr]
            self._handle_prompt_two(container, label, cb)
            return

    # ---------------- Small helpers extracted to reduce branching ----------------

    def _close_overlay_if_open(self) -> bool:
        """Close overlay if present and navigate back.

        Returns:
            True if an overlay was closed and navigation occurred; False otherwise.
        """
        if self._overlay_container is None:
            return False
        with contextlib.suppress(Exception):
            self._overlay_container.remove()
        self._overlay_container = None
        self._overlay_list = None
        self._overlay_select_action = None
        self._md_mode = False
        self._md_scope = None
        self._navigate_back_or_home()
        return True

    def _handle_markdown_back_if_needed(self) -> bool:
        """Handle back navigation when in markdown selection context.

        Returns:
            True if markdown-specific back handling occurred; False otherwise.
        """
        if not (self._md_mode and self._table.display):
            return False
        if self._navigation_stack and self._navigation_stack[-1] == "repo_selection":
            self._navigation_stack.pop()
            self._show_list(
                "Repos",
                [r.name for r in self.cfg.repositories],
                select_action=self._md_select_repo,
            )
            return True
        if self._navigation_stack and self._navigation_stack[-1] == "account_selection":
            self._navigation_stack.pop()
            accounts = sorted(set(self.cfg.global_users) | {u for r in self.cfg.repositories for u in (r.users or [])})
            self._show_list("Accounts", accounts, select_action=self._md_select_account)
            return True
        self._show_markdown_menu()
        return True

    def _navigate_back_or_home(self) -> None:
        """Navigate back using the stack or go home when stack is empty."""
        if self._navigation_stack:
            prev_screen = self._navigation_stack.pop()
            if prev_screen == "config_menu":
                self._show_config_menu()
            elif prev_screen == "main_menu":
                self._show_menu()
            elif prev_screen == "markdown_menu":
                self._show_markdown_menu()
            else:
                self._show_menu()
        else:
            self._show_menu()

    def _handle_overlay_selection_if_any(self, event: ListView.Selected) -> bool:
        """Handle overlay list selection if the event targets an overlay list.

        Args:
            event: The `ListView.Selected` event.

        Returns:
            True if handled; False otherwise.
        """
        if self._overlay_list is None or event.list_view is not self._overlay_list:
            return False
        item_id = getattr(event.item, "_value", event.item.id or "")
        if self._overlay_container:
            self._overlay_container.remove()
        cb = self._overlay_select_action
        self._overlay_container = None
        self._overlay_list = None
        self._overlay_select_action = None
        if cb:
            cb(item_id)
        else:
            self._show_menu()
        return True

    def _handle_main_menu_selection_if_any(self, event: ListView.Selected) -> None:
        """Handle selection on the main menu list if present."""
        if self._menu is None or event.list_view is not self._menu:
            return
        item_id = event.item.id or ""
        actions: dict[str, Callable[[], None]] = {
            "list_all_prs": self._show_cached_all,
            "list_repos": lambda: self._show_list(
                "Tracked Repos", [r.name for r in self.cfg.repositories], self._select_repo
            ),
            "list_accounts": lambda: self._show_list(
                "Tracked Accounts",
                sorted(set(self.cfg.global_users) | {u for r in self.cfg.repositories for u in (r.users or [])}),
                self._select_account,
            ),
            "prs_per_repo": lambda: self._show_list(
                "Repos", [r.name for r in self.cfg.repositories], self._load_repo_prs
            ),
            "prs_per_account": lambda: self._show_list(
                "Accounts",
                sorted(set(self.cfg.global_users) | {u for r in self.cfg.repositories for u in (r.users or [])}),
                self._load_account_prs,
            ),
            "save_markdown": self._show_markdown_menu,
            "config": lambda: self._show_config_menu(is_from_main_menu=True),
            "exit": self.exit,
        }
        actions.get(item_id, self._show_menu)()

    def _handle_custom_keymap(self, key: str, event) -> bool:
        """Handle custom key mappings for the table and pagination.

        Args:
            key: The key string from the event.
            event: The original Textual event (used to prevent default and stop).

        Returns:
            True if the event was handled; False to continue processing.
        """
        try:
            table_active = (
                self._table.display
                and self._overlay_container is None
                and not self._menu.display
                and self._table_has_focus()
            )
            if self._md_mode and table_active and key == self._keymap.get("mark_markdown"):
                self.action_toggle_markdown_pr()
                with contextlib.suppress(Exception):
                    event.prevent_default()
                event.stop()
                return True
            if (not self._md_mode) and table_active and key == self._keymap.get("open_pr"):
                pr = self._table.get_selected_pr()
                if pr:
                    webbrowser.open(pr.html_url)
                    with contextlib.suppress(Exception):
                        event.prevent_default()
                    event.stop()
                    return True
            if key == self._keymap.get("next_page"):
                self.action_next_page()
                with contextlib.suppress(Exception):
                    event.prevent_default()
                event.stop()
                return True
            if key == self._keymap.get("prev_page"):
                self.action_prev_page()
                with contextlib.suppress(Exception):
                    event.prevent_default()
                event.stop()
                return True
            if key == self._keymap.get("back"):
                self.action_go_back()
                with contextlib.suppress(Exception):
                    event.prevent_default()
                event.stop()
                return True
        except Exception:
            pass
        return False

    def _handle_list_wrap_key(self, key: str, event) -> None:
        """Wrap ListView selection for up/down keys at boundaries.

        Args:
            key: Key value from event.
            event: The original Textual event.
        """
        if key not in {"up", "down"}:
            return
        target = None
        if self._overlay_list is not None and self._overlay_list.display:
            target = self._overlay_list
        elif self._menu is not None and self._menu.display:
            target = self._menu
        if target is None:
            return
        try:
            count = len(target.children)
            if count == 0:
                return
            idx = getattr(target, "index", 0)
            wrapped = self._maybe_wrap_index(count, idx, key)
            if wrapped is None:
                return
            target.index = wrapped
            with contextlib.suppress(Exception):
                event.prevent_default()
            event.stop()
        except Exception:
            pass

    def _handle_prompt_one(self, container, label: str, cb: Callable[[str], None]) -> None:
        """Process a one-field prompt OK/Cancel action.

        Args:
            container: The prompt container Vertical node.
            label: Button label (OK/Cancel).
            cb: Callback to invoke with the entered value.
        """
        value = container.query_one(Input).value  # type: ignore[arg-type]
        container.remove()
        if label == "OK":
            cb(value)
        else:
            self._navigate_back_or_home()

    def _handle_prompt_two(self, container, label: str, cb: Callable[[str, str], None]) -> None:
        """Process a two-field prompt OK/Cancel action.

        Args:
            container: The prompt container Vertical node.
            label: Button label (OK/Cancel).
            cb: Callback to invoke with the two entered values.
        """
        v1 = container.query_one("#f1", Input).value  # type: ignore[arg-type]
        v2 = container.query_one("#f2", Input).value  # type: ignore[arg-type]
        container.remove()
        if label == "OK":
            cb(v1, v2)
        else:
            self._navigate_back_or_home()
