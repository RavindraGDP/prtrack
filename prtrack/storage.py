from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterable

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
        conn.execute(
            "REPLACE INTO metadata(key, value) VALUES (?, ?)", (f"last_refresh:{scope}", str(ts))
        )


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
        cur = conn.execute("SELECT * FROM prs ORDER BY number DESC")
        result: list[PullRequest] = []
        for r in cur.fetchall():
            pr = _row_to_pr(r)
            if pr.author == account or account in pr.assignees:
                result.append(pr)
        return result


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
