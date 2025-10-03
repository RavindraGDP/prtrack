from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

# Set up logging
logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


# Rate limiting constants
RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"
RATE_LIMIT_REMAINING_HEADER = "X-RateLimit-Remaining"
RATE_LIMIT_LIMIT_HEADER = "X-RateLimit-Limit"
FORBIDDEN_STATUS_CODE = 403


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
        state: State of the PR ("open", "closed", "merged").
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
    state: str = "open"  # Default to "open"


class GitHubClient:
    """Enhanced GitHub API client for fetching pull requests and reviews."""

    def __init__(self, token: str | None, max_retries: int = 3) -> None:
        """Initialize the client.

        Args:
            token: A GitHub personal access token. If provided, it is used for
                authenticated requests; otherwise, unauthenticated requests are
                made with stricter rate limits.
            max_retries: Maximum number of retries for failed requests.
        """
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "prtrack",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._max_retries = max_retries
        self._rate_limit_remaining = 999  # Initial value, will be updated after first request
        self._rate_limit_reset_time = 0

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
        # Check if we're rate limited and need to wait
        if self._rate_limit_remaining <= 1 and time.time() < self._rate_limit_reset_time:
            sleep_time = self._rate_limit_reset_time - time.time() + 1  # Add 1 second buffer
            logger.warning(f"Rate limited. Sleeping for {sleep_time} seconds.")
            await asyncio.sleep(sleep_time)

        # Try the request up to max_retries times
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.get(url, headers=self._headers, params=params)
                    # Update rate limit information
                    self._update_rate_limit_info(r)
                    r.raise_for_status()
                    return r.json()
            except httpx.HTTPStatusError as e:
                # If we hit rate limit, wait and retry
                status_code = getattr(e.response, "status_code", None)
                if (
                    status_code == FORBIDDEN_STATUS_CODE
                    and self._rate_limit_remaining <= 1
                    and attempt < self._max_retries
                ):
                    # Wait for rate limit reset before retrying
                    if time.time() < self._rate_limit_reset_time:
                        sleep_time = self._rate_limit_reset_time - time.time() + 1
                        logger.warning(f"Hit rate limit. Waiting {sleep_time} seconds before retry.")
                        await asyncio.sleep(sleep_time)
                    continue
                # For other HTTP errors or if we've exhausted retries, re-raise
                try:
                    code_str = str(getattr(e.response, "status_code", "unknown"))
                except Exception:
                    code_str = "unknown"
                logger.error(f"HTTP error {code_str} for URL {url}: {e}")
                raise
            except httpx.RequestError as e:
                # For network errors, retry if we have attempts left
                if attempt < self._max_retries:
                    logger.warning(f"Network error (attempt {attempt + 1}/{self._max_retries + 1}): {e}")
                    await asyncio.sleep(2**attempt)  # Exponential backoff
                    continue
                logger.error(f"Network error after {self._max_retries + 1} attempts: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise

        # This should never be reached, but just in case
        raise httpx.RequestError("Max retries exceeded", request=None)

    def _update_rate_limit_info(self, response: httpx.Response) -> None:
        """Update rate limit information from response headers.

        Args:
            response: The HTTP response to extract rate limit info from.
        """
        try:
            remaining = response.headers.get(RATE_LIMIT_REMAINING_HEADER)
            reset = response.headers.get(RATE_LIMIT_RESET_HEADER)
            if remaining is not None:
                self._rate_limit_remaining = int(remaining)
            if reset is not None:
                self._rate_limit_reset_time = int(reset)
        except Exception:
            # Silently ignore if we can't parse rate limit headers
            pass

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
                    state=pr.get("state", "open"),
                )
            )
        # Fetch approvals for each PR concurrently
        tasks = [asyncio.create_task(self._count_approvals(owner, repo, pr.number)) for pr in prs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
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

    async def list_prs_by_state(self, owner: str, repo: str, state: str = "open") -> list[PullRequest]:
        """List pull requests for a repository with a specific state.

        Args:
            owner: Repository owner/org login.
            repo: Repository name.
            state: PR state to filter by ("open", "closed", "all").

        Returns:
            A list of `PullRequest` objects with approvals populated.

        Raises:
            httpx.HTTPStatusError: If the API responds with an error status.
            httpx.RequestError: On network or timeout errors.
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
        data = await self._get(url, params={"state": state, "per_page": 100})
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
                    state=pr.get("state", state),
                )
            )
        # Fetch approvals for each PR concurrently
        tasks = [asyncio.create_task(self._count_approvals(owner, repo, pr.number)) for pr in prs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for pr, approvals in zip(prs, results, strict=False):
            pr.approvals = int(approvals) if not isinstance(approvals, Exception) else 0
        return prs

    async def get_pr_details(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        """Get detailed information about a specific pull request.

        Args:
            owner: Repository owner/org login.
            repo: Repository name.
            number: Pull request number.

        Returns:
            A dictionary with detailed PR information.

        Raises:
            httpx.HTTPStatusError: If the API responds with an error status.
            httpx.RequestError: On network or timeout errors.
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}"
        return await self._get(url)

    async def get_pr_comments(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        """Get comments for a specific pull request.

        Args:
            owner: Repository owner/org login.
            repo: Repository name.
            number: Pull request number.

        Returns:
            A list of comment dictionaries.

        Raises:
            httpx.HTTPStatusError: If the API responds with an error status.
            httpx.RequestError: On network or timeout errors.
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}/comments"
        return await self._get(url)

    async def get_pr_status_checks(self, owner: str, repo: str, ref: str) -> list[dict[str, Any]]:
        """Get status checks for a specific ref (branch or commit).

        Args:
            owner: Repository owner/org login.
            repo: Repository name.
            ref: The ref (branch or commit SHA) to get status checks for.

        Returns:
            A list of status check dictionaries.

        Raises:
            httpx.HTTPStatusError: If the API responds with an error status.
            httpx.RequestError: On network or timeout errors.
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/commits/{ref}/status"
        data = await self._get(url)
        return data.get("statuses", [])


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
