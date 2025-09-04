from __future__ import annotations

import contextlib
import os

from .utils.markdown import write_prs_markdown


class MarkdownManager:
    """Manages markdown selection and export functionality for the PRTrack TUI."""

    def __init__(self, app) -> None:
        """Initialize with reference to the main app."""
        self.app = app

    def show_markdown_menu(self) -> None:
        actions = [
            ("md_by_repo", "Select PRs by Repo"),
            ("md_by_account", "Select PRs by Account"),
            ("md_review", f"Review Selection ({len(self.app._md_selected)})"),
            ("md_save", "Save Selected to Markdown"),
            ("back", "Back"),
        ]
        self.app._menu_manager.show_choice_menu("Save PRs to Markdown", actions)
        # Rewire overlay handler to markdown actions
        self.app._overlay_select_action = lambda key: self.handle_markdown_action(key)

    def handle_markdown_action(self, action: str) -> None:
        match action:
            case "md_by_repo":
                # Push current screen to navigation stack before showing repo list
                self.app._navigation_manager.push_screen("markdown_menu")
                self.app._menu_manager.show_list(
                    "Repos",
                    [r.name for r in self.app.cfg.repositories],
                    select_action=self.md_select_repo,
                )
            case "md_by_account":
                # Push current screen to navigation stack before showing account list
                self.app._navigation_manager.push_screen("markdown_menu")
                accounts = sorted(
                    set(self.app.cfg.global_users) | {u for r in self.app.cfg.repositories for u in (r.users or [])}
                )
                self.app._menu_manager.show_list(
                    "Accounts",
                    accounts,
                    select_action=self.md_select_account,
                )
            case "md_review":
                self.md_review_selection()
            case "md_save":
                self.prompt_save_markdown()
            case "back":
                self.app.action_go_back()
            case _:
                self.app._show_menu()

    def enter_md_mode(self, kind: str, value: str | None) -> None:
        self.app._md_mode = True
        self.app._md_scope = (kind, value)
        self.app._status_manager.update_markdown_status()

    def md_select_repo(self, repo_name: str) -> None:
        # Push the repo selection screen to navigation stack so backspace works correctly
        self.app._navigation_manager.push_screen("repo_selection")
        self.app._show_cached_repo(repo_name)
        self.enter_md_mode("repo", repo_name)

    def md_select_account(self, account: str) -> None:
        # Push the account selection screen to navigation stack so backspace works correctly
        self.app._navigation_manager.push_screen("account_selection")
        self.app._show_cached_account(account)
        self.enter_md_mode("account", account)

    def toggle_markdown_pr(self) -> None:
        # Only allow marking when in markdown mode AND table is active and focused
        if not (
            self.app._md_mode
            and self.app._table.display
            and self.app._overlay_container is None
            and self.app._table_has_focus()
        ):
            return
        pr = self.app._table.get_selected_pr()
        if not pr:
            return
        key = (pr.repo, pr.number)
        if key in self.app._md_selected:
            del self.app._md_selected[key]
            self.app._show_toast(f"Unmarked {pr.repo}#{pr.number}")
        else:
            self.app._md_selected[key] = pr
            self.app._show_toast(f"Marked {pr.repo}#{pr.number}")
        self.app._status_manager.update_markdown_status()

    def md_review_selection(self) -> None:
        items = [f"{repo}#{num} - {pr.title}" for (repo, num), pr in self.app._md_selected.items()]
        if not items:
            self.app._show_toast("No PRs selected")
            self.show_markdown_menu()
            return
        # Push current screen to navigation stack before showing review list
        self.app._navigation_manager.push_screen("markdown_menu")
        # Selecting an item will deselect it
        self.app._menu_manager.show_list("Review Selection - select to remove", items, select_action=self.md_deselect)

    def md_deselect(self, label: str) -> None:
        # label format: "owner/repo#num - title"
        try:
            left = label.split(" - ", 1)[0]
            repo, num_str = left.split("#", 1)
            key = (repo, int(num_str))
            if key in self.app._md_selected:
                del self.app._md_selected[key]
                self.app._show_toast(f"Removed {repo}#{num_str}")
        except Exception:
            pass
        self.show_markdown_menu()

    def prompt_save_markdown(self) -> None:
        if not self.app._md_selected:
            self.app._show_toast("No PRs selected")
            self.show_markdown_menu()
            return
        # Push current screen to navigation stack before showing prompt
        self.app._navigation_manager.push_screen("markdown_menu")
        default_path = os.path.join(os.getcwd(), "pr-track.md")
        # Reuse one-field prompt
        self.app._prompt_manager.prompt_one_field(
            "Output markdown path (empty = CWD/pr-track.md)", default_path, self.do_save_markdown
        )

    def do_save_markdown(self, path: str) -> None:
        outfile = path.strip() or os.path.join(os.getcwd(), "pr-track.md")
        # Create parent dirs if needed
        with contextlib.suppress(Exception):
            os.makedirs(os.path.dirname(outfile) or ".", exist_ok=True)
        try:
            count = len(self.app._md_selected)
            write_prs_markdown(self.app._md_selected.values(), outfile)
            self.app._show_toast(f"Saved {count} PR(s) to {outfile}")
        except Exception:
            self.app._show_toast("Failed to save markdown")
        # Exit md mode back to menu but keep selection for convenience
        self.app._md_mode = False
        self.app._md_scope = None
        # Check if we should return to markdown menu
        if self.app._navigation_manager.peek_screen() == "markdown_menu":
            # Remove the markdown_menu entry from stack and show markdown menu
            self.app._navigation_manager.pop_screen()
            self.show_markdown_menu()
        else:
            self.app._show_menu()
