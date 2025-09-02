from __future__ import annotations

import contextlib
from collections.abc import Iterable

from textual.message import Message
from textual.widgets import DataTable, Label, Static

from ..github import PullRequest


class PRTable(Static):
    """Widget that renders a table of pull requests and emits open/refresh events."""

    class OpenRequested(Message):
        def __init__(self, pr: PullRequest) -> None:
            self.pr = pr
            super().__init__()

    class PRRefreshRequested(Message):
        def __init__(self, pr: PullRequest) -> None:
            self.pr = pr
            super().__init__()

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.table = DataTable(cursor_type="row")

    def compose(self):  # type: ignore[override]
        yield Label(self.title, id="table-title")
        yield self.table

    def on_mount(self) -> None:  # type: ignore[override]
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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:  # type: ignore[override]
        pr = event.row_key
        if isinstance(pr, PullRequest):
            self.post_message(self.OpenRequested(pr))

    def action_refresh_pr(self) -> None:
        # Get the currently selected row
        cursor_row = self.table.cursor_row
        if cursor_row < 0:
            return
        # Some Textual versions store the key separately; safer to fetch via API
        try:
            key = self.table.row_keys[cursor_row]
        except Exception:
            # Fallback: attempt to derive from first column
            try:
                key = self.table.get_row_at(cursor_row)[0]
            except Exception:
                key = None
        if isinstance(key, PullRequest):
            self.post_message(PRTable.PRRefreshRequested(key))
