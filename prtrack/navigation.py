from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # For type checking only, not used at runtime
    from .tui import PRTrackApp


class NavigationManager:
    """Manages navigation stack and back navigation functionality for PRTrackApp."""

    def __init__(self, app: PRTrackApp) -> None:
        """Initialize NavigationManager with reference to the main app.

        Args:
            app: The main PRTrackApp instance
        """
        self.app = app

    def push_screen(self, screen_name: str) -> None:
        """Push a screen to the navigation stack.

        Args:
            screen_name: Name of the screen to push
        """
        # Avoid duplicate consecutive entries
        if not self.app._navigation_stack or self.app._navigation_stack[-1] != screen_name:
            self.app._navigation_stack.append(screen_name)

    def pop_screen(self) -> str | None:
        """Pop a screen from the navigation stack.

        Returns:
            Name of the popped screen, or None if stack is empty
        """
        if self.app._navigation_stack:
            return self.app._navigation_stack.pop()
        return None

    def peek_screen(self) -> str | None:
        """Get the current screen without popping it.

        Returns:
            Name of the current screen, or None if stack is empty
        """
        if self.app._navigation_stack:
            return self.app._navigation_stack[-1]
        return None

    def clear_stack(self) -> None:
        """Clear the navigation stack."""
        self.app._navigation_stack.clear()

    def handle_markdown_back_if_needed(self) -> bool:
        """Handle back navigation when in markdown selection context.

        Returns:
            True if markdown-specific back handling occurred; False otherwise.
        """
        if not (self.app._md_mode and self.app._table.display):
            return False
        if self.app._navigation_stack and self.app._navigation_stack[-1] == "repo_selection":
            self.pop_screen()
            self.app._show_list(
                "Repos",
                [r.name for r in self.app.cfg.repositories],
                select_action=self.app._md_select_repo,
            )
            return True
        if self.app._navigation_stack and self.app._navigation_stack[-1] == "account_selection":
            self.pop_screen()
            accounts = sorted(
                set(self.app.cfg.global_users) | {u for r in self.app.cfg.repositories for u in (r.users or [])}
            )
            self.app._show_list("Accounts", accounts, select_action=self.app._md_select_account)
            return True
        self.app._show_markdown_menu()
        return True

    def navigate_back_or_home(self) -> None:
        """Navigate back using the stack or go home when stack is empty."""
        if self.app._navigation_stack:
            prev_screen = self.pop_screen()
            if prev_screen == "config_menu":
                self.app._show_config_menu()
            elif prev_screen == "main_menu":
                self.app._show_menu()
            elif prev_screen == "markdown_menu":
                self.app._show_markdown_menu()
            elif prev_screen == "repo_selection":
                # Go back to markdown menu when coming from repo selection
                self.app._show_markdown_menu()
            elif prev_screen == "account_selection":
                # Go back to markdown menu when coming from account selection
                self.app._show_markdown_menu()
            else:
                self.app._show_menu()
        else:
            self.app._show_menu()
