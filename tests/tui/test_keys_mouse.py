"""
Module: Test / TUI keyboard and mouse
Description: 用 Pilot 检查方向键、列表单击/双击和弹窗取消。
Scope: Test
Notes: 仅合成数据库与临时配置，不包含真实比赛或登录信息。
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input, ListView

from ojaudit.core.schema import Contest, Submission
from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.review_screens import ReviewPopup
from ojaudit.tui.screens import ContestListScreen, ContestOverviewScreen, EntryDialog, HomeScreen
from ojaudit.tui.settings_model import SettingsModel
from ojaudit.tui.settings_screen import ConfirmLeave, EditValue, SettingsScreen


def test_empty_home_focus_and_navigation(tmp_path):
    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            view = app.screen.query_one(ListView)
            assert app.focused is view
            assert "按 S 同步" in str(view.children[0].query_one("Label").render())
            await pilot.press("right")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            assert not app.screen.entries
            assert "按 c" in str(
                app.screen.query_one(ListView).children[0].query_one("Label").render()
            )
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("j", "k", "shift+g", "g")
            assert app.screen.query_one(ListView).index == 0
            await pilot.press("space")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            await pilot.press("left")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())


def test_mouse_single_then_double_click(tmp_path):
    db = tmp_path / "demo.sqlite"
    with Store(db) as store:
        store.import_contest(
            Contest("synthetic", "101", "虚构比赛"),
            submissions=[
                Submission("synthetic", "101", "s1", "u1", 0, "cpp", "AC", 100, 1, "contest", "x")
            ],
        )

    async def scenario():
        app = AuditApp(LocalContests(db))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.click("HomeScreen ListItem", offset=(2, 0))
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.click("#tile-0")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ContestOverviewScreen)
            # 叠放的书页：第一行是首页、第二行是比赛列表的标题边，点击直接翻回那一页。
            await pilot.click("#frame-top", offset=(6, 1))
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            await pilot.press("enter")
            await pilot.pause()
            await pilot.click("#frame-left", offset=(0, 2))
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())


def test_entry_dialog_esc_and_enter(tmp_path):
    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            await pilot.press("o")
            await pilot.pause()
            assert isinstance(app.screen, EntryDialog)
            assert isinstance(app.focused, Input)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("o")
            await pilot.pause()
            assert isinstance(app.screen, EntryDialog)
            await pilot.press("a", "space", "b", "enter")
            await pilot.pause()
            assert isinstance(app.screen, EntryDialog), "非法 ID 时 enter 不关闭"
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())


def test_choice_dialog_and_settings_confirmation(tmp_path):
    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            app.push_screen(ReviewPopup("虚构结论", (("正常", "normal"), ("存疑", "suspect"))))
            await pilot.pause()
            assert isinstance(app.screen, ReviewPopup)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

            model = SettingsModel(tmp_path / "config.toml", [])
            app.push_screen(SettingsScreen(model))
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            await pilot.press("l")
            assert app.screen.focus_values
            await pilot.press("j", "k", "space")
            await pilot.press("h")
            assert not app.screen.focus_values
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

            app.push_screen(ConfirmLeave())
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())


def test_edit_value_esc_from_input(tmp_path):
    model = SettingsModel(tmp_path / "config.toml", [])
    option = next(o for o in model.options if o.kind == "text" and not o.readonly)

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            app.push_screen(EditValue(option, "synthetic"))
            await pilot.pause()
            assert isinstance(app.focused, Input)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())


def test_confirm_popup_left_right_enter(tmp_path):
    from ojaudit.tui.popup import ConfirmPopup, HintRow

    results = []

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            for keys in (("enter",), ("left", "enter"), ("h", "l", "enter"), ("tab", "space")):
                app.push_screen(ConfirmPopup("合成确认", "继续？"), results.append)
                await pilot.pause()
                row = app.screen.query_one(HintRow)
                assert row.selected == 1, "默认选中安全的「否」"
                await pilot.press(*keys)
                await pilot.pause()
            app.push_screen(ConfirmPopup("合成确认", "继续？", default=True), results.append)
            await pilot.pause()
            assert app.screen.query_one(HintRow).selected == 0
            await pilot.press("right", "enter")
            await pilot.pause()

    asyncio.run(scenario())
    assert results == [False, True, False, True, False]


def test_popups_left_goes_back_right_confirms(tmp_path):
    from textual.widgets import Input

    from ojaudit.tui.popup import MenuPopup
    from ojaudit.tui.review_screens import ReviewPopup

    results = []

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            options = [("甲", "a"), ("乙", "b")]
            app.push_screen(MenuPopup("合成菜单", options), results.append)
            await pilot.pause()
            await pilot.press("left")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen), "← 关闭弹窗"
            app.push_screen(MenuPopup("合成菜单", options), results.append)
            await pilot.pause()
            await pilot.press("j", "right")
            await pilot.pause()
            app.push_screen(ReviewPopup("合成复核", options), results.append)
            await pilot.pause()
            await pilot.press("tab", "h", "l", "left", "left", "j")
            await pilot.pause()
            assert isinstance(app.screen, ReviewPopup), "备注框里方向键和字母用于编辑"
            # ← 在输入框里移动光标：j 插到了最前面。
            assert app.screen.query_one("#note", Input).value == "jhl"
            await pilot.press("tab", "l")
            await pilot.pause()

    asyncio.run(scenario())
    assert results == [None, "b", ("a", "jhl")]


def test_refilled_list_keeps_visible_highlight(tmp_path):
    """重填列表后高亮落在新条目上（以前单条比赛时高亮会消失）。"""
    db = tmp_path / "one.sqlite"
    with Store(db) as store:
        store.put_contest_listing("nowcoder", "1", "唯一的比赛", 1)

    async def scenario():
        app = AuditApp(LocalContests(db))
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            app.screen.refresh_home()
            await pilot.pause()
            view = app.screen.query_one("#recent", ListView)
            assert view.index == 0
            assert view.highlighted_child is not None
            assert view.highlighted_child.has_class("-highlight")

    asyncio.run(scenario())


def test_long_lists_mount_in_batches(tmp_path):
    """长列表先挂载一批；移动到末尾附近、G 跳到末尾、搜索靠后的行都会加载后面的行。"""
    from ojaudit.core.schema import Participant
    from ojaudit.tui.interaction import CHUNK
    from ojaudit.tui.review_data import ReviewData
    from ojaudit.tui.review_screens import PeopleScreen

    db = tmp_path / "many.sqlite"
    count = CHUNK * 2 + 50
    with Store(db) as store:
        store.import_contest(
            Contest("nowcoder", "1", "合成大赛"),
            [Participant("nowcoder", "1", f"u{i:04d}", f"选手{i:04d}") for i in range(count)],
        )
    local = LocalContests(db)
    data = ReviewData(local, Contest("nowcoder", "1", "合成大赛"))

    async def scenario():
        app = AuditApp(local)
        async with app.run_test(size=(120, 30)) as pilot:
            app.push_screen(PeopleScreen(data, "首页"))
            await pilot.pause()
            screen = app.screen
            view = screen.query_one("#items", ListView)
            assert len(screen.rows) == count
            assert view.mounted_count() == CHUNK, "只先挂载一批"
            view.index = CHUNK - 5
            await pilot.pause()
            assert view.mounted_count() == CHUNK * 2, "接近末尾时追加下一批"
            target = screen.rows[-1]["name"]
            assert screen._jump_to(str(target))
            await pilot.pause()
            assert view.mounted_count() == count and view.index == count - 1
            await pilot.press("g")
            await pilot.press("shift+g")
            assert view.index == count - 1

    asyncio.run(scenario())
