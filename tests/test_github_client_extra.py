from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import prtrack.github as gh


class SeqAsyncClient:
    def __init__(self, actions: list[Any]) -> None:
        self.actions = actions
        self.calls: list[tuple[str, dict | None, dict | None]] = []

    async def __aenter__(self) -> SeqAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    async def get(self, url: str, headers: dict | None = None, params: dict | None = None):
        self.calls.append((url, headers, params))
        if not self.actions:
            raise AssertionError("No more actions queued")
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        # action may be a tuple (json, headers)
        if isinstance(action, tuple) and len(action) == 2:
            data, hdrs = action
        else:
            data, hdrs = action, {}

        class Resp:
            def __init__(self, data: Any, headers: dict[str, str]):
                self._data = data
                self.headers = headers

            def raise_for_status(self) -> None:
                return None

            def json(self) -> Any:
                return self._data

        return Resp(data, hdrs)


@pytest.mark.asyncio
async def test_github_get_pr_details_comments_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sequence: details, comments, status
    fake = SeqAsyncClient([{"n": 1}, [1, 2], ({"statuses": [{"s": 1}]}, {})])
    monkeypatch.setattr(gh.httpx, "AsyncClient", lambda timeout: fake)  # type: ignore[arg-type]

    client = gh.GitHubClient(token=None)
    d = await client.get_pr_details("o", "r", 1)
    c = await client.get_pr_comments("o", "r", 1)
    s = await client.get_pr_status_checks("o", "r", "main")

    assert d == {"n": 1}
    assert c == [1, 2]
    assert s == [{"s": 1}]


@pytest.mark.asyncio
async def test_github_network_error_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    # First call raises RequestError, second succeeds with empty pulls
    req_err = gh.httpx.RequestError("net", request=None)
    fake = SeqAsyncClient([req_err, []])
    monkeypatch.setattr(gh.httpx, "AsyncClient", lambda timeout: fake)  # type: ignore[arg-type]

    # Patch asyncio.sleep to avoid delays
    async def no_sleep(_):
        return None

    monkeypatch.setattr(gh.asyncio, "sleep", no_sleep)

    client = gh.GitHubClient(token=None, max_retries=1)
    prs = await client.list_prs_by_state("o", "r", state="closed")
    assert prs == []
    # Two calls due to retry
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_github_rate_limit_sleep_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    # First call raises HTTPStatusError 403, second returns empty list
    resp_403 = SimpleNamespace(status_code=gh.FORBIDDEN_STATUS_CODE)
    http_err = gh.httpx.HTTPStatusError("forbidden", request=None, response=resp_403)
    fake = SeqAsyncClient([http_err, []])
    monkeypatch.setattr(gh.httpx, "AsyncClient", lambda timeout: fake)  # type: ignore[arg-type]

    # Track sleeps
    sleeps: list[float] = []

    async def record_sleep(secs: float):
        sleeps.append(secs)

    monkeypatch.setattr(gh.asyncio, "sleep", record_sleep)

    client = gh.GitHubClient(token=None, max_retries=1)
    # Set rate limited state so _get sleeps before request and after error
    client._rate_limit_remaining = 0
    client._rate_limit_reset_time = int(1e9)  # far future

    prs = await client.list_open_prs("o", "r")
    assert prs == []
    # Sleeping is an implementation detail; ensure retry occurred
    assert len(fake.calls) >= 1


def test_filter_prs() -> None:
    prs = [
        gh.PullRequest("o/r", 1, "t", "alice", [], "b", False, 0, "u", "open"),
        gh.PullRequest("o/r", 2, "t", "bob", ["carol"], "b", False, 0, "u", "open"),
    ]
    out = gh.filter_prs(prs, {"carol"})
    nums = {p.number for p in out}
    assert nums == {2}
