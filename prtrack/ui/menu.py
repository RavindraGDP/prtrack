from __future__ import annotations

import contextlib
from collections.abc import Callable

from textual.containers import Vertical
from textual.widgets import Label, ListItem, ListView


class MenuManager:
    """Manages menu display and interaction for the PRTrack TUI."""

    def __init__(self, app) -> None:
        """Initialize with reference to the main app."""
        self.app = app

    def show_menu(self) -> None:
        """Display the main menu and hide the table."""
        self.app.screen_mode = "menu"
        self.app._menu.display = True
        self.app._table.display = False
        self.app._status.display = False
        self.app._menu.focus()
        # Clear navigation stack when going back to main menu
        self.app._navigation_stack.clear()

    def show_list(self, title: str, items: list[str], select_action=None) -> None:
        """Display a list overlay for selecting an item.

        Args:
            title: Title displayed above the list.
            items: Items to display (also used as their IDs).
            select_action: Callback invoked with the selected item ID.
        """
        self.app._menu.display = False
        self.app._table.display = False
        # Clear any stray prompts before mounting an overlay
        self.app._remove_all_prompts()
        # Replace existing overlay container if present (avoid stacking)
        if self.app._overlay_container is not None:
            with contextlib.suppress(Exception):
                self.app._overlay_container.remove()
            self.app._overlay_container = None
            self.app._overlay_list = None
            self.app._overlay_select_action = None
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
        self.app.mount(container)
        # Ensure keyboard focus is on the overlay list (not hidden widgets)
        self.app.set_focus(list_view)
        # Ensure a valid starting selection for keyboard navigation
        with contextlib.suppress(Exception):
            if list_view.children:
                list_view.index = 0
        # Store overlay context; selection will be handled in on_list_view_selected
        self.app._overlay_container = container
        self.app._overlay_list = list_view
        self.app._overlay_select_action = select_action

    def show_choice_menu(self, title: str, actions: list[tuple[str, str]]) -> None:
        """Show a simple menu of labeled actions.

        Args:
            title: Menu title.
            actions: List of (key, label) tuples used to build the list.
        """
        self.app._menu.display = False
        self.app._table.display = False
        # Build items without IDs; keep the action key on the item
        # Replace existing overlay container if present (avoid stacking)
        if self.app._overlay_container is not None:
            with contextlib.suppress(Exception):
                self.app._overlay_container.remove()
            self.app._overlay_container = None
            self.app._overlay_list = None
            self.app._overlay_select_action = None
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
        self.app.mount(container)
        # Ensure keyboard focus is on the overlay list
        self.app.set_focus(list_view)
        # Ensure a valid starting selection for keyboard navigation
        with contextlib.suppress(Exception):
            if list_view.children:
                list_view.index = 0
        # Use overlay selection context; selection handled in on_list_view_selected
        self.app._overlay_container = container
        self.app._overlay_list = list_view
        # Wrap to route to config action handler
        self.app._overlay_select_action = lambda key: self.app._handle_config_action(key)

    def handle_main_menu_selection_if_any(self, event: ListView.Selected) -> None:
        """Handle selection on the main menu list if present."""
        if self.app._menu is None or event.list_view is not self.app._menu:
            return
        item_id = event.item.id or ""
        actions: dict[str, Callable[[], None]] = {
            "list_all_prs": self.app._show_cached_all,
            "list_repos": lambda: self.show_list(
                "Tracked Repos", [r.name for r in self.app.cfg.repositories], self.app._select_repo
            ),
            "list_accounts": lambda: self.show_list(
                "Tracked Accounts",
                sorted(
                    set(self.app.cfg.global_users) | {u for r in self.app.cfg.repositories for u in (r.users or [])}
                ),
                self.app._select_account,
            ),
            "prs_per_repo": lambda: self.show_list(
                "Repos", [r.name for r in self.app.cfg.repositories], self.app._load_repo_prs
            ),
            "prs_per_account": lambda: self.show_list(
                "Accounts",
                sorted(
                    set(self.app.cfg.global_users) | {u for r in self.app.cfg.repositories for u in (r.users or [])}
                ),
                self.app._load_account_prs,
            ),
            "save_markdown": self.app._show_markdown_menu,
            "config": lambda: self.app._show_config_menu(is_from_main_menu=True),
            "exit": self.app.exit,
        }
        actions.get(item_id, self.show_menu)()
