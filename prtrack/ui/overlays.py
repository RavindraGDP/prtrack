from __future__ import annotations

import contextlib


class OverlayManager:
    """Manages overlay display and interaction for the PRTrack TUI."""

    def __init__(self, app) -> None:
        """Initialize with reference to the main app."""
        self.app = app

    def close_overlay_if_open(self) -> bool:
        """Close overlay if present and navigate back.

        Returns:
            True if an overlay was closed and navigation occurred; False otherwise.
        """
        if self.app._overlay_container is None:
            return False
        with contextlib.suppress(Exception):
            self.app._overlay_container.remove()
        self.app._overlay_container = None
        self.app._overlay_list = None
        self.app._overlay_select_action = None
        self.app._md_mode = False
        self.app._md_scope = None
        self.app._navigate_back_or_home()
        return True

    def remove_all_prompts(self) -> None:
        """Remove all prompt overlays (one and two-field) if present."""
        try:
            for pid in ("prompt_one", "prompt_two"):
                for node in list(self.app.query(f"#{pid}")):
                    with contextlib.suppress(Exception):
                        node.remove()
        except Exception:
            pass
