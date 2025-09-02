from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from prtrack import storage
from prtrack.github import PullRequest


@pytest.fixture
def temp_storage_dir(monkeypatch):
    """Create a temporary directory for storage and set it as the storage path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "prtrack"
        monkeypatch.setattr(storage, "CONFIG_DIR", config_dir)
        monkeypatch.setattr(storage, "DB_PATH", config_dir / "cache.sqlite3")
        yield config_dir


def make_pr(
    repo: str, number: int, author: str = "testuser", assignees: list[str] | None = None
) -> PullRequest:
    """Create a test PullRequest object."""
    return PullRequest(
        repo=repo,
        number=number,
        title=f"Test PR {number}",
        author=author,
        assignees=assignees or [],
        branch="main",
        draft=False,
        approvals=0,
        html_url=f"https://github.com/{repo}/pull/{number}",
    )


def test_record_and_get_last_refresh(temp_storage_dir):
    """Test recording and retrieving last refresh timestamps."""
    # Test recording a timestamp
    scope = "test_scope"
    timestamp = 1234567890
    storage.record_last_refresh(scope, timestamp)

    # Test retrieving the timestamp
    retrieved = storage.get_last_refresh(scope)
    assert retrieved == timestamp

    # Test retrieving non-existent scope
    assert storage.get_last_refresh("nonexistent") is None

    # Test recording with current time (default)
    storage.record_last_refresh("current_time")
    retrieved = storage.get_last_refresh("current_time")
    assert retrieved is not None
    assert isinstance(retrieved, int)


def test_upsert_prs_and_get_cached_all_prs(temp_storage_dir):
    """Test inserting/updating PRs and retrieving all cached PRs."""
    # Create test PRs
    pr1 = make_pr("owner/repo1", 1, "author1", ["assignee1"])
    pr2 = make_pr("owner/repo2", 2, "author2", ["assignee2"])
    prs = [pr1, pr2]

    # Test upserting PRs
    storage.upsert_prs(prs)

    # Test retrieving all PRs
    cached_prs = storage.get_cached_all_prs()
    assert len(cached_prs) == 2

    # Check that PRs are correctly stored and retrieved
    cached_pr1 = next(pr for pr in cached_prs if pr.number == 1)
    cached_pr2 = next(pr for pr in cached_prs if pr.number == 2)

    assert cached_pr1.repo == "owner/repo1"
    assert cached_pr1.author == "author1"
    assert cached_pr1.assignees == ["assignee1"]
    assert cached_pr1.title == "Test PR 1"

    assert cached_pr2.repo == "owner/repo2"
    assert cached_pr2.author == "author2"
    assert cached_pr2.assignees == ["assignee2"]
    assert cached_pr2.title == "Test PR 2"


def test_upsert_prs_with_fetched_at(temp_storage_dir):
    """Test upserting PRs with a specific fetched_at timestamp."""
    pr = make_pr("owner/repo", 1)
    fetched_at = 9876543210

    storage.upsert_prs([pr], fetched_at=fetched_at)

    # Verify PR was stored (basic check since we don't directly access the timestamp)
    cached_prs = storage.get_cached_all_prs()
    assert len(cached_prs) == 1
    assert cached_prs[0].number == 1


def test_upsert_prs_empty_list(temp_storage_dir):
    """Test upserting an empty list of PRs."""
    # Should not raise an exception
    storage.upsert_prs([])

    # Should have no PRs
    cached_prs = storage.get_cached_all_prs()
    assert len(cached_prs) == 0


def test_get_cached_prs_by_repo(temp_storage_dir):
    """Test retrieving cached PRs for a specific repository."""
    # Create PRs for different repos
    pr1 = make_pr("owner/repo1", 1)
    pr2 = make_pr("owner/repo2", 2)
    pr3 = make_pr("owner/repo1", 3)  # Another PR for repo1

    storage.upsert_prs([pr1, pr2, pr3])

    # Test retrieving PRs for repo1
    repo1_prs = storage.get_cached_prs_by_repo("owner/repo1")
    assert len(repo1_prs) == 2
    numbers = {pr.number for pr in repo1_prs}
    assert numbers == {1, 3}

    # Test retrieving PRs for repo2
    repo2_prs = storage.get_cached_prs_by_repo("owner/repo2")
    assert len(repo2_prs) == 1
    assert repo2_prs[0].number == 2

    # Test retrieving PRs for non-existent repo
    empty_prs = storage.get_cached_prs_by_repo("nonexistent/repo")
    assert len(empty_prs) == 0


def test_get_cached_prs_by_account(temp_storage_dir):
    """Test retrieving cached PRs for a specific account."""
    # Create PRs with different authors and assignees
    pr1 = make_pr("owner/repo1", 1, "alice", [])
    pr2 = make_pr("owner/repo2", 2, "bob", ["alice"])
    pr3 = make_pr("owner/repo3", 3, "charlie", ["dave"])
    pr4 = make_pr("owner/repo4", 4, "alice", ["bob"])

    storage.upsert_prs([pr1, pr2, pr3, pr4])

    # Test retrieving PRs where alice is author or assignee
    alice_prs = storage.get_cached_prs_by_account("alice")
    assert len(alice_prs) == 3
    numbers = {pr.number for pr in alice_prs}
    assert numbers == {1, 2, 4}

    # Test retrieving PRs where bob is author or assignee
    bob_prs = storage.get_cached_prs_by_account("bob")
    assert len(bob_prs) == 2
    numbers = {pr.number for pr in bob_prs}
    assert numbers == {2, 4}

    # Test retrieving PRs for non-existent account
    empty_prs = storage.get_cached_prs_by_account("nonexistent")
    assert len(empty_prs) == 0


def test_delete_prs_by_repo(temp_storage_dir):
    """Test deleting PRs for a specific repository."""
    # Create PRs for different repos
    pr1 = make_pr("owner/repo1", 1)
    pr2 = make_pr("owner/repo2", 2)
    pr3 = make_pr("owner/repo1", 3)

    storage.upsert_prs([pr1, pr2, pr3])

    # Verify initial state
    assert len(storage.get_cached_all_prs()) == 3

    # Delete PRs for repo1
    storage.delete_prs_by_repo("owner/repo1")

    # Verify only repo2 PR remains
    remaining_prs = storage.get_cached_all_prs()
    assert len(remaining_prs) == 1
    assert remaining_prs[0].number == 2

    # Test deleting from already empty repo
    storage.delete_prs_by_repo("owner/repo1")  # Should not raise exception
    assert len(storage.get_cached_all_prs()) == 1


def test_delete_prs_by_account_without_repo(temp_storage_dir):
    """Test deleting PRs for an account across all repositories."""
    # Create PRs with different authors and assignees
    pr1 = make_pr("owner/repo1", 1, "alice", [])
    pr2 = make_pr("owner/repo2", 2, "bob", ["alice"])
    pr3 = make_pr("owner/repo3", 3, "charlie", ["dave"])
    pr4 = make_pr("owner/repo4", 4, "alice", ["bob"])

    storage.upsert_prs([pr1, pr2, pr3, pr4])

    # Verify initial state
    assert len(storage.get_cached_all_prs()) == 4

    # Delete PRs where alice is author or assignee
    storage.delete_prs_by_account("alice")

    # Verify only PRs where alice is not author or assignee remain
    remaining_prs = storage.get_cached_all_prs()
    assert len(remaining_prs) == 1
    assert remaining_prs[0].number == 3
    assert remaining_prs[0].author == "charlie"


def test_delete_prs_by_account_with_repo(temp_storage_dir):
    """Test deleting PRs for an account within a specific repository."""
    # Create PRs with different authors and assignees
    pr1 = make_pr("owner/repo1", 1, "alice", [])
    pr2 = make_pr("owner/repo1", 2, "bob", ["alice"])
    pr3 = make_pr("owner/repo2", 3, "alice", [])  # alice as author in different repo
    pr4 = make_pr("owner/repo1", 4, "charlie", ["bob"])

    storage.upsert_prs([pr1, pr2, pr3, pr4])

    # Verify initial state
    assert len(storage.get_cached_all_prs()) == 4

    # Delete PRs where alice is author or assignee, but only in repo1
    storage.delete_prs_by_account("alice", "owner/repo1")

    # Verify PRs in repo1 with alice removed, but alice's PR in repo2 remains
    remaining_prs = storage.get_cached_all_prs()
    assert len(remaining_prs) == 2
    numbers = {pr.number for pr in remaining_prs}
    assert numbers == {3, 4}  # PR3 (alice in repo2) and PR4 (charlie in repo1)

    # Verify that repo2 still has alice's PR
    repo2_prs = storage.get_cached_prs_by_repo("owner/repo2")
    assert len(repo2_prs) == 1
    assert repo2_prs[0].author == "alice"


def test_row_to_pr_with_assignees(temp_storage_dir):
    """Test the _row_to_pr function with assignees."""
    # Create a PR with assignees and store it
    pr = make_pr("owner/repo", 1, "author", ["assignee1", "assignee2"])
    storage.upsert_prs([pr])

    # Retrieve and verify
    cached_prs = storage.get_cached_all_prs()
    assert len(cached_prs) == 1
    cached_pr = cached_prs[0]

    assert cached_pr.assignees == ["assignee1", "assignee2"]


def test_row_to_pr_with_draft(temp_storage_dir):
    """Test the _row_to_pr function with draft status."""
    # Create a draft PR and store it
    pr = PullRequest(
        repo="owner/repo",
        number=1,
        title="Draft PR",
        author="author",
        assignees=[],
        branch="feature",
        draft=True,
        approvals=0,
        html_url="https://github.com/owner/repo/pull/1",
    )
    storage.upsert_prs([pr])

    # Retrieve and verify
    cached_prs = storage.get_cached_all_prs()
    assert len(cached_prs) == 1
    cached_pr = cached_prs[0]

    assert cached_pr.draft is True


def test_upsert_prs_update_existing(temp_storage_dir):
    """Test that upserting PRs updates existing records."""
    # Create and store initial PR
    pr = make_pr("owner/repo", 1, "author1", ["assignee1"])
    storage.upsert_prs([pr])

    # Verify initial state
    cached_prs = storage.get_cached_all_prs()
    assert len(cached_prs) == 1
    assert cached_prs[0].author == "author1"
    assert cached_prs[0].assignees == ["assignee1"]
    assert cached_prs[0].title == "Test PR 1"

    # Create updated PR with same repo/number but different data
    updated_pr = make_pr("owner/repo", 1, "author2", ["assignee2"])
    updated_pr.title = "Updated PR Title"
    storage.upsert_prs([updated_pr])

    # Verify update
    cached_prs = storage.get_cached_all_prs()
    assert len(cached_prs) == 1
    assert cached_prs[0].author == "author2"
    assert cached_prs[0].assignees == ["assignee2"]
    assert cached_prs[0].title == "Updated PR Title"


def test_get_cached_prs_ordering(temp_storage_dir):
    """Test that cached PRs are returned in the correct order (newest first by number)."""
    # Create PRs with different numbers
    pr1 = make_pr("owner/repo", 1)
    pr2 = make_pr("owner/repo", 5)
    pr3 = make_pr("owner/repo", 3)

    storage.upsert_prs([pr1, pr2, pr3])

    # Retrieve and verify ordering
    cached_prs = storage.get_cached_all_prs()
    assert len(cached_prs) == 3
    # Should be ordered by number descending
    numbers = [pr.number for pr in cached_prs]
    assert numbers == [5, 3, 1]


def test_delete_prs_by_account_error_handling(temp_storage_dir, monkeypatch):
    """Test error handling in delete_prs_by_account when JSON parsing fails."""
    # Create a PR with assignees
    pr = make_pr("owner/repo", 1, "author", ["assignee"])
    storage.upsert_prs([pr])

    # Mock json.loads to raise an exception
    def mock_json_loads(s):
        raise ValueError("Invalid JSON")

    original_loads = json.loads
    monkeypatch.setattr(json, "loads", mock_json_loads)

    # Should not raise an exception even with JSON parsing error
    storage.delete_prs_by_account("assignee")

    # Restore original json.loads to allow get_cached_all_prs to work
    monkeypatch.setattr(json, "loads", original_loads)

    # The PR should still exist since we couldn't parse the assignees
    assert len(storage.get_cached_all_prs()) == 1


def test_delete_prs_by_account_with_repo_error_handling(temp_storage_dir, monkeypatch):
    """Test error handling in delete_prs_by_account with repo parameter when JSON parsing fails."""
    # Create a PR with assignees
    pr = make_pr("owner/repo", 1, "author", ["assignee"])
    storage.upsert_prs([pr])

    # Mock json.loads to raise an exception
    def mock_json_loads(s):
        raise ValueError("Invalid JSON")

    original_loads = json.loads
    monkeypatch.setattr(json, "loads", mock_json_loads)

    # Should not raise an exception even with JSON parsing error
    storage.delete_prs_by_account("assignee", "owner/repo")

    # Restore original json.loads to allow get_cached_all_prs to work
    monkeypatch.setattr(json, "loads", original_loads)

    # The PR should still exist since we couldn't parse the assignees
    assert len(storage.get_cached_all_prs()) == 1
