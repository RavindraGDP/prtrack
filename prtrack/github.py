from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"


@dataclass
class PullRequest:
    """Lightweight representation of a GitHub pull request.

    Attributes:
        repo: "owner/repo" string identifying the repository.
        number: Pull request number.
        title: PR title.
        author: Login of the PR author.
        assignees: List of usernames assigned to the PR.
        branch: Head branch name.
        draft: Whether the PR is marked as draft.
        approvals: Number of approval reviews on the PR.
        html_url: Web URL to the PR.
    """

    repo: str
    number: int
    title: str
    author: str
    assignees: list[str]
    branch: str
    draft: bool
    approvals: int
    html_url: str


class GitHubClient:
    """Minimal GitHub API client for fetching pull requests and reviews."""

    def __init__(self, token: str | None) -> None:
        """Initialize the client.

        Args:
            token: A GitHub personal access token. If provided, it is used for
                authenticated requests; otherwise, unauthenticated requests are
                made with stricter rate limits.
        """
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "prtrack",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Perform a GET request and return parsed JSON.

        Args:
            url: Absolute endpoint URL.
            params: Optional query parameters.

        Returns:
            The JSON-decoded response body.

        Raises:
            httpx.HTTPStatusError: If the response indicates an HTTP error.
            httpx.RequestError: On network or timeout errors.
        """
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=self._headers, params=params)
            r.raise_for_status()
            return r.json()

    async def list_open_prs(self, owner: str, repo: str) -> list[PullRequest]:
        """List open pull requests for a repository.

        Args:
            owner: Repository owner/org login.
            repo: Repository name.

        Returns:
            A list of `PullRequest` objects with approvals populated.

        Raises:
            httpx.HTTPStatusError: If the API responds with an error status.
            httpx.RequestError: On network or timeout errors.
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
        data = await self._get(url, params={"state": "open", "per_page": 100})
        prs: list[PullRequest] = []
        for pr in data:
            prs.append(
                PullRequest(
                    repo=f"{owner}/{repo}",
                    number=pr["number"],
                    title=pr["title"],
                    author=pr["user"]["login"],
                    assignees=[a["login"] for a in pr.get("assignees", [])],
                    branch=pr["head"]["ref"],
                    draft=bool(pr.get("draft", False)),
                    approvals=0,  # filled below via concurrent review loads
                    html_url=pr["html_url"],
                )
            )
        # Fetch approvals for each PR concurrently
        import asyncio as _asyncio

        tasks = [_asyncio.create_task(self._count_approvals(owner, repo, pr.number)) for pr in prs]
        results = await _asyncio.gather(*tasks, return_exceptions=True)
        for pr, approvals in zip(prs, results, strict=False):
            pr.approvals = int(approvals) if not isinstance(approvals, Exception) else 0
        return prs

    async def _count_approvals(self, owner: str, repo: str, number: int) -> int:
        """Count approval reviews for a pull request.

        Args:
            owner: Repository owner/org login.
            repo: Repository name.
            number: Pull request number.

        Returns:
            The number of reviews with state "APPROVED".

        Raises:
            httpx.HTTPStatusError: If the API responds with an error status.
            httpx.RequestError: On network or timeout errors.
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/reviews"
        data = await self._get(url)
        approvals = sum(1 for r in data if r.get("state") == "APPROVED")
        return approvals


def filter_prs(prs: Iterable[PullRequest], users: set[str]) -> list[PullRequest]:
    """Return PRs where the author or any assignee is in `users`.

    Args:
        prs: Iterable of `PullRequest` instances.
        users: Set of usernames to include; if empty, returns all PRs.

    Returns:
        A list of PRs matching the user filter.
    """
    if not users:
        return list(prs)
    selected: list[PullRequest] = []
    for pr in prs:
        if pr.author in users or any(a in users for a in pr.assignees):
            selected.append(pr)
    return selected
