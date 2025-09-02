from __future__ import annotations

import pytest

from prtrack.tui import PRTrackApp

# Test constants
TEST_LIST_SIZE = 5
TEST_LAST_INDEX = 4
TEST_MIDDLE_INDEX = 3
TEST_FIRST_INDEX = 0


class DummyList:
    def __init__(self, n: int) -> None:
        self.children = [object() for _ in range(n)]
        self.index = 0
        self.display = True


class DummyEvent:
    def __init__(self, key: str) -> None:
        self.key = key
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True


def test_wrap_only_at_boundaries() -> None:
    app = PRTrackApp()
    # use overlay list as target to avoid dealing with actual Textual
    lst = DummyList(TEST_LIST_SIZE)
    app._overlay_list = lst  # type: ignore[attr-defined]

    # Down in middle: should not wrap or stop; Textual should handle
    lst.index = 1
    app.on_key(DummyEvent("down"))
    assert lst.index == 1

    # Down at last: should wrap to 0 and stop
    lst.index = TEST_LAST_INDEX
    ev = DummyEvent("down")
    app.on_key(ev)
    assert lst.index == TEST_FIRST_INDEX
    assert ev._stopped is True

    # Up in middle: no change
    lst.index = TEST_MIDDLE_INDEX
    app.on_key(DummyEvent("up"))
    assert lst.index == TEST_MIDDLE_INDEX

    # Up at first: should wrap to last and stop
    lst.index = TEST_FIRST_INDEX
    ev = DummyEvent("up")
    app.on_key(ev)
    assert lst.index == TEST_LAST_INDEX
    assert ev._stopped is True


def test_main_menu_enter_triggers_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    app = PRTrackApp()

    # Build a synthetic event matching selection for the main menu
    class Item:
        def __init__(self, id: str) -> None:
            self.id = id

    class ListView:
        pass

    called = {"all": False}

    def fake_show_cached_all() -> None:
        called["all"] = True

    monkeypatch.setattr(app, "_show_cached_all", fake_show_cached_all)

    # Simulate Textual Selected event structure with attributes used in handler
    class Selected:
        def __init__(self, list_view, item) -> None:
            self.list_view = list_view
            self.item = item

    event = Selected(app._menu, Item("list_all_prs"))

    app.on_list_view_selected(event)  # type: ignore[arg-type]

    assert called["all"] is True
