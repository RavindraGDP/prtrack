from __future__ import annotations

from types import SimpleNamespace

from prtrack.event_handler import EventHandler
from prtrack.github import PullRequest


class FakeListView:
    def __init__(self) -> None:
        self.display = True
        self.children: list[SimpleNamespace] = []
        self.index = 0


class FakeEvent:
    def __init__(self, key: str | None = None) -> None:
        self.key = key
        self._stopped = False

    def prevent_default(self):
        pass

    def stop(self):
        self._stopped = True


class FakeButton:
    def __init__(self, label: str, container):
        self.label = label
        self.parent = SimpleNamespace(parent=container)


def _app_with_lists():
    app = SimpleNamespace()
    app._overlay_list = FakeListView()
    app._overlay_container = SimpleNamespace(id="list_overlay", remove=lambda: None)
    app._overlay_select_action = lambda k: app._actions.append(k)
    app._menu = FakeListView()
    app._menu.display = True
    app._actions = []
    app._keymap = {"back": "esc", "next_page": "]", "prev_page": "[", "open_pr": "enter", "mark_markdown": " "}
    app._table = SimpleNamespace(display=True, cursor_row=0)
    app._table_has_focus = lambda: True
    app._menu.display = True
    app._overlay_container = None
    app.cfg = SimpleNamespace(repositories=[SimpleNamespace(name="o/r", users=["alice"])], global_users=["bob"])
    app._show_cached_all = lambda: app._actions.append("all")
    app._show_list = lambda title, items, select_action=None: app._actions.append((title, list(items)))
    app._select_repo = lambda name: app._actions.append(("repo", name))
    app._select_account = lambda name: app._actions.append(("acct", name))
    app._load_repo_prs = lambda name: app._actions.append(("load_repo", name))
    app._load_account_prs = lambda name: app._actions.append(("load_acct", name))
    app._markdown_manager = SimpleNamespace(show_markdown_menu=lambda: app._actions.append("md"))
    app._show_config_menu = lambda is_from_main_menu=False: app._actions.append(("cfg", is_from_main_menu))
    app.exit = lambda: app._actions.append("exit")
    app._show_menu = lambda: app._actions.append("menu")
    app.action_go_back = lambda: app._actions.append("back")
    app.action_next_page = lambda: app._actions.append("next")
    app.action_prev_page = lambda: app._actions.append("prev")
    app.action_toggle_markdown_pr = lambda: app._actions.append("toggle_md")
    app._md_mode = False
    return app


class Item:
    def __init__(self, id: str = "") -> None:
        self.id = id
        self._value = id


class SelEvent:
    def __init__(self, list_view, item):
        self.list_view = list_view
        self.item = item


def test_overlay_and_main_menu_selection():
    app = _app_with_lists()
    h = EventHandler(app)

    # overlay handling when overlay_list matches
    app._overlay_list = FakeListView()
    e = SelEvent(app._overlay_list, Item("x"))
    handled = h._handle_overlay_selection_if_any(e)
    assert handled is True

    # main menu handling
    e2 = SelEvent(app._menu, Item("list_accounts"))
    h._handle_main_menu_selection_if_any(e2)
    # _show_list appends (title, items)
    assert any(isinstance(a, tuple) and a[0] == "Tracked Accounts" for a in app._actions)


def test_keymap_and_wrap_behavior(monkeypatch):
    app = _app_with_lists()
    h = EventHandler(app)
    # table open key when not in md mode triggers browser open; stub webbrowser
    pr = PullRequest("o/r", 1, "t", "alice", [], "b", False, 0, "http://u")
    app._table.get_selected_pr = lambda: pr
    opened = {}
    monkeypatch.setattr("webbrowser.open", lambda url: opened.setdefault("u", url))
    # Ensure table_active True per handler conditions
    app._menu.display = False
    h._handle_custom_keymap("enter", FakeEvent("enter"))
    # In _handle_custom_keymap, open occurs only when table_active is true and md_mode False
    assert opened.get("u") == "http://u"
    # back key
    h._handle_custom_keymap("esc", FakeEvent("esc"))
    assert app._actions[-1] == "back"
    # pagination keys
    h._handle_custom_keymap("]", FakeEvent("]"))
    h._handle_custom_keymap("[", FakeEvent("["))
    assert app._actions[-2:] == ["next", "prev"]
    # wrap logic (ensure menu is active target)
    app._overlay_list = None
    app._menu.display = True
    app._menu.children = [SimpleNamespace(), SimpleNamespace()]
    app._menu.index = 0
    h._handle_list_wrap_key("up", FakeEvent("up"))
    assert app._menu.index == 1
    app._menu.index = 1
    h._handle_list_wrap_key("down", FakeEvent("down"))
    assert app._menu.index == 0


def test_prompt_button_handling(monkeypatch):
    app = _app_with_lists()
    h = EventHandler(app)

    # one field OK
    cont1 = SimpleNamespace(
        id="prompt_one",
        children=[SimpleNamespace(), SimpleNamespace(value="v1")],
        data_cb=lambda v: None,
        remove=lambda: None,
    )
    e1 = SimpleNamespace(button=FakeButton("OK", cont1))
    h.on_button_pressed(e1)

    # two fields Cancel (still removes)
    called = {}
    cont2 = SimpleNamespace(
        id="prompt_two",
        children=[SimpleNamespace(), SimpleNamespace(value="a"), SimpleNamespace(value="b")],
        data_cb=lambda a, b: None,
        remove=lambda: called.setdefault("r", True),
    )
    e2 = SimpleNamespace(button=FakeButton("Cancel", cont2))
    h.on_button_pressed(e2)
    assert called.get("r", False) is True
