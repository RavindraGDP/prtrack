from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from prtrack.navigation import NavigationManager
from prtrack.ui.menu import MenuManager
from prtrack.ui.overlays import OverlayManager
from prtrack.ui.prompts import PromptManager
from prtrack.ui.status import StatusManager


class FakeLabel:
    def __init__(self) -> None:
        self.display = False
        self._text = ""

    def update(self, text: str) -> None:
        self._text = text


class FakeTable:
    def __init__(self) -> None:
        self.display = False
        self.table = SimpleNamespace(has_focus=True)

    def focus(self) -> None:  # used by MenuManager.show_menu
        pass

    def get_selected_pr(self):  # used by MarkdownManager but not here
        return None

    def set_prs(self, prs) -> None:
        self.last = list(prs)


class FakeListView:
    def __init__(self) -> None:
        self.display = False

    def focus(self) -> None:
        pass


class FakeApp:
    def __init__(self) -> None:
        # basic widgets
        self._status = FakeLabel()
        self._table = FakeTable()
        self._menu = FakeListView()
        self._overlay_container = None
        self._overlay_list = None
        self._overlay_select_action: Callable[[str], None] | None = None
        self._navigation_stack: list[str] = []
        self._current_prs: list[Any] = []
        self._page_size = 2
        self._page = 1
        self._keymap = {"mark_markdown": "m", "back": "backspace"}
        self.cfg = SimpleNamespace(repositories=[], global_users=[])
        # managers (wire after self)
        self._navigation_manager = NavigationManager(self)
        self._overlay_manager = OverlayManager(self)  # for remove_all_prompts usage

        # spies
        self.mounted: list[Any] = []
        self.focus_set: list[Any] = []
        self.exited = False

    # methods expected by managers
    def mount(self, container) -> None:
        self.mounted.append(container)

    def set_focus(self, node) -> None:
        self.focus_set.append(node)

    def exit(self) -> None:
        self.exited = True

    # hooks used in MenuManager actions mapping
    def _show_cached_all(self) -> None:  # pragma: no cover - trivial
        pass

    def _select_repo(self, repo: str) -> None:  # pragma: no cover - trivial
        self._last_repo = repo

    def _load_repo_prs(self, repo: str) -> None:  # pragma: no cover - trivial
        self._last_repo = repo

    def _select_account(self, acct: str) -> None:  # pragma: no cover - trivial
        self._last_acct = acct

    def _load_account_prs(self, acct: str) -> None:  # pragma: no cover - trivial
        self._last_acct = acct

    def _show_config_menu(self, is_from_main_menu: bool = False) -> None:  # pragma: no cover - trivial
        self._from_main = is_from_main_menu

    def _handle_config_action(self, key: str) -> None:
        self._handled = key

    def _current_scope_key(self) -> str:
        return "all"

    def _remove_all_prompts(self) -> None:
        self._overlay_manager.remove_all_prompts()


@pytest.mark.parametrize("items", [["a", "b"], []])
def test_menu_manager_show_list_and_choice(items: list[str]) -> None:
    app = FakeApp()
    mm = MenuManager(app)

    # show_list
    mm.show_list("Title", items, select_action=lambda v: None)
    assert app._overlay_container is not None
    assert app._overlay_list is not None

    # show_choice_menu rewires overlay handler
    mm.show_choice_menu("Pick", [("k1", "L1"), ("k2", "L2")])
    assert callable(app._overlay_select_action)

    # show_menu focuses menu and clears stack
    app._navigation_stack = ["x", "y"]
    mm.show_menu()
    assert app._menu.display is True
    assert app._table.display is False
    assert app._status.display is False
    assert app._navigation_stack == []


def test_overlay_manager_close_overlay_and_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FakeApp()
    ov = OverlayManager(app)

    class Removable:
        def __init__(self) -> None:
            self.removed = False

        def remove(self) -> None:
            self.removed = True

    # close_overlay_if_open with no overlay
    assert ov.close_overlay_if_open() is False

    # set overlay and close
    app._overlay_container = Removable()
    app._overlay_list = object()
    app._overlay_select_action = lambda _: None
    ov_nav_called = False

    def fake_nav() -> None:
        nonlocal ov_nav_called
        ov_nav_called = True

    app._navigation_manager.navigate_back_or_home = fake_nav  # type: ignore[assignment]
    assert ov.close_overlay_if_open() is True
    assert ov_nav_called is True
    assert app._overlay_container is None and app._overlay_list is None and app._overlay_select_action is None

    # remove_all_prompts tolerates missing nodes
    ov.remove_all_prompts()


def test_prompt_manager_one_and_two(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FakeApp()
    pm = PromptManager(app)

    captured: dict[str, Any] = {}

    def cb1(val: str) -> None:
        captured["one"] = val

    pm.prompt_one_field("T", "PH", cb1)
    assert app.mounted, "container mounted"
    container = app.mounted[-1]

    # Emulate a user typing by stubbing query_one to return a fake with value
    class _FakeInput:
        def __init__(self, value: str) -> None:
            self.value = value

    container.query_one = lambda *args, **kwargs: _FakeInput("hello")  # type: ignore[assignment]
    container.remove = lambda: None  # type: ignore[assignment]
    pm.handle_prompt_one(container, "OK", cb1)
    assert captured["one"] == "hello"

    # Two-field prompt
    def cb2(v1: str, v2: str) -> None:
        captured["two"] = (v1, v2)

    pm.prompt_two_fields("T2", "A", "B", cb2)
    container2 = app.mounted[-1]

    # Stub query_one for #f1 and #f2
    class _FakeInput2:
        def __init__(self, value: str) -> None:
            self.value = value

    def _q(selector, *args, **kwargs):  # type: ignore[override]
        if isinstance(selector, str) and selector == "#f1":
            return _FakeInput2("x")
        if isinstance(selector, str) and selector == "#f2":
            return _FakeInput2("y")
        return _FakeInput2("")

    container2.query_one = _q  # type: ignore[assignment]
    container2.remove = lambda: None  # type: ignore[assignment]
    pm.handle_prompt_two(container2, "OK", cb2)
    assert captured["two"] == ("x", "y")


def test_status_manager_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FakeApp()
    sm = StatusManager(app)

    # No last refresh
    monkeypatch.setattr("prtrack.storage.get_last_refresh", lambda scope: None)
    sm.update_status_label("all", refreshing=False)
    assert "never" in app._status._text

    # With last refresh and pagination info
    monkeypatch.setattr("prtrack.storage.get_last_refresh", lambda scope: 0)
    app._current_prs = [1, 2, 3]
    app._page_size = 2
    app._page = 1
    sm.update_status_label("all", refreshing=True)
    assert "Refreshing" in app._status._text
    assert "Page 1/2 (3 PRs)" in app._status._text

    # Markdown status uses keymap and scope
    app._md_selected = {}
    app._keymap = {"mark_markdown": "m", "back": "backspace"}
    sm.update_markdown_status()
    assert "Selecting for Markdown" in app._status._text
