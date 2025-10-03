"""Test for the single PR refresh bug fix.

This test verifies that closed/merged PRs are properly removed from the cache
when using the single-PR refresh flow.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from prtrack import storage
from prtrack.github import PullRequest
from prtrack.tui import PRTrackApp


@pytest.mark.asyncio
async def test_single_pr_refresh_removes_closed_pr():
    """Test that single PR refresh removes closed PRs from cache."""
    # Create a mock app
    app = PRTrackApp()

    # Mock the GitHub client to simulate fetching a closed PR
    mock_client = Mock()
    mock_client._get = AsyncMock(
        return_value={
            "number": 123,
            "title": "Test PR",
            "user": {"login": "testuser"},
            "assignees": [],
            "head": {"ref": "test-branch"},
            "draft": False,
            "html_url": "https://github.com/testowner/testrepo/pull/123",
            "state": "closed",  # This PR is closed
        }
    )
    mock_client._count_approvals = AsyncMock(return_value=2)
    app.client = mock_client

    # Simulate a cached PR that exists in the database
    existing_pr = PullRequest(
        repo="testowner/testrepo",
        number=123,
        title="Test PR",
        author="testuser",
        assignees=[],
        branch="test-branch",
        draft=False,
        approvals=1,
        html_url="https://github.com/testowner/testrepo/pull/123",
        state="open",
    )

    # Add the existing PR to the cache
    storage.upsert_prs([existing_pr])

    # Verify the PR exists in cache
    cached_prs = storage.get_cached_prs_by_repo("testowner/testrepo")
    assert len(cached_prs) == 1
    assert cached_prs[0].number == 123
    assert cached_prs[0].state == "open"

    # Simulate the single PR refresh for this PR (should detect it's closed and remove it)
    result = await app._load_single_pr("testowner", "testrepo", 123)

    # The function should return None since the PR is closed
    assert result is None

    # Verify the PR was removed from cache
    cached_prs_after = storage.get_cached_prs_by_repo("testowner/testrepo")
    assert len(cached_prs_after) == 0


@pytest.mark.asyncio
async def test_single_pr_refresh_keeps_open_pr():
    """Test that single PR refresh keeps open PRs in cache."""
    # Create a mock app
    app = PRTrackApp()

    # Mock the GitHub client to simulate fetching an open PR
    mock_client = Mock()
    mock_client._get = AsyncMock(
        return_value={
            "number": 123,
            "title": "Test PR",
            "user": {"login": "testuser"},
            "assignees": [],
            "head": {"ref": "test-branch"},
            "draft": False,
            "html_url": "https://github.com/testowner/testrepo/pull/123",
            "state": "open",  # This PR is open
        }
    )
    mock_client._count_approvals = AsyncMock(return_value=2)
    app.client = mock_client

    # Simulate a cached PR that exists in the database
    existing_pr = PullRequest(
        repo="testowner/testrepo",
        number=123,
        title="Test PR",
        author="testuser",
        assignees=[],
        branch="test-branch",
        draft=False,
        approvals=1,
        html_url="https://github.com/testowner/testrepo/pull/123",
        state="open",
    )

    # Add the existing PR to the cache
    storage.upsert_prs([existing_pr])

    # Verify the PR exists in cache
    cached_prs = storage.get_cached_prs_by_repo("testowner/testrepo")
    assert len(cached_prs) == 1
    assert cached_prs[0].number == 123
    assert cached_prs[0].state == "open"

    # Simulate the single PR refresh for this PR (should keep it in cache)
    result = await app._load_single_pr("testowner", "testrepo", 123)

    # The function should return a PR object since it's still open
    assert result is not None
    assert result.number == 123
    assert result.state == "open"
    assert result.approvals == 2  # Should have updated approvals

    # Now simulate saving the result back to the cache like _schedule_refresh_single_pr does
    if result:
        storage.upsert_prs([result])

    # Verify the PR still exists in cache with updated info
    cached_prs_after = storage.get_cached_prs_by_repo("testowner/testrepo")
    assert len(cached_prs_after) == 1
    assert cached_prs_after[0].number == 123
    assert cached_prs_after[0].approvals == 2  # Should have updated approvals


@pytest.mark.asyncio
async def test_single_pr_refresh_handles_merged_pr():
    """Test that single PR refresh removes merged PRs from cache."""
    # Create a mock app
    app = PRTrackApp()

    # Mock the GitHub client to simulate fetching a merged PR
    mock_client = Mock()
    mock_client._get = AsyncMock(
        return_value={
            "number": 123,
            "title": "Test PR",
            "user": {"login": "testuser"},
            "assignees": [],
            "head": {"ref": "test-branch"},
            "draft": False,
            "html_url": "https://github.com/testowner/testrepo/pull/123",
            "state": "closed",  # Merged PRs have state "closed" but "merged" field is true
            "merged_at": "2023-01-01T00:00:00Z",  # This indicates it was merged
        }
    )
    mock_client._count_approvals = AsyncMock(return_value=2)
    app.client = mock_client

    # Simulate a cached PR that exists in the database
    existing_pr = PullRequest(
        repo="testowner/testrepo",
        number=123,
        title="Test PR",
        author="testuser",
        assignees=[],
        branch="test-branch",
        draft=False,
        approvals=1,
        html_url="https://github.com/testowner/testrepo/pull/123",
        state="open",
    )

    # Add the existing PR to the cache
    storage.upsert_prs([existing_pr])

    # Verify the PR exists in cache
    cached_prs = storage.get_cached_prs_by_repo("testowner/testrepo")
    assert len(cached_prs) == 1
    assert cached_prs[0].number == 123

    # Simulate the single PR refresh for this PR (should detect it's closed/merged and remove it)
    result = await app._load_single_pr("testowner", "testrepo", 123)

    # The function should return None since the PR is closed/merged
    assert result is None

    # Verify the PR was removed from cache
    cached_prs_after = storage.get_cached_prs_by_repo("testowner/testrepo")
    assert len(cached_prs_after) == 0
