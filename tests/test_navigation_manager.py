from __future__ import annotations

from types import SimpleNamespace

from prtrack.navigation import NavigationManager


class FakeApp:
    def __init__(self) -> None:
        self._navigation_stack: list[str] = []
        self._md_mode = True
        self._table = SimpleNamespace(display=True)
        self._actions: list[str] = []
        self.cfg = SimpleNamespace(repositories=[SimpleNamespace(name="o/r", users=["bob"])], global_users=["alice"])
        self._markdown_manager = SimpleNamespace(
            show_markdown_menu=lambda: self._actions.append("md_menu"),
            md_select_repo=lambda v: self._actions.append(f"md_repo:{v}"),
            md_select_account=lambda v: self._actions.append(f"md_acct:{v}"),
        )

    def _show_list(self, title: str, items: list[str], select_action) -> None:
        self._actions.append(f"list:{title}:{len(items)}")

    def _show_menu(self) -> None:
        self._actions.append("menu")

    def _show_config_menu(self, is_from_main_menu: bool = False) -> None:
        self._actions.append(f"config:{is_from_main_menu}")


def test_navigation_push_pop_peek_clear() -> None:
    app = FakeApp()
    nm = NavigationManager(app)

    nm.push_screen("a")
    nm.push_screen("a")  # no duplicate consecutive
    nm.push_screen("b")
    assert app._navigation_stack == ["a", "b"]
    assert nm.peek_screen() == "b"
    assert nm.pop_screen() == "b"
    assert nm.pop_screen() == "a"
    assert nm.pop_screen() is None
    nm.push_screen("x")
    nm.clear_stack()
    assert app._navigation_stack == []


def test_navigation_markdown_back_and_back_or_home() -> None:
    app = FakeApp()
    nm = NavigationManager(app)

    # repo selection back
    app._navigation_stack = ["repo_selection"]
    assert nm.handle_markdown_back_if_needed() is True
    assert "list:Repos:1" in app._actions

    # account selection back
    app._navigation_stack = ["account_selection"]
    app._actions.clear()
    assert nm.handle_markdown_back_if_needed() is True
    assert "list:Accounts:2" in app._actions

    # default goes to markdown menu
    app._navigation_stack = []
    app._actions.clear()
    assert nm.handle_markdown_back_if_needed() is True
    assert "md_menu" in app._actions

    # navigate_back_or_home various previous screens
    app._actions.clear()
    app._navigation_stack = ["config_menu"]
    nm.navigate_back_or_home()
    assert app._actions  # some action executed

    app._actions.clear()
    app._navigation_stack = ["main_menu"]
    nm.navigate_back_or_home()
    assert app._actions  # menu shown

    app._actions.clear()
    app._navigation_stack = ["markdown_menu"]
    nm.navigate_back_or_home()
    assert "md_menu" in app._actions

    app._actions.clear()
    app._navigation_stack = ["unknown"]
    nm.navigate_back_or_home()
    assert "menu" in app._actions

    app._actions.clear()
    app._navigation_stack = []
    nm.navigate_back_or_home()
    assert "menu" in app._actions
