from __future__ import annotations

from prtrack.github import PullRequest
from prtrack.tui import PRTrackApp

# Test constants
TEST_LIST_SIZE = 4
TEST_LAST_INDEX = 3
TEST_FIRST_INDEX = 0
TEST_MIDDLE_INDEX = 2
TEST_PAGE_NUMBER_2 = 2
TEST_PAGE_NUMBER_3 = 3


def make_pr(n: int) -> PullRequest:
    return PullRequest(
        repo="o/r",
        number=n,
        title=f"PR {n}",
        author="a",
        assignees=[],
        branch="b",
        draft=False,
        approvals=0,
        html_url="http://example.com",
    )


def test_maybe_wrap_index_helper() -> None:
    # no wrap in middle
    assert PRTrackApp._maybe_wrap_index(TEST_LIST_SIZE, 1, "down") is None
    assert PRTrackApp._maybe_wrap_index(TEST_LIST_SIZE, TEST_MIDDLE_INDEX, "up") is None
    # wrap at boundaries
    assert PRTrackApp._maybe_wrap_index(TEST_LIST_SIZE, TEST_FIRST_INDEX, "up") == TEST_LAST_INDEX
    assert PRTrackApp._maybe_wrap_index(TEST_LIST_SIZE, TEST_LAST_INDEX, "down") == TEST_FIRST_INDEX
    # empty list: no action
    assert PRTrackApp._maybe_wrap_index(0, 0, "down") is None


def test_pagination_next_prev_changes_page(monkeypatch) -> None:
    app = PRTrackApp()
    # Set page size to 2 and provide 5 PRs
    app._page_size = 2
    app._current_prs = [make_pr(i) for i in range(1, 6)]
    app._page = 1

    # Capture rows passed to table
    captured: list[list[PullRequest]] = []

    def fake_set_prs(prs):
        captured.append(list(prs))

    app._table.set_prs = fake_set_prs  # type: ignore[assignment]

    # Render first page: should contain 1..2
    app._render_current_page()
    assert [p.number for p in captured[-1]] == [1, 2]

    # Next page -> 3..4
    app.action_next_page()
    app._render_current_page()
    assert app._page == TEST_PAGE_NUMBER_2
    assert [p.number for p in captured[-1]] == [3, 4]

    # Next page -> last page (5)
    app.action_next_page()
    app._render_current_page()
    assert app._page == TEST_PAGE_NUMBER_3
    assert [p.number for p in captured[-1]] == [5]

    # Next page -> wrap to 1..2
    app.action_next_page()
    app._render_current_page()
    assert app._page == 1
    assert [p.number for p in captured[-1]] == [1, 2]

    # Prev page from page 1 -> wrap to page 3 (5)
    app.action_prev_page()
    app._render_current_page()
    assert app._page == TEST_PAGE_NUMBER_3
    assert [p.number for p in captured[-1]] == [5]
