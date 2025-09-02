from __future__ import annotations

from typing import Any

import pytest

import prtrack.github as gh


class FakeResponse:
    def __init__(self, json_data: Any) -> None:
        self._json = json_data

    def raise_for_status(self) -> None:  # no-op
        return None

    def json(self) -> Any:
        return self._json


class FakeAsyncClient:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = responses
        self.seen_headers: list[dict[str, str]] = []
        self.seen_urls: list[str] = []

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-any-unimported]
        return None

    async def get(
        self, url: str, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> FakeResponse:
        self.seen_urls.append(url)
        self.seen_headers.append(headers or {})
        if not self._responses:
            raise AssertionError("No more fake responses queued")
        return FakeResponse(self._responses.pop(0))


@pytest.mark.asyncio
async def test_github_client_lists_prs_and_counts_approvals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Prepare fake API responses
    pulls = [
        {
            "number": 10,
            "title": "Fix bug",
            "user": {"login": "alice"},
            "assignees": [{"login": "bob"}],
            "head": {"ref": "bugfix"},
            "draft": False,
            "html_url": "https://github.com/o/r/pull/10",
        },
        {
            "number": 5,
            "title": "Add feature",
            "user": {"login": "carol"},
            "assignees": [],
            "head": {"ref": "feature"},
            "draft": True,
            "html_url": "https://github.com/o/r/pull/5",
        },
    ]
    reviews_pr10 = [{"state": "APPROVED"}, {"state": "COMMENTED"}, {"state": "APPROVED"}]
    reviews_pr5 = [{"state": "CHANGES_REQUESTED"}]

    fake_client = FakeAsyncClient([pulls, reviews_pr10, reviews_pr5])

    # Patch httpx.AsyncClient to our fake
    monkeypatch.setattr(gh.httpx, "AsyncClient", lambda timeout: fake_client)  # type: ignore[arg-type]

    client = gh.GitHubClient(token="tok")
    prs = await client.list_open_prs("o", "r")

    assert [p.number for p in prs] == [10, 5]
    # Approvals should be counted from reviews
    assert {p.number: p.approvals for p in prs} == {10: 2, 5: 0}
    # Headers should include Authorization when token is set
    assert any(
        "Authorization" in h and h["Authorization"].startswith("Bearer ")
        for h in fake_client.seen_headers
    )
    # URLs should be correct (pulls then reviews per PR)
    assert fake_client.seen_urls[0].endswith("/repos/o/r/pulls")
    assert "/repos/o/r/pulls/10/reviews" in fake_client.seen_urls[1]
    assert "/repos/o/r/pulls/5/reviews" in fake_client.seen_urls[2]


@pytest.mark.asyncio
async def test_github_client_handles_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    pulls = []
    fake_client = FakeAsyncClient([pulls])
    monkeypatch.setattr(gh.httpx, "AsyncClient", lambda timeout: fake_client)  # type: ignore[arg-type]

    client = gh.GitHubClient(token=None)
    prs = await client.list_open_prs("o", "r")
    assert prs == []
    # Ensure Authorization header not present
    assert all("Authorization" not in h for h in fake_client.seen_headers)


@pytest.mark.asyncio
async def test_github_client_handles_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that GitHub client properly handles HTTP errors."""
    import httpx

    class FakeAsyncClientError:
        async def __aenter__(self) -> FakeAsyncClientError:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(
            self,
            url: str,
            headers: dict[str, str] | None = None,
            params: dict[str, Any] | None = None,
        ):
            # Raise an HTTPStatusError to simulate API error
            raise httpx.HTTPStatusError("Not Found", request=None, response=None)

    # Patch httpx.AsyncClient to our fake error client
    monkeypatch.setattr(gh.httpx, "AsyncClient", lambda timeout: FakeAsyncClientError())

    client = gh.GitHubClient(token="tok")

    # Should raise the HTTPStatusError
    with pytest.raises(httpx.HTTPStatusError):
        await client.list_open_prs("o", "r")


def test_fake_async_client_raises_error_when_no_responses():
    """Test that FakeAsyncClient raises AssertionError when no more responses are queued."""
    fake_client = FakeAsyncClient([])

    import asyncio

    # Should raise AssertionError when trying to get a response
    with pytest.raises(AssertionError, match="No more fake responses queued"):
        asyncio.run(fake_client.get("http://example.com"))
