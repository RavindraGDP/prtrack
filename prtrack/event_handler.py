from __future__ import annotations

import contextlib
import webbrowser
from collections.abc import Callable
from typing import TYPE_CHECKING

from textual.widgets import Button, ListView

from .ui import PRTable

if TYPE_CHECKING:
    from .tui import PRTrackApp

# Constants for prompt container child indices
PROMPT_LABEL_INDEX = 0
PROMPT_INPUT1_INDEX = 1
PROMPT_INPUT2_INDEX = 2


class EventHandler:
    """Handles events for the PRTrackApp."""

    def __init__(self, app: PRTrackApp) -> None:
        """Initialize with reference to the main app."""
        self.app = app

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle item selection from either the main menu or overlays.

        Args:
            event: The selection event emitted by `ListView`.
        """
        if self._handle_overlay_selection_if_any(event):
            return
        self._handle_main_menu_selection_if_any(event)

    def on_key(self, event) -> None:  # type: ignore[override]
        """Key handling: wrapping for lists and custom key mappings."""
        key = getattr(event, "key", None)
        if key is None:
            return
        if self._handle_custom_keymap(key, event):
            return
        self._handle_list_wrap_key(key, event)

    def on_pr_table_open_requested(self, message: PRTable.OpenRequested) -> None:
        """Open the selected PR in the default web browser.

        Args:
            message: Message carrying the `PullRequest` to open.
        """
        # In markdown selection mode, ignore open on Enter
        if self.app._md_mode:
            return
        webbrowser.open(message.pr.html_url)

    def on_pr_table_pr_refresh_requested(self, message: PRTable.PRRefreshRequested) -> None:
        """Refresh the selected PR.

        Args:
            message: Message carrying the `PullRequest` to refresh.
        """
        self.app._schedule_refresh_single_pr(message.pr)

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

    def _handle_overlay_selection_if_any(self, event: ListView.Selected) -> bool:
        """Handle overlay list selection if the event targets an overlay list.

        Args:
            event: The `ListView.Selected` event.

        Returns:
            True if handled; False otherwise.
        """
        if self.app._overlay_list is None or event.list_view is not self.app._overlay_list:
            return False
        item_id = getattr(event.item, "_value", event.item.id or "")
        if self.app._overlay_container:
            self.app._overlay_container.remove()
        cb = self.app._overlay_select_action
        self.app._overlay_container = None
        self.app._overlay_list = None
        self.app._overlay_select_action = None
        if cb:
            cb(item_id)
        else:
            self.app._show_menu()
        return True

    def _handle_main_menu_selection_if_any(self, event: ListView.Selected) -> None:
        """Handle selection on the main menu list if present."""
        if self.app._menu is None or event.list_view is not self.app._menu:
            return
        item_id = event.item.id or ""
        actions: dict[str, Callable[[], None]] = {
            "list_all_prs": self.app._show_cached_all,
            "list_repos": lambda: self.app._show_list(
                "Tracked Repos", [r.name for r in self.app.cfg.repositories], self.app._select_repo
            ),
            "list_accounts": lambda: self.app._show_list(
                "Tracked Accounts",
                sorted(
                    set(self.app.cfg.global_users) | {u for r in self.app.cfg.repositories for u in (r.users or [])}
                ),
                self.app._select_account,
            ),
            "prs_per_repo": lambda: self.app._show_list(
                "Repos", [r.name for r in self.app.cfg.repositories], self.app._load_repo_prs
            ),
            "prs_per_account": lambda: self.app._show_list(
                "Accounts",
                sorted(
                    set(self.app.cfg.global_users) | {u for r in self.app.cfg.repositories for u in (r.users or [])}
                ),
                self.app._load_account_prs,
            ),
            "save_markdown": self.app._markdown_manager.show_markdown_menu,
            "config": lambda: self.app._show_config_menu(is_from_main_menu=True),
            "exit": self.app.exit,
        }
        actions.get(item_id, self.app._show_menu)()

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
                self.app._table.display
                and self.app._overlay_container is None
                and not self.app._menu.display
                and self.app._table_has_focus()
            )
            if self.app._md_mode and table_active and key == self.app._keymap.get("mark_markdown"):
                self.app.action_toggle_markdown_pr()
                with contextlib.suppress(Exception):
                    event.prevent_default()
                event.stop()
                return True
            if (not self.app._md_mode) and table_active and key == self.app._keymap.get("open_pr"):
                pr = self.app._table.get_selected_pr()
                if pr:
                    webbrowser.open(pr.html_url)
                    with contextlib.suppress(Exception):
                        event.prevent_default()
                    event.stop()
                    return True
            if key == self.app._keymap.get("next_page"):
                self.app.action_next_page()
                with contextlib.suppress(Exception):
                    event.prevent_default()
                event.stop()
                return True
            if key == self.app._keymap.get("prev_page"):
                self.app.action_prev_page()
                with contextlib.suppress(Exception):
                    event.prevent_default()
                event.stop()
                return True
            if key == self.app._keymap.get("back"):
                self.app.action_go_back()
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
        if self.app._overlay_list is not None and self.app._overlay_list.display:
            target = self.app._overlay_list
        elif self.app._menu is not None and self.app._menu.display:
            target = self.app._menu
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

    def _handle_prompt_one(self, container, label: str, cb: Callable[[str], None]) -> None:
        """Process a one-field prompt OK/Cancel action.

        Args:
            container: The prompt container Vertical node.
            label: Button label (OK/Cancel).
            cb: Callback to invoke with the entered value.
        """
        # Get the input widget (first child after the label)
        input_widget = (
            container.children[PROMPT_INPUT1_INDEX] if len(container.children) > PROMPT_INPUT1_INDEX else None
        )
        if not input_widget:
            return

        value = getattr(input_widget, "value", "")
        if label == "OK":
            cb(value)
        # Remove the prompt regardless of button pressed
        container.remove()

    def _handle_prompt_two(self, container, label: str, cb: Callable[[str, str], None]) -> None:
        """Process a two-field prompt OK/Cancel action.

        Args:
            container: The prompt container Vertical node.
            label: Button label (OK/Cancel).
            cb: Callback to invoke with the two entered values.
        """
        # Get the input widgets (children 1 and 2 after the label)
        input1 = container.children[PROMPT_INPUT1_INDEX] if len(container.children) > PROMPT_INPUT1_INDEX else None
        input2 = container.children[PROMPT_INPUT2_INDEX] if len(container.children) > PROMPT_INPUT2_INDEX else None
        if not input1 or not input2:
            return

        value1 = getattr(input1, "value", "")
        value2 = getattr(input2, "value", "")
        if label == "OK":
            cb(value1, value2)
        # Remove the prompt regardless of button pressed
        container.remove()
