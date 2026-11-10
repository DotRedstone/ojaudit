"""
Module: TUI / settings screen
Description: 提供分栏设置编辑、输入、默认值及离开确认。
Scope: TUI
Notes: UI 暂存更改；仅 Ctrl+S 显式保存配置。
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListView, Static

from ojaudit.tui.icons import label
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView
from ojaudit.tui.screens import ShellScreen
from ojaudit.tui.settings_model import CATEGORIES, Option, SettingsModel


class EditValue(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消", priority=True),
        Binding("h", "cancel", "取消"),
    ]


    def __init__(self, option: Option, value: Any) -> None:
        super().__init__()
        self.option = option
        self.current = str(value)

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-dialog", classes="dialog-box"):
            yield Label(
                label(
                    "settings",
                    f"{self.option.title} · 默认：{self.option.default}",
                    self.app.nerd_font,
                )
            )
            yield Input(value=self.current, id="edit-value")
            with Horizontal():
                yield Button(
                    label("save", "确定", self.app.nerd_font), id="accept", variant="primary"
                )
                yield Button(label("cancel", "取消", self.app.nerd_font), id="cancel")

    def on_mount(self) -> None:
        self.query_one("#edit-value", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def submit_value(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept":
            self.dismiss(self.query_one("#edit-value", Input).value)
        else:
            self.dismiss(None)


class ConfirmLeave(ModalScreen[bool]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "继续编辑", priority=True),
        Binding("h", "cancel", "继续编辑"),
    ]


    def compose(self) -> ComposeResult:
        with Vertical(id="confirm", classes="dialog-box"):
            yield Label(label("warning", "设置尚未保存，是否放弃更改？", self.app.nerd_font))
            with Horizontal():
                yield Button(
                    label("cancel", "放弃更改", self.app.nerd_font), id="discard", variant="warning"
                )
                yield Button(
                    label("back", "继续编辑", self.app.nerd_font), id="stay", variant="primary"
                )

    def on_mount(self) -> None:
        self.query_one("#stay", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "discard")


class SettingsScreen(ShellScreen):
    TITLE = "设置"
    PATH = "首页 › 设置"
    HINTS = "Enter 编辑  Space 开关  Ctrl+S 保存  Tab 面板  a/b 新增  d 删除"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "back", "返回"),
        ("left,h", "previous", "返回分类/上层"),
        ("right,l,enter", "edit", "进入/修改"),
        ("space", "toggle", "切换选项"),
        ("up,k", "up", "上移"),
        ("down,j", "down", "下移"),
        ("g", "first", "首项"),
        ("shift+g", "last", "末项"),
        ("slash", "search", "搜索"),
        ("ctrl+s", "save", "保存"),
        ("r", "reset", "恢复本类默认"),
        ("a", "add_white", "新增白名单/管理者"),
        ("b", "add_black", "新增黑名单"),
        ("d", "delete_list_item", "删除当前列表项"),
        ("tab", "focus_next", "切换窗格"),
        ("shift+tab", "focus_next", "切换窗格"),
    ]

    def __init__(self, model: SettingsModel | None = None) -> None:
        super().__init__()
        self.model = model or SettingsModel()
        self.category_index = 0
        self.rows: list[Option] = []
        self.focus_values = False

    def compose(self) -> ComposeResult:
        columns = Horizontal(
            NavigateListView(
                *(
                    ListItem(Label(label("settings", category, self.app.nerd_font)))
                    for category in CATEGORIES
                ),
                id="categories",
            ),
            Vertical(
                NavigateListView(id="settings-values"),
                Static("", id="settings-detail"),
                id="options-pane",
            ),
            id="settings-columns",
        )
        yield from self.shell([columns])

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#categories", ListView).border_title = label(
            "list", "分类", self.app.nerd_font
        )
        self.query_one("#options-pane", Vertical).border_title = label(
            "settings", "选项", self.app.nerd_font
        )
        self.query_one("#categories", ListView).index = 0
        self.reload()
        self.query_one("#categories", ListView).focus()
        self.status()

    def status(self) -> None:
        self.CURRENT = "设置 · " + ("● 未保存" if self.model.dirty else "已保存")
        self._update_status()

    def active_option(self) -> Option | None:
        view = self.query_one("#settings-values", ListView)
        index = view.index if view.index is not None else 0
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def reload(self) -> None:
        self.rows = self.model.options_for(CATEGORIES[self.category_index])
        view = self.query_one("#settings-values", ListView)
        previous = view.index or 0
        view.clear()
        for option in self.rows:
            value = self.model.values[option.key]
            if option.kind == "bool":
                display = "[✓]" if value else "[ ]"
            elif option.kind == "enum":
                display = f"‹ {value} ›"
            else:
                display = str(value)
            marker = "● " if self.model.changed(option) else "  "
            view.append(
                ListItem(
                    Label(
                        label("settings", f"{marker}{option.title}   {display}", self.app.nerd_font)
                    )
                )
            )
        if not self.rows:
            view.append(ListItem(Label("本类暂无可编辑项")))
        view.call_after_refresh(setattr, view, "index", min(previous, len(self.rows) - 1))
        self.detail()
        self.status()

    def detail(self) -> None:
        option = self.active_option()
        if option:
            self.query_one("#settings-detail", Static).update(
                f"默认：{option.default}\n类型：{option.kind} "
                f"{'（只读）' if option.readonly else ''}\n{option.description}"
            )

    @on(ListView.Highlighted, "#categories")
    def category_changed(self, event: ListView.Highlighted) -> None:
        if event.list_view.index is not None:
            self.category_index = event.list_view.index
            self.reload()

    @on(ListView.Highlighted, "#settings-values")
    def option_changed(self, event: ListView.Highlighted) -> None:
        self.detail()

    def action_focus_next(self) -> None:
        self.focus_values = not self.focus_values
        self.query_one("#settings-values" if self.focus_values else "#categories", ListView).focus()

    def modify(self, amount: int = 1) -> None:
        option = self.active_option()
        if not self.focus_values or option is None or option.readonly:
            return
        value = self.model.values[option.key]
        if option.kind == "enum":
            choices = option.choices
            value = choices[(choices.index(value) + amount) % len(choices)]
        elif option.kind == "bool":
            value = not value
        elif option.kind in ("int", "float"):
            value = value + amount
        else:
            return
        try:
            self.model.change(option, value)
        except (TypeError, ValueError) as exc:
            self.notify(str(exc), severity="warning")
            return
        self.reload()

    def active_view(self) -> ListView:
        return self.query_one("#settings-values" if self.focus_values else "#categories", ListView)

    def action_up(self) -> None:
        view = self.active_view()
        view.index = max(0, (view.index or 0) - 1)

    def action_down(self) -> None:
        view = self.active_view()
        view.index = min(len(view.children) - 1, (view.index or 0) + 1)

    def action_first(self) -> None:
        self.active_view().index = 0

    def action_last(self) -> None:
        view = self.active_view()
        view.index = max(0, len(view.children) - 1)

    def action_previous(self) -> None:
        if self.focus_values:
            self.action_focus_next()
        else:
            self.action_back()

    def action_toggle(self) -> None:
        option = self.active_option()
        if self.focus_values and option is not None and option.kind in ("bool", "enum"):
            self.modify()

    def action_edit(self) -> None:
        if not self.focus_values:
            self.action_focus_next()
            return
        option = self.active_option()
        if option is None or option.readonly:
            return
        if option.kind in ("bool", "enum"):
            self.modify()
            return
        self.app.push_screen(
            EditValue(option, self.model.values[option.key]),
            lambda value: self.apply_input(option, value),
        )

    def apply_input(self, option: Option, value: str | None) -> None:
        if value is None:
            return
        try:
            if option.kind == "int":
                converted: Any = int(value)
            elif option.kind == "float":
                converted = float(value)
            else:
                converted = value
            self.model.change(option, converted)
            self.reload()
        except (ValueError, TypeError) as exc:
            self.notify(f"设置无效：{exc}", severity="error")

    def _add_list_item(self, group: str) -> None:
        category = CATEGORIES[self.category_index]
        if category not in {"比赛筛选", "人员名单"}:
            return
        try:
            self.model.add_list_item(category, group)
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self.reload()
        rows = self.model.options_for(category)
        prefix = (
            "contest_filter." + group + "." if category == "比赛筛选" else "people.manager_entries."
        )
        indices = [index for index, option in enumerate(rows) if option.key.startswith(prefix)]
        if indices:
            view = self.query_one("#settings-values", ListView)
            view.call_after_refresh(
                setattr, view, "index", indices[-2] if category == "比赛筛选" else indices[-3]
            )
            self.focus_values = True
            view.focus()

    def action_add_white(self) -> None:
        self._add_list_item("whitelist")

    def action_add_black(self) -> None:
        self._add_list_item("blacklist")

    def action_delete_list_item(self) -> None:
        if not self.focus_values:
            return
        option = self.active_option()
        if option is None or not self.model.lists.is_list_key(option.key):
            return
        try:
            self.model.remove_list_item(option)
        except (ValueError, IndexError) as exc:
            self.notify(str(exc), severity="warning")
            return
        self.reload()

    def action_reset(self) -> None:
        self.model.restore(CATEGORIES[self.category_index])
        self.reload()

    def action_save(self) -> None:
        try:
            self.model.save()
        except (ValueError, TypeError, OSError) as exc:
            self.notify(f"保存失败：{exc}", severity="error")
            return
        self.reload()
        self.app.nerd_font = bool(self.model.values["appearance.nerd_font"])
        self.refresh_breadcrumb()
        self.query_one("#categories", ListView).border_title = label(
            "list", "分类", self.app.nerd_font
        )
        self.query_one("#options-pane", Vertical).border_title = label(
            "settings", "选项", self.app.nerd_font
        )
        categories = self.query_one("#categories", ListView)
        for category, item in zip(CATEGORIES, categories.children):
            item.query_one(Label).update(label("settings", category, self.app.nerd_font))
        self.notify(label("success", "设置已保存", self.app.nerd_font))

    def open_index(self, index: int) -> None:
        self.action_edit()

    def action_back(self) -> None:
        if self.model.dirty:
            self.app.push_screen(
                ConfirmLeave(),
                lambda discard: self.app.pop_screen() if discard else None,
            )
        else:
            self.app.pop_screen()
