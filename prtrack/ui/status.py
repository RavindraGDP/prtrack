from __future__ import annotations

import time

from .. import storage
from ..utils.time import format_time_ago


class StatusManager:
    """Manages status display for the PRTrack TUI."""

    def __init__(self, app) -> None:
        """Initialize with reference to the main app."""
        self.app = app

    def update_status_label(self, scope: str, refreshing: bool) -> None:
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
        total = len(self.app._current_prs)
        if total:
            pages = max(1, (total + self.app._page_size - 1) // self.app._page_size)
            text += f" • Page {self.app._page}/{pages} ({total} PRs)"
        self.app._status.update(text)
        self.app._status.display = True

    def update_markdown_status(self) -> None:
        scope = self.app._current_scope_key()
        count = len(self.app._md_selected)
        base = "Selecting for Markdown"
        mk = self.app._keymap.get("mark_markdown", "m")
        bk = self.app._keymap.get("back", "backspace")
        # Keep line length under 100 chars
        msg = f"{base} • Selected: {count} • Scope: {scope} • Keys: " f"mark='{mk}', back='{bk}', accept='enter'"
        self.app._status.update(msg)
        self.app._status.display = True
