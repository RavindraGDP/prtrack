from __future__ import annotations

import asyncio

import pytest

from prtrack.storage import StorageManager


@pytest.mark.asyncio
async def test_storage_manager_schedule_and_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    sm = StorageManager()

    called: list[str] = []

    async def refresh_func():
        await asyncio.sleep(0)
        called.append("refresh")

    cb_called = []

    def cb():
        cb_called.append(True)

    # schedule with callback
    task = sm.schedule_refresh("all", refresh_func, callback=cb)
    assert sm.is_refreshing("all") is True

    await task
    assert called == ["refresh"]
    assert cb_called == [True]
    assert sm.is_refreshing("all") is False

    # schedule again and then cancel
    sm.schedule_refresh("all", refresh_func)
    assert sm.cancel_refresh("all") is True
    # canceling removes from queue
    assert sm.is_refreshing("all") is False


@pytest.mark.asyncio
async def test_storage_manager_replaces_existing_and_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sm = StorageManager()

    started: list[str] = []

    async def slow():
        started.append("slow")
        # never await; will be cancelled by next schedule
        await asyncio.sleep(0.01)

    async def failing():
        started.append("fail")
        raise RuntimeError("boom")

    # schedule slow then immediately schedule failing on same scope; first may be cancelled before running
    sm.schedule_refresh("s", slow)
    task = sm.schedule_refresh("s", failing)
    # error should be swallowed inside wrapper
    await task
    # Only failing is guaranteed to run
    assert started[-1] == "fail"
    assert sm.is_refreshing("s") is False
