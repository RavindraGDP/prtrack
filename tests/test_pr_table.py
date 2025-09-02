from __future__ import annotations

from textual.widgets import DataTable

from prtrack.github import PullRequest
from prtrack.ui.pr_table import PRTable


def make_pr(repo: str, number: int, **kwargs) -> PullRequest:
    """Create a test PullRequest object.

    Args:
        repo: Repository in "owner/repo" format.
        number: Pull request number.
        **kwargs: Optional fields to override on the `PullRequest`.

    Returns:
        A `PullRequest` instance populated with defaults and any overrides.
    """
    defaults = {
        "title": "Test PR",
        "author": "testuser",
        "assignees": [],
        "branch": "main",
        "draft": False,
        "approvals": 0,
        "html_url": f"https://github.com/{repo}/pull/{number}",
    }
    defaults.update(kwargs)
    return PullRequest(
        repo=repo,
        number=number,
        title=defaults["title"],
        author=defaults["author"],
        assignees=defaults["assignees"] or [],
        branch=defaults["branch"],
        draft=defaults["draft"],
        approvals=defaults["approvals"],
        html_url=defaults["html_url"],
    )


def test_pr_table_initialization():
    """Test PRTable initialization."""
    title = "Test Table"
    table = PRTable(title)

    assert table.title == title
    assert isinstance(table.table, DataTable)
    assert table.prs == []


def test_pr_table_compose():
    """Test PRTable compose method."""
    table = PRTable("Test Table")
    composed = list(table.compose())

    assert len(composed) == 2
    assert composed[0].id == "table-title"
    assert composed[0].content == "Test Table"
    assert composed[1] == table.table


def test_set_prs_adds_rows_and_stores():
    table = PRTable("PRs")
    table.on_mount()
    prs = [
        make_pr(
            "org/repo1", 1, title="One", assignees=["a1"], branch="feat/x", draft=False, approvals=2
        ),
        make_pr(
            "org/repo2",
            2,
            title="Two",
            assignees=["a2", "a3"],
            branch="bug/y",
            draft=True,
            approvals=0,
        ),
    ]
    table.set_prs(prs)

    # Stored
    assert table.prs == prs

    # Simulate selection using a lightweight stub (avoids Textual internals)
    class TableStub:
        def __init__(self):
            self.cursor_row = 0
            self.row_keys = [0, 1]

        def get_row_at(self, idx):
            pr = prs[idx]
            return [pr.repo, str(pr.number)]

    table.table = TableStub()
    sel = table.get_selected_pr()
    assert sel == prs[0]


def test_get_selected_pr_by_key():
    table = PRTable("PRs")
    table.on_mount()
    prs = [make_pr("org/repo", 10), make_pr("org/repo", 11)]
    table.set_prs(prs)

    # Simulate a selection where row_keys map to integer indices
    class TableStub:
        def __init__(self):
            self.cursor_row = 1
            self.row_keys = [0, 1]

        def get_row_at(self, idx):
            pr = prs[idx]
            return [pr.repo, str(pr.number)]

    table.table = TableStub()
    assert table.get_selected_pr() == prs[1]


def test_on_data_table_row_selected_posts_message_with_int(monkeypatch):
    table = PRTable("PRs")
    table.on_mount()
    prs = [make_pr("org/repo", 1), make_pr("org/repo", 2)]
    table.set_prs(prs)

    posted = []
    monkeypatch.setattr(table, "post_message", lambda msg: posted.append(msg))

    class E:
        row_key = 1

    table.on_data_table_row_selected(E())
    from prtrack.ui.pr_table import PRTable as _PRTable

    assert len(posted) == 1
    assert isinstance(posted[0], _PRTable.OpenRequested)
    assert posted[0].pr == prs[1]


def test_on_data_table_row_selected_rowkey_value_posts_message(monkeypatch):
    table = PRTable("PRs")
    table.on_mount()
    prs = [make_pr("org/repo", 3), make_pr("org/repo", 4)]
    table.set_prs(prs)

    posted = []
    monkeypatch.setattr(table, "post_message", lambda msg: posted.append(msg))

    class RowKeyProxy:
        def __init__(self, value):
            self.value = value

    class E:
        row_key = RowKeyProxy(0)

    table.on_data_table_row_selected(E())
    from prtrack.ui.pr_table import PRTable as _PRTable

    assert len(posted) == 1
    assert isinstance(posted[0], _PRTable.OpenRequested)
    assert posted[0].pr == prs[0]


def test_action_open_selected_pr_opens_browser(monkeypatch):
    table = PRTable("PRs")
    table.on_mount()
    prs = [make_pr("org/repo", 42)]
    table.set_prs(prs)

    # Simulate selection
    class TableStub:
        def __init__(self):
            self.cursor_row = 0
            self.row_keys = [0]

        def get_row_at(self, idx):
            pr = prs[idx]
            return [pr.repo, str(pr.number)]

    table.table = TableStub()

    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    table.action_open_selected_pr()
    assert opened == [prs[0].html_url]


def test_action_refresh_pr_with_pr_key_posts_message(monkeypatch):
    table = PRTable("PRs")
    table.on_mount()
    pr = make_pr("org/repo", 5)
    table.set_prs([pr])

    # Simulate selection and a key that is the PR itself
    class TableStub:
        def __init__(self):
            self.cursor_row = 0
            self.row_keys = [pr]

        def get_row_at(self, idx):
            return [pr.repo, str(pr.number)]

    table.table = TableStub()

    posted = []
    monkeypatch.setattr(table, "post_message", lambda msg: posted.append(msg))

    from prtrack.ui.pr_table import PRTable as _PRTable

    table.action_refresh_pr()
    assert any(isinstance(m, _PRTable.PRRefreshRequested) and m.pr == pr for m in posted)


def test_action_refresh_pr_with_int_key_noop(monkeypatch):
    table = PRTable("PRs")
    table.on_mount()
    pr = make_pr("org/repo", 6)
    table.set_prs([pr])

    # Simulate selection and an int key (the default path for set_prs)
    class TableStub:
        def __init__(self):
            self.cursor_row = 0
            self.row_keys = [0]

        def get_row_at(self, idx):
            return [pr.repo, str(pr.number)]

    table.table = TableStub()

    posted = []
    monkeypatch.setattr(table, "post_message", lambda msg: posted.append(msg))
    table.action_refresh_pr()
    assert posted == []
