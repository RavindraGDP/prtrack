from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterable

from .config import CONFIG_DIR
from .github import PullRequest

# Database path inside the app config directory
DB_PATH = CONFIG_DIR / "cache.sqlite3"

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS prs (
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    assignees TEXT NOT NULL, -- JSON array
    branch TEXT NOT NULL,
    draft INTEGER NOT NULL,
    approvals INTEGER NOT NULL,
    html_url TEXT NOT NULL,
    fetched_at INTEGER NOT NULL, -- unix epoch seconds
    PRIMARY KEY (repo, number)
);
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class StorageManager:
    """Manages background refresh operations and cache optimization."""

    def __init__(self) -> None:
        self._refresh_queue: dict[str, asyncio.Task] = {}
        self._refresh_callbacks: dict[str, list[Callable]] = {}

    def schedule_refresh(self, scope: str, refresh_func: Callable, callback: Callable | None = None) -> asyncio.Task:
        """Schedule a background refresh for a specific scope.

        Args:
            scope: The scope to refresh (e.g., "all", "repo:owner/repo")
            refresh_func: Async function to perform the refresh
            callback: Optional callback to execute after refresh completes

        Returns:
            The asyncio Task handling the refresh
        """
        # Cancel existing refresh for this scope if present
        if scope in self._refresh_queue:
            self._refresh_queue[scope].cancel()

        # Add callback if provided
        if callback:
            if scope not in self._refresh_callbacks:
                self._refresh_callbacks[scope] = []
            self._refresh_callbacks[scope].append(callback)

        # Create and schedule the refresh task
        async def _refresh_wrapper() -> None:
            try:
                await refresh_func()
                # Execute callbacks if any
                if scope in self._refresh_callbacks:
                    for cb in self._refresh_callbacks[scope]:
                        with contextlib.suppress(Exception):
                            cb()
                    # Clear callbacks after execution
                    del self._refresh_callbacks[scope]
            except Exception:
                pass  # Silently ignore refresh errors
            finally:
                # Remove from queue when done
                if scope in self._refresh_queue:
                    del self._refresh_queue[scope]

        task = asyncio.create_task(_refresh_wrapper())
        self._refresh_queue[scope] = task
        return task

    def is_refreshing(self, scope: str) -> bool:
        """Check if a scope is currently being refreshed.

        Args:
            scope: The scope to check

        Returns:
            True if the scope is being refreshed, False otherwise
        """
        return scope in self._refresh_queue and not self._refresh_queue[scope].done()

    def cancel_refresh(self, scope: str) -> bool:
        """Cancel a scheduled refresh for a scope.

        Args:
            scope: The scope to cancel refresh for

        Returns:
            True if a refresh was cancelled, False if none was scheduled
        """
        if scope in self._refresh_queue:
            self._refresh_queue[scope].cancel()
            del self._refresh_queue[scope]
            return True
        return False


def _connect() -> sqlite3.Connection:
    """Open a connection to the cache database, creating it if needed.

    Returns:
        A sqlite3 connection with row factory set to `sqlite3.Row`.
    """
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def record_last_refresh(scope: str, ts: int | None = None) -> None:
    """Record last refresh timestamp for a scope.

    Args:
        scope: A key representing the refresh scope, e.g. "all", "repo:owner/repo",
            or "account:username".
        ts: Unix epoch seconds. If None, current time is used.
    """
    if ts is None:
        ts = int(time.time())
    with _connect() as conn:
        conn.execute("REPLACE INTO metadata(key, value) VALUES (?, ?)", (f"last_refresh:{scope}", str(ts)))


def get_last_refresh(scope: str) -> int | None:
    """Get last refresh timestamp for a scope.

    Args:
        scope: Scope key used in `record_last_refresh`.

    Returns:
        Epoch seconds if recorded, otherwise None.
    """
    with _connect() as conn:
        cur = conn.execute("SELECT value FROM metadata WHERE key = ?", (f"last_refresh:{scope}",))
        row = cur.fetchone()
        return int(row[0]) if row else None


def upsert_prs(prs: Iterable[PullRequest], fetched_at: int | None = None) -> None:
    """Insert or update PRs in the cache.

    Args:
        prs: Iterable of `PullRequest` objects to upsert.
        fetched_at: A single timestamp to apply to all PRs. If None, now() is used.
    """
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
    if not rows:
        return
    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO prs(
                repo, number, title, author, assignees,
                branch, draft, approvals, html_url, fetched_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(repo, number) DO UPDATE SET
              title=excluded.title,
              author=excluded.author,
              assignees=excluded.assignees,
              branch=excluded.branch,
              draft=excluded.draft,
              approvals=excluded.approvals,
              html_url=excluded.html_url,
              fetched_at=excluded.fetched_at
            """,
            rows,
        )


def get_cached_all_prs() -> list[PullRequest]:
    """Return all cached PRs across repositories, newest first by number."""
    with _connect() as conn:
        cur = conn.execute("SELECT * FROM prs ORDER BY number DESC")
        return [_row_to_pr(r) for r in cur.fetchall()]


def get_cached_prs_by_repo(repo_name: str) -> list[PullRequest]:
    """Return cached PRs for a single repository.

    Args:
        repo_name: "owner/repo" identifier.
    """
    with _connect() as conn:
        cur = conn.execute("SELECT * FROM prs WHERE repo = ? ORDER BY number DESC", (repo_name,))
        return [_row_to_pr(r) for r in cur.fetchall()]


def get_cached_prs_by_account(account: str) -> list[PullRequest]:
    """Return cached PRs where author or assignees include the account."""
    with _connect() as conn:
        # Use SQL queries for better performance instead of filtering in Python
        # We need to check both author and assignees (JSON array)
        cur = conn.execute(
            """
            SELECT * FROM prs
            WHERE author = ? OR assignees LIKE ?
            ORDER BY number DESC
        """,
            (account, f'%"{account}"%'),
        )
        return [_row_to_pr(r) for r in cur.fetchall()]


def delete_prs_by_repo(repo_name: str) -> None:
    """Delete all cached PRs belonging to a repository.

    Args:
        repo_name: "owner/repo" identifier to remove from cache.
    """
    with _connect() as conn:
        conn.execute("DELETE FROM prs WHERE repo = ?", (repo_name,))


def delete_prs_by_account(account: str, repo_name: str | None = None) -> None:
    """Delete cached PRs authored by or assigned to an account.

    Args:
        account: GitHub username to purge from cache.
        repo_name: Optional "owner/repo" to limit the deletion to a repository.
    """
    with _connect() as conn:
        if repo_name:
            # Delete rows where author==account and repo matches
            query = "DELETE FROM prs WHERE repo = ? AND author = ?"
            conn.execute(query, (repo_name, account))
            # For assignee membership, filter in Python due to JSON storage
            query = "SELECT repo, number, assignees FROM prs WHERE repo = ?"
            cur = conn.execute(query, (repo_name,))
            rows = cur.fetchall()
            for r in rows:
                try:
                    assignees = list(json.loads(r["assignees"]) or [])
                except Exception:
                    assignees = []
                if account in assignees:
                    query = "DELETE FROM prs WHERE repo = ? AND number = ?"
                    conn.execute(query, (r["repo"], r["number"]))
        else:
            query = "DELETE FROM prs WHERE author = ?"
            conn.execute(query, (account,))
            query = "SELECT repo, number, assignees FROM prs"
            cur = conn.execute(query)
            rows = cur.fetchall()
            for r in rows:
                try:
                    assignees = list(json.loads(r["assignees"]) or [])
                except Exception:
                    assignees = []
                if account in assignees:
                    query = "DELETE FROM prs WHERE repo = ? AND number = ?"
                    conn.execute(query, (r["repo"], r["number"]))


def _row_to_pr(row: sqlite3.Row) -> PullRequest:
    return PullRequest(
        repo=row["repo"],
        number=int(row["number"]),
        title=row["title"],
        author=row["author"],
        assignees=list(json.loads(row["assignees"]) or []),
        branch=row["branch"],
        draft=bool(row["draft"]),
        approvals=int(row["approvals"]),
        html_url=row["html_url"],
    )


def batch_upsert_prs(prs: Iterable[PullRequest], fetched_at: int | None = None) -> None:
    """Batch insert or update PRs in the cache for better performance.

    Args:
        prs: Iterable of `PullRequest` objects to upsert.
        fetched_at: A single timestamp to apply to all PRs. If None, now() is used.
    """
    upsert_prs(prs, fetched_at)  # For now, just use the existing method


def cleanup_old_cache(max_age_days: int = 30) -> None:
    """Remove cached PRs older than max_age_days.

    Args:
        max_age_days: Maximum age of cached PRs in days. PRs older than this will be removed.
    """
    cutoff_time = int(time.time()) - (max_age_days * 24 * 60 * 60)
    with _connect() as conn:
        conn.execute("DELETE FROM prs WHERE fetched_at < ?", (cutoff_time,))
        conn.execute("DELETE FROM metadata WHERE key LIKE 'last_refresh:%' AND value < ?", (cutoff_time,))


def get_cache_stats() -> dict[str, int]:
    """Get statistics about the cache.

    Returns:
        Dictionary with cache statistics.
    """
    with _connect() as conn:
        # Get total number of PRs
        cur = conn.execute("SELECT COUNT(*) as count FROM prs")
        total_prs = cur.fetchone()["count"]

        # Get number of repositories
        cur = conn.execute("SELECT COUNT(DISTINCT repo) as count FROM prs")
        repos = cur.fetchone()["count"]

        # Get cache size (approximate)
        cur = conn.execute(
            """
            SELECT SUM(
                LENGTH(title) + LENGTH(author) + LENGTH(assignees) +
                LENGTH(branch) + LENGTH(html_url)
            ) as size FROM prs
            """
        )
        size = cur.fetchone()["size"] or 0

        return {"total_prs": total_prs, "repositories": repos, "approximate_size_bytes": size}
