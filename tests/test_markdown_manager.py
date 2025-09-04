from __future__ import annotations

from types import SimpleNamespace

import pytest

from prtrack.github import PullRequest
from prtrack.markdown_manager import MarkdownManager


class SpyMenu:
    def __init__(self, app) -> None:
        self.app = app
        self.calls: list[tuple[str, tuple, dict]] = []

    def show_choice_menu(self, title, actions):
        self.calls.append(("choice", (title,), {}))

    def show_list(self, title, items, select_action):
        self.calls.append(("list", (title, tuple(items)), {}))
        # store the action for later inspection
        self.app._last_select_action = select_action


class SpyNav:
    def __init__(self, app) -> None:
        self.app = app
        self.stack: list[str] = []

    def push_screen(self, name: str) -> None:
        self.stack.append(name)

    def pop_screen(self) -> str | None:
        return self.stack.pop() if self.stack else None

    def peek_screen(self) -> str | None:
        return self.stack[-1] if self.stack else None


class SpyStatus:
    def __init__(self, app) -> None:
        self.app = app
        self.updates: int = 0

    def update_markdown_status(self) -> None:
        self.updates += 1


class FakeTable:
    def __init__(self) -> None:
        self.display = True
        self._sel: PullRequest | None = None

    def get_selected_pr(self) -> PullRequest | None:
        return self._sel


class FakeApp:
    def __init__(self) -> None:
        self._menu_manager = SpyMenu(self)
        self._navigation_manager = SpyNav(self)
        self._status_manager = SpyStatus(self)
        self._prompt_manager = SimpleNamespace(prompt_one_field=lambda *a, **k: self._prompt(*a, **k))
        self._overlay_container = None
        self._md_selected: dict[tuple[str, int], PullRequest] = {}
        self._md_mode = False
        self._md_scope = None
        self._table = FakeTable()
        self._toasts: list[str] = []
        self.cfg = SimpleNamespace(
            repositories=[SimpleNamespace(name="o/r", users=["alice"])],
            global_users=["bob"],
        )
        self._last_prompt_args = None
        self._menu_shown = False
        self._cached_repo: str | None = None
        self._cached_account: str | None = None

    def _prompt(self, title, placeholder, cb):
        self._last_prompt_args = (title, placeholder, cb)

    def _show_toast(self, msg: str) -> None:
        self._toasts.append(msg)

    def _show_cached_repo(self, repo: str) -> None:
        self._cached_repo = repo

    def _show_cached_account(self, acc: str) -> None:
        self._cached_account = acc

    def _show_menu(self) -> None:
        self._menu_shown = True

    def _table_has_focus(self) -> bool:
        return True

    def action_go_back(self) -> None:
        self._menu_shown = True


def _make_pr(n: int = 1) -> PullRequest:
    return PullRequest(
        repo="o/r",
        number=n,
        title=f"T{n}",
        author="a",
        assignees=[],
        branch="b",
        draft=False,
        approvals=0,
        html_url="u",
    )


def test_markdown_menu_and_actions_flow(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = FakeApp()
    md = MarkdownManager(app)

    # show menu wires overlay action
    md.show_markdown_menu()
    assert app._menu_manager.calls and app._menu_manager.calls[0][0] == "choice"
    assert callable(app._overlay_select_action)

    # md_by_repo lists repos and sets md mode on selection
    md.handle_markdown_action("md_by_repo")
    assert app._navigation_manager.stack[-1] == "markdown_menu"
    assert ("list", ("Repos", ("o/r",)), {}) in app._menu_manager.calls
    app._last_select_action("o/r")
    assert app._cached_repo == "o/r"
    assert app._md_mode is True and app._md_scope == ("repo", "o/r")

    # md_by_account lists accounts and sets md mode on selection
    md.handle_markdown_action("md_by_account")
    assert ("list", ("Accounts", ("alice", "bob")), {}) in app._menu_manager.calls
    app._last_select_action("bob")
    assert app._cached_account == "bob"
    assert app._md_mode is True and app._md_scope == ("account", "bob")

    # toggle_markdown_pr marks/unmarks
    pr = _make_pr(7)
    app._table._sel = pr
    md.toggle_markdown_pr()
    assert (pr.repo, pr.number) in app._md_selected
    md.toggle_markdown_pr()
    assert (pr.repo, pr.number) not in app._md_selected
    assert app._status_manager.updates >= 2

    # review empty selection shows toast and menu again
    md.md_review_selection()
    assert any("No PRs selected" in t for t in app._toasts)

    # add, review then deselect via md_deselect
    app._md_selected[(pr.repo, pr.number)] = pr
    md.md_review_selection()
    assert app._navigation_manager.stack[-1] == "markdown_menu"
    # emulate selecting the label shown
    label = f"{pr.repo}#{pr.number} - {pr.title}"
    md.md_deselect(label)
    assert (pr.repo, pr.number) not in app._md_selected

    # prompt to save when none selected shows toast
    app._md_selected.clear()
    md.prompt_save_markdown()
    assert any("No PRs selected" in t for t in app._toasts)

    # with selection, prompt and do save
    app._md_selected[(pr.repo, pr.number)] = pr
    md.prompt_save_markdown()
    assert app._navigation_manager.stack[-1] == "markdown_menu"
    assert app._last_prompt_args is not None

    # patch writer and cwd
    wrote = {}
    monkeypatch.setattr("prtrack.markdown_manager.write_prs_markdown", lambda prs, path: wrote.setdefault("p", path))
    monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))

    # call the saved callback with empty to use default
    cb = app._last_prompt_args[2]
    cb("")
    assert wrote["p"].endswith("pr-track.md")
    # do_save_markdown exits md mode and returns to markdown menu because of stack
    assert app._md_mode is False and app._menu_shown is False  # show_markdown_menu, not main menu
