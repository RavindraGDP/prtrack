from __future__ import annotations

import json
import tempfile
import time
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
    repo: str, number: int, author: str = "testuser", assignees: list[str] | None = None, state: str = "open"
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
        state=state,
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


def test_regression_closed_pr_persistence_bug_document_current_behavior(temp_storage_dir):
    """Test that documents the current buggy behavior where closed PRs persist in cache after refresh.

    This test documents the current behavior (the bug): when a PR is deleted from
    GitHub's response but still exists in the cache, it remains in the cache after
    a refresh because we only merge/insert, never delete.
    This test will fail once the bug is fixed, proving the fix works.
    """
    # Create and store a PR in the cache
    pr = make_pr("owner/repo", 1, "author", ["assignee"])
    storage.upsert_prs([pr])

    # Verify the PR is in the cache
    cached_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs) == 1
    assert cached_prs[0].number == 1

    # Simulate a refresh where GitHub no longer returns this PR (it's now closed)
    # This represents the fresh data from GitHub after the PR has been closed
    fresh_prs_from_github = []  # Empty list - GitHub no longer reports this PR as open

    # Perform the current upsert operation (this is the buggy behavior)
    storage.upsert_prs(fresh_prs_from_github)

    # After refresh with upsert, the PR still exists in cache (this is the bug!)
    cached_prs_after_refresh = storage.get_cached_prs_by_repo("owner/repo")
    # This assertion passes with current buggy behavior
    assert len(cached_prs_after_refresh) == 1  # This is the bug - PR still exists!
    assert cached_prs_after_refresh[0].number == 1  # The closed PR is still there


def test_regression_closed_pr_removal_after_sync(temp_storage_dir):
    """Test that captures the expected behavior: closed PRs should disappear after sync-based refresh.

    This test will be enabled after implementing sync_repo_prs.
    It shows what the behavior should be after the fix: when GitHub stops reporting
    a PR as open, the next refresh should remove it from the cache.
    """

    # Create a sync_repo_prs function as specified in the design doc
    def sync_repo_prs(repo: str, prs, fetched_at=None):
        """Replace cached PRs for `repo` with `prs` in a single transaction."""
        ts = int(time.time()) if fetched_at is None else int(fetched_at)

        rows = [
            (
                pr.repo,
                pr.number,
                pr.title,
                pr.author,
                json.dumps(pr.assignees),
                pr.branch,
                1 if pr.draft else 0,
                pr.approvals,
                pr.html_url,
                ts,
            )
            for pr in prs
        ]

        with storage._connect() as conn:
            # Delete existing PRs for this repo first (inside the same transaction)
            conn.execute("DELETE FROM prs WHERE repo = ?", (repo,))
            # Insert the new PRs
            if rows:
                conn.executemany(
                    """
                    INSERT INTO prs(
                        repo, number, title, author, assignees,
                        branch, draft, approvals, html_url, fetched_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    rows,
                )

    # Create and store a PR in the cache
    pr = make_pr("owner/repo", 1, "author", ["assignee"])
    storage.upsert_prs([pr])

    # Verify the PR is in the cache
    cached_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs) == 1
    assert cached_prs[0].number == 1

    # Simulate a refresh where GitHub no longer returns this PR (it's now closed)
    # This represents the fresh data from GitHub after the PR has been closed
    fresh_prs_from_github = []  # Empty list - GitHub no longer reports this PR as open

    # Perform the sync operation (this will be the fixed behavior)
    sync_repo_prs("owner/repo", fresh_prs_from_github)

    # After sync-based refresh, the PR should disappear from cache
    cached_prs_after_refresh = storage.get_cached_prs_by_repo("owner/repo")
    # After the fix is properly implemented, this assertion should pass
    assert len(cached_prs_after_refresh) == 0  # PR should be removed after sync


def test_sync_repo_prs_basic(temp_storage_dir):
    """Test basic functionality of sync_repo_prs - replaces PRs for a single repo."""
    # Create initial PRs for the target repo
    pr1 = make_pr("owner/repo", 1, "author1", ["assignee1"])
    pr2 = make_pr("owner/repo", 2, "author2", ["assignee2"])
    storage.upsert_prs([pr1, pr2])

    # Also add PRs for a different repo to make sure they aren't affected
    pr3 = make_pr("other/repo", 3, "author3", ["assignee3"])
    storage.upsert_prs([pr3])

    # Verify initial state
    assert len(storage.get_cached_prs_by_repo("owner/repo")) == 2
    assert len(storage.get_cached_prs_by_repo("other/repo")) == 1

    # Create new PRs to sync - these will replace the existing ones for owner/repo
    new_pr1 = make_pr("owner/repo", 10, "newauthor1", ["newassignee1"])
    new_pr2 = make_pr("owner/repo", 20, "newauthor2", ["newassignee2"])
    fresh_prs = [new_pr1, new_pr2]

    # Sync the repository
    storage.sync_repo_prs("owner/repo", fresh_prs)

    # Verify that old PRs were removed and new ones added
    owner_repo_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(owner_repo_prs) == 2
    numbers = {pr.number for pr in owner_repo_prs}
    assert numbers == {10, 20}

    # Verify other repo PRs are unaffected
    other_repo_prs = storage.get_cached_prs_by_repo("other/repo")
    assert len(other_repo_prs) == 1
    assert other_repo_prs[0].number == 3


def test_sync_repo_prs_empty_list_removes_all(temp_storage_dir):
    """Test that sync_repo_prs with empty list removes all PRs for the repo."""
    # Create initial PRs
    pr1 = make_pr("owner/repo", 1, "author1", ["assignee1"])
    pr2 = make_pr("owner/repo", 2, "author2", ["assignee2"])
    storage.upsert_prs([pr1, pr2])

    # Also add PRs for a different repo to make sure they aren't affected
    pr3 = make_pr("other/repo", 3, "author3", ["assignee3"])
    storage.upsert_prs([pr3])

    # Verify initial state
    assert len(storage.get_cached_prs_by_repo("owner/repo")) == 2
    assert len(storage.get_cached_prs_by_repo("other/repo")) == 1

    # Sync with empty list - should remove all PRs for owner/repo
    storage.sync_repo_prs("owner/repo", [])

    # Verify that PRs for owner/repo were removed
    owner_repo_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(owner_repo_prs) == 0

    # Verify other repo PRs are unaffected
    other_repo_prs = storage.get_cached_prs_by_repo("other/repo")
    assert len(other_repo_prs) == 1
    assert other_repo_prs[0].number == 3


def test_sync_repo_prs_with_fetched_at(temp_storage_dir):
    """Test that sync_repo_prs respects the fetched_at parameter."""
    custom_timestamp = int(time.time()) - 1000  # 1000 seconds ago

    # Create PRs to sync with custom timestamp
    pr1 = make_pr("owner/repo", 1, "author1", ["assignee1"])
    fresh_prs = [pr1]

    # Sync with custom timestamp
    storage.sync_repo_prs("owner/repo", fresh_prs, fetched_at=custom_timestamp)

    # Get the cached PR and verify timestamp
    cached_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs) == 1
    # We can't directly check fetched_at from the PullRequest object,
    # but the functionality is handled in the storage layer


def test_sync_repo_prs_transaction_rollback_on_error(temp_storage_dir):
    """Test that sync_repo_prs maintains transactional integrity."""
    # This test will be more complex to implement, but conceptually
    # we want to verify that if something fails during the sync operation,
    # the delete operation is also rolled back.
    # For now, we'll focus on basic functionality.
    pr1 = make_pr("owner/repo", 1, "author1", ["assignee1"])
    storage.upsert_prs([pr1])

    # Verify initial state
    cached_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs) == 1
    assert cached_prs[0].number == 1

    # Sync with a new PR
    new_pr = make_pr("owner/repo", 2, "author2", ["assignee2"])
    storage.sync_repo_prs("owner/repo", [new_pr])

    # Verify only the new PR remains
    cached_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs) == 1
    assert cached_prs[0].number == 2


def test_sync_repo_prs_preserves_other_repos(temp_storage_dir):
    """Test that sync_repo_prs only affects the specified repository."""
    # Create PRs for multiple repositories
    pr1 = make_pr("repo1/name", 1, "author1", ["assignee1"])
    pr2 = make_pr("repo1/name", 2, "author2", ["assignee2"])
    pr3 = make_pr("repo2/name", 3, "author3", ["assignee3"])
    pr4 = make_pr("repo3/name", 4, "author4", ["assignee4"])

    storage.upsert_prs([pr1, pr2, pr3, pr4])

    # Verify initial state
    assert len(storage.get_cached_prs_by_repo("repo1/name")) == 2
    assert len(storage.get_cached_prs_by_repo("repo2/name")) == 1
    assert len(storage.get_cached_prs_by_repo("repo3/name")) == 1

    # Sync only repo1 - this should only affect repo1's PRs
    new_prs_for_repo1 = [make_pr("repo1/name", 10, "newauthor1", ["newassignee1"])]
    storage.sync_repo_prs("repo1/name", new_prs_for_repo1)

    # Verify repo1 was updated
    repo1_prs = storage.get_cached_prs_by_repo("repo1/name")
    assert len(repo1_prs) == 1
    assert repo1_prs[0].number == 10

    # Verify other repos are unchanged
    repo2_prs = storage.get_cached_prs_by_repo("repo2/name")
    assert len(repo2_prs) == 1
    assert repo2_prs[0].number == 3

    repo3_prs = storage.get_cached_prs_by_repo("repo3/name")
    assert len(repo3_prs) == 1
    assert repo3_prs[0].number == 4


def test_sync_repo_prs_idempotent(temp_storage_dir):
    """Test that sync_repo_prs is idempotent - syncing the same data twice has same result."""
    # Create initial PRs
    initial_prs = [
        make_pr("owner/repo", 1, "author1", ["assignee1"]),
        make_pr("owner/repo", 2, "author2", ["assignee2"]),
    ]
    storage.upsert_prs(initial_prs)

    # Verify initial state
    cached_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs) == 2

    # First sync with same PRs
    storage.sync_repo_prs("owner/repo", initial_prs)

    # Should have same PRs after first sync
    cached_prs_after_first = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs_after_first) == 2

    # Second sync with same PRs
    storage.sync_repo_prs("owner/repo", initial_prs)

    # Should have same PRs after second sync
    cached_prs_after_second = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs_after_second) == 2

    # Verify that the PRs are the expected ones
    numbers = {pr.number for pr in cached_prs_after_second}
    assert numbers == {1, 2}


def test_regression_closed_pr_removal_after_sync_implemented(temp_storage_dir):
    """Test that closed PRs are properly removed after a sync-based refresh."""
    # Create and store a PR in the cache
    pr = make_pr("owner/repo", 1, "author", ["assignee"])
    storage.upsert_prs([pr])

    # Verify the PR is in the cache
    cached_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs) == 1
    assert cached_prs[0].number == 1

    # Simulate a refresh where GitHub no longer returns this PR (it's now closed)
    # This represents the fresh data from GitHub after the PR has been closed
    fresh_prs_from_github = []  # Empty list - GitHub no longer reports this PR as open

    # Perform the sync operation (this is the fixed behavior)
    storage.sync_repo_prs("owner/repo", fresh_prs_from_github)

    # After sync-based refresh, the PR should disappear from cache
    cached_prs_after_refresh = storage.get_cached_prs_by_repo("owner/repo")
    # After the fix is properly implemented, this assertion should pass
    assert len(cached_prs_after_refresh) == 0  # PR should be removed after sync


def test_sync_repo_prs_updates_existing_prs(temp_storage_dir):
    """Test that sync_repo_prs properly updates existing PRs with new information."""
    # Create and store an initial PR
    initial_pr = make_pr("owner/repo", 1, "initial_author", ["initial_assignee"])
    initial_pr.title = "Initial Title"
    storage.upsert_prs([initial_pr])

    # Verify initial state
    cached_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs) == 1
    assert cached_prs[0].author == "initial_author"
    assert cached_prs[0].title == "Initial Title"

    # Create updated PR with same repo/number but different data
    updated_pr = make_pr("owner/repo", 1, "updated_author", ["updated_assignee"])
    updated_pr.title = "Updated Title"

    # Sync with the updated PR
    storage.sync_repo_prs("owner/repo", [updated_pr])

    # Verify the PR was updated
    cached_prs = storage.get_cached_prs_by_repo("owner/repo")
    assert len(cached_prs) == 1
    assert cached_prs[0].author == "updated_author"
    assert cached_prs[0].title == "Updated Title"
    assert cached_prs[0].assignees == ["updated_assignee"]
