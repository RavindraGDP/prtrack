from __future__ import annotations

from .tui import PRTrackApp


def main() -> None:
    """Entry point for the `prtrack` console script.

    Launches the Textual TUI application.

    Returns:
        None
    """
    PRTrackApp().run()
