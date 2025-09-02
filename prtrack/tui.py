from __future__ import annotations

import asyncio
import contextlib
import time
import webbrowser
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
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
from .github import GitHubClient, PullRequest, filter_prs


@dataclass
class MenuItem:
    key: str
    label: str


MAIN_MENU: list[MenuItem] = [
    MenuItem("list_all_prs", "List tracked PRs"),
    MenuItem("list_repos", "List tracked repos"),
    MenuItem("list_accounts", "List tracked accounts"),
    MenuItem("prs_per_repo", "List PRs per repo"),
    MenuItem("prs_per_account", "List PRs per account"),
    MenuItem("config", "Adjust config"),
    MenuItem("exit", "Exit"),
]


class PRTable(Static):
    """Widget that renders a table of pull requests and emits open events."""

    class OpenRequested(Message):
        def __init__(self, pr: PullRequest) -> None:
            """Message indicating that a PR should be opened in a browser.

            Args:
                pr: The `PullRequest` selected by the user.
            """
            self.pr = pr
            super().__init__()

    def __init__(self, title: str) -> None:
        """Initialize the table widget.

        Args:
            title: Title label displayed above the table.
        """
        super().__init__()
        self.title = title
        self.table = DataTable(cursor_type="row")

    def compose(self) -> ComposeResult:
        """Compose the child widgets for this component."""
        yield Label(self.title, id="table-title")
        yield self.table

    def on_mount(self) -> None:
        """Set up the table columns when the widget mounts.

        Uses a suppress block to tolerate minor version differences.
        """
        # Initialize columns once on first mount
        with contextlib.suppress(Exception):
            self.table.add_columns(
                "Repo",
                "#",
                "Title",
                "Author",
                "Assignees",
                "Branch",
                "Status",
                "Approvals",
            )

    def set_prs(self, prs: Iterable[PullRequest]) -> None:
        """Populate the table rows with pull request data.

        Args:
            prs: Iterable of `PullRequest` objects to render.
        """
        # Rebuild table to avoid version-specific clear semantics
        with contextlib.suppress(Exception):
            self.table.remove()
        self.table = DataTable(cursor_type="row")
        with contextlib.suppress(Exception):
            self.mount(self.table)
            self.table.add_columns(
                "Repo",
                "#",
                "Title",
                "Author",
                "Assignees",
                "Branch",
                "Status",
                "Approvals",
            )
        for pr in prs:
            try:
                self.table.add_row(
                    pr.repo,
                    str(pr.number),
                    pr.title,
                    pr.author,
                    ", ".join(pr.assignees),
                    pr.branch,
                    "Draft" if pr.draft else "Ready",
                    str(pr.approvals),
                    key=pr,
                )
            except Exception:
                # Fallback without key if API differs
                self.table.add_row(
                    pr.repo,
                    str(pr.number),
                    pr.title,
                    pr.author,
                    ", ".join(pr.assignees),
                    pr.branch,
                    "Draft" if pr.draft else "Ready",
                    str(pr.approvals),
                )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle selection and emit an `OpenRequested` message.

        Args:
            event: Selection event from the internal `DataTable`.
        """
        pr = event.row_key
        if isinstance(pr, PullRequest):
            self.post_message(self.OpenRequested(pr))


class PRTrackApp(App):
    """Textual TUI application for tracking GitHub pull requests."""

    CSS = """
    #table-title { padding: 1 0; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "go_home", "Home"),
        Binding("r", "refresh_current", "Refresh"),
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
        self._table = PRTable("Pull Requests")
        self._status = Label("", id="status")
        # Refresh state
        self._current_scope: tuple[str, str | None] = ("menu", None)  # (kind, value)
        self._stale_after_seconds: int = 300
        self._refresh_task: asyncio.Task | None = None
        # Overlay selection context (for repo/account lists, config lists, etc.)
        self._overlay_container: Vertical | None = None
        self._overlay_list: ListView | None = None
        self._overlay_select_action: Callable[[str], None] | None = None

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
        self._show_menu()

    def _show_menu(self) -> None:
        """Display the main menu and hide the table."""
        self.screen_mode = "menu"
        self._menu.display = True
        self._table.display = False
        self._status.display = False
        self._menu.focus()

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
        users = set(
            next((r.users or [] for r in self.cfg.repositories if r.name == repo_name), [])
        ) or set(self.cfg.global_users)
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
            ago = int(time.time()) - int(last)
            text = f"Last refresh: {ago}s ago"
        if refreshing:
            text += " • Refreshing…"
        self._status.update(text)
        self._status.display = True

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
        self._table.set_prs(all_prs)
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
        self._table.set_prs(cached)
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
        self._table.set_prs(cached)
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
            # Apply current filters (if any global/per-repo)
            self._table.set_prs(storage.get_cached_all_prs())
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
            self._table.set_prs(storage.get_cached_prs_by_repo(repo_name))
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
            self._table.set_prs(storage.get_cached_prs_by_account(account))
            self._update_status_label(scope, refreshing=False)

        self._refresh_task = asyncio.create_task(runner())

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle item selection from either the main menu or overlays.

        Args:
            event: The selection event emitted by `ListView`.
        """
        # If an overlay list is active and this event is for it, handle overlay selection
        if self._overlay_list is not None and event.list_view is self._overlay_list:
            item_id = getattr(event.item, "_value", event.item.id or "")
            if self._overlay_container:
                self._overlay_container.remove()
            cb = self._overlay_select_action
            # Clear overlay context
            self._overlay_container = None
            self._overlay_list = None
            self._overlay_select_action = None
            if cb:
                cb(item_id)
            else:
                self._show_menu()
            return

        # Otherwise, treat selection as from the main menu
        item_id = event.item.id or ""
        match item_id:
            case "list_all_prs":
                # Cache-first display then background refresh if stale
                self._show_cached_all()
            case "list_repos":
                self._show_list(
                    "Tracked Repos",
                    [r.name for r in self.cfg.repositories],
                    select_action=self._select_repo,
                )
            case "list_accounts":
                accounts = sorted(
                    set(self.cfg.global_users)
                    | {u for r in self.cfg.repositories for u in (r.users or [])}
                )
                self._show_list("Tracked Accounts", accounts, select_action=self._select_account)
            case "prs_per_repo":
                self._show_list(
                    "Repos",
                    [r.name for r in self.cfg.repositories],
                    select_action=self._load_repo_prs,
                )
            case "prs_per_account":
                accounts = sorted(
                    set(self.cfg.global_users)
                    | {u for r in self.cfg.repositories for u in (r.users or [])}
                )
                self._show_list("Accounts", accounts, select_action=self._load_account_prs)
            case "config":
                self._show_config_menu()
            case "exit":
                self.exit()

    def _show_list(
        self, title: str, items: list[str], select_action: Callable[[str], None] | None = None
    ) -> None:
        """Show a selectable overlay list.

        Args:
            title: Title displayed above the list.
            items: Items to display (also used as their IDs).
            select_action: Callback invoked with the selected item ID.
        """
        self._menu.display = False
        self._table.display = False
        # Build items without IDs (some values contain slashes or spaces). Store original value.
        li_items: list[ListItem] = []
        for it in items:
            li = ListItem(Label(it))
            li._value = it
            li_items.append(li)
        list_view = ListView(*li_items)
        list_view.can_focus = True
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
        webbrowser.open(message.pr.html_url)

    # ---------------- Config menu ----------------

    def _show_config_menu(self) -> None:
        """Display configuration actions menu as an overlay list."""
        actions = [
            ("add_repo", "Add repo"),
            ("remove_repo", "Remove repo"),
            ("add_account", "Add account"),
            ("remove_account", "Remove account"),
            ("update_token", "Update GitHub token"),
            ("show_config", "Show current config"),
            ("back", "Back"),
        ]
        self._show_choice_menu("Config", actions)

    def _show_choice_menu(self, title: str, actions: list[tuple[str, str]]) -> None:
        """Show a simple menu of labeled actions.

        Args:
            title: Menu title.
            actions: List of (key, label) tuples used to build the list.
        """
        self._menu.display = False
        self._table.display = False
        # Build items without IDs; keep the action key on the item
        li_actions: list[ListItem] = []
        for key, lbl in actions:
            li = ListItem(Label(lbl))
            li._value = key
            li_actions.append(li)
        list_view = ListView(*li_actions)
        list_view.can_focus = True
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

    def _handle_config_action(self, action: str) -> None:
        """Route a selected config action to its handler.

        Args:
            action: Action key from the config menu.
        """
        match action:
            case "add_repo":
                self._prompt_add_repo()
            case "remove_repo":
                self._prompt_remove_repo()
            case "add_account":
                self._prompt_add_account()
            case "remove_account":
                self._prompt_remove_account()
            case "update_token":
                self._prompt_update_token()
            case "show_config":
                self._show_current_config()
            case _:
                self._show_menu()

    def _prompt_add_repo(self) -> None:
        """Prompt the user to add a repository and optional users."""
        self._prompt_two_fields(
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
            self.cfg.repositories.append(RepoConfig(name=repo, users=users or None))
            save_config(self.cfg)
        self._show_menu()

    def _prompt_remove_repo(self) -> None:
        """Prompt for selecting a repository to remove from the config."""
        names = [r.name for r in self.cfg.repositories]
        self._show_list("Remove Repo - select", names, select_action=self._do_remove_repo)

    def _do_remove_repo(self, repo_name: str) -> None:
        """Remove a repository from the configuration.

        Args:
            repo_name: Repository in "owner/repo" format to remove.
        """
        self.cfg.repositories = [r for r in self.cfg.repositories if r.name != repo_name]
        save_config(self.cfg)
        self._show_menu()

    def _prompt_add_account(self) -> None:
        """Prompt to add an account globally or scoped to a repository."""
        self._prompt_two_fields(
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
            self._show_menu()
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
        self._show_menu()

    def _prompt_remove_account(self) -> None:
        """Prompt to remove an account from global or per-repo tracked users."""
        self._prompt_two_fields(
            "Remove Account",
            "username",
            "repo (owner/repo or empty=global)",
            self._do_remove_account,
        )

    def _do_remove_account(self, username: str, repo_name: str) -> None:
        """Remove an account from global or per-repo tracked users.

        Args:
            username: GitHub username to remove.
            repo_name: "owner/repo" to scope removal, or empty for global.
        """
        username = username.strip()
        repo_name = repo_name.strip()
        if repo_name:
            for r in self.cfg.repositories:
                if r.name == repo_name and r.users:
                    r.users = [u for u in r.users if u != username] or None
        else:
            self.cfg.global_users = [u for u in self.cfg.global_users if u != username]
        save_config(self.cfg)
        self._show_menu()

    def _prompt_update_token(self) -> None:
        """Prompt to update the stored GitHub personal access token."""
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
        self._show_menu()

    def _show_current_config(self) -> None:
        """Display a transient view of the current configuration."""
        lines = ["Current Config:"]
        lines.append(f"Token: {'set' if self.cfg.auth_token else 'not set'}")
        users = ", ".join(self.cfg.global_users) if self.cfg.global_users else "(none)"
        lines.append(f"Global users: {users}")
        for r in self.cfg.repositories:
            users = ", ".join(r.users) if r.users else "(inherit globals)"
            lines.append(f"Repo: {r.name} | users: {users}")
        static = Static("\n".join(lines))
        self.mount(static)

        def close_and_back():
            static.remove()
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
        container = Vertical(
            Label(title), Input(placeholder=placeholder), Horizontal(Button("OK"), Button("Cancel"))
        )
        container.id = "prompt_one"
        container.data_cb = cb  # type: ignore[attr-defined]
        self.mount(container)

    def _prompt_two_fields(self, title: str, ph1: str, ph2: str, cb) -> None:
        """Create a two-field input prompt overlay.

        Args:
            title: Title displayed above the inputs.
            ph1: Placeholder for the first input field.
            ph2: Placeholder for the second input field.
            cb: Callback invoked with both input strings upon confirmation.
        """
        container = Vertical(
            Label(title),
            Input(placeholder=ph1, id="f1"),
            Input(placeholder=ph2, id="f2"),
            Horizontal(Button("OK"), Button("Cancel")),
        )
        container.id = "prompt_two"
        container.data_cb = cb  # type: ignore[attr-defined]
        self.mount(container)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # Textual event handler
        """Handle OK/Cancel button presses for prompt overlays.

        Args:
            event: Button press event emitted by Textual.
        """
        # Handle OK/Cancel for prompt containers
        label = event.button.label or ""
        # Find the nearest ancestor Vertical used for prompts
        container = event.button.parent and event.button.parent.parent  # Horizontal -> Vertical
        if not container:
            return
        if getattr(container, "id", None) not in {"prompt_one", "prompt_two"}:  # type: ignore[attr-defined]
            return
        cb = getattr(container, "data_cb", None)
        if not cb:
            return
        if container.id == "prompt_one":  # type: ignore[union-attr]
            value = container.query_one(Input).value  # type: ignore[arg-type]
            container.remove()
            if label == "OK":
                cb(value)
            else:
                self._show_menu()
        elif container.id == "prompt_two":  # type: ignore[union-attr]
            v1 = container.query_one("#f1", Input).value  # type: ignore[arg-type]
            v2 = container.query_one("#f2", Input).value  # type: ignore[arg-type]
            container.remove()
            if label == "OK":
                cb(v1, v2)
            else:
                self._show_menu()
