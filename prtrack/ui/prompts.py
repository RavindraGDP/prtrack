from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING

from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label

if TYPE_CHECKING:  # For type checking only, not used at runtime
    from ..tui import PRTrackApp


class PromptManager:
    """Manages prompt display and interaction for the PRTrack TUI."""

    def __init__(self, app: PRTrackApp) -> None:
        """Initialize with reference to the main app."""
        self.app = app

    def prompt_one_field(self, title: str, placeholder: str, cb: Callable[[str], None]) -> None:
        """Create a one-field input prompt overlay.

        Args:
            title: Title displayed above the input.
            placeholder: Placeholder text for the input field.
            cb: Callback invoked with the input string upon confirmation.
        """
        # Remove existing prompt containers if any to ensure unique IDs
        self.app._remove_all_prompts()
        container = Vertical(Label(title), Input(placeholder=placeholder), Horizontal(Button("OK"), Button("Cancel")))
        container.id = "prompt_one"
        container.data_cb = cb  # type: ignore[attr-defined]
        self.app.mount(container)

    def prompt_two_fields(self, title: str, ph1: str, ph2: str, cb: Callable[[str, str], None]) -> None:
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
                self.app.query_one(f"#{pid}").remove()
        container = Vertical(
            Label(title),
            Input(placeholder=ph1, id="f1"),
            Input(placeholder=ph2, id="f2"),
            Horizontal(Button("OK"), Button("Cancel")),
        )
        container.id = "prompt_two"
        container.data_cb = cb  # type: ignore[attr-defined]
        self.app.mount(container)

    def handle_prompt_one(self, container: Vertical, label: str, cb: Callable[[str], None]) -> None:
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
            self.app._navigation_manager.navigate_back_or_home()

    def handle_prompt_two(self, container: Vertical, label: str, cb: Callable[[str, str], None]) -> None:
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
            self.app._navigation_manager.navigate_back_or_home()
