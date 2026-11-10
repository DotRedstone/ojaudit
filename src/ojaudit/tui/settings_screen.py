"""
Module: TUI / settings screen
Description: 提供分栏设置编辑、输入、默认值及离开确认。
Scope: TUI
Notes: UI 暂存更改；仅 Ctrl+S 显式保存配置。
"""

from __future__ import annotations

from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListView, Static

from ojaudit.tui import ui
from ojaudit.tui.icons import label
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.screens import Chrome, Dialog, dialog_buttons
from ojaudit.tui.settings_model import CATEGORIES, Option, SettingsModel


class EditValue(Dialog):
    def __init__(self, option: Option, value: Any) -> None:
        super().__init__()
        self.option = option
        self.current = str(value)

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-dialog", classes="dialog"):
            yield Label(
                label("settings", self.option.title, self.app.nerd_font), classes="dialog-title"
            )
            yield Label(
                f"{self.option.description or ''}  默认：{self.option.default}".strip(),
                classes="dialog-hint",
            )
            yield Input(value=self.current, id="edit-value")
            yield dialog_buttons(("accept", "确定"), ("cancel", "取消"), self.app.nerd_font)

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


class ConfirmLeave(Dialog):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "继续编辑", priority=True),
        Binding("h", "cancel", "继续编辑"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm", classes="dialog warning"):
            yield Label(
                label("warning", "放弃未保存的设置？", self.app.nerd_font), classes="dialog-title"
            )
            yield Label("离开后本次修改不会写入配置文件。", classes="dialog-hint")
            with Horizontal(classes="dialog-buttons"):
                yield Button(
                    label("cancel", "放弃更改", self.app.nerd_font), id="discard", variant="error"
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


class SettingsScreen(Chrome, Screen):
    TITLE = "设置"
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
    PATH = "首页 › 设置"
    HINTS = (
        ("tab", "切换窗格"),
        ("↵", "编辑"),
        ("space", "开关"),
        ("a/b/d", "增删规则"),
        ("ctrl+s", "保存"),
        ("esc", "返回"),
    )

    def __init__(self, model: SettingsModel | None = None) -> None:
        super().__init__()
        self.model = model or SettingsModel()
        self.category_index = 0
        self.rows: list[Option] = []
        self.focus_values = False

    def compose(self) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            yield Static("", id="heading")
            with Horizontal(id="settings-columns"):
                yield ListView(
                    *(
                        ListItem(Label(label("settings", category, self.app.nerd_font)))
                        for category in CATEGORIES
                    ),
                    id="categories",
                    classes="panel",
                )
                with Vertical(id="options-pane", classes="panel"):
                    yield ListView(id="settings-values")
                    yield Static("", id="settings-detail")
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
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
        colors = ui.palette(self.app)
        heading = Text("设置", style=f"bold {colors.fg}")
        if self.model.dirty:
            heading.append("   ● 有未保存的修改，ctrl+s 保存", style=colors.warn)
        else:
            heading.append("   所有修改已保存", style=colors.muted)
        self.query_one("#heading", Static).update(heading)
        self._update_status()

    def on_resize(self, _event: object) -> None:
        self.call_after_refresh(self.reload)

    def active_option(self) -> Option | None:
        view = self.query_one("#settings-values", ListView)
        index = view.index if view.index is not None else 0
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def reload(self) -> None:
        self.rows = self.model.options_for(CATEGORIES[self.category_index])
        self.query_one("#options-pane", Vertical).border_title = label(
            "settings", CATEGORIES[self.category_index], self.app.nerd_font
        )
        view = self.query_one("#settings-values", ListView)
        previous = view.index or 0
        view.clear()
        colors = ui.palette(self.app)
        width = max(self.query_one("#options-pane").size.width - 6, 40)
        columns = (ui.Column("", 2), ui.Column(""), ui.Column("", min(36, width // 2)))
        for option in self.rows:
            value = self.model.values[option.key]
            if option.kind == "bool":
                display = (
                    Text("● 开", style=f"bold {colors.ok}")
                    if value
                    else Text("○ 关", style=colors.muted)
                )
            elif option.kind == "enum":
                display = Text("‹ ", style=colors.muted)
                display.append(str(value), style=f"bold {colors.accent}")
                display.append(" ›", style=colors.muted)
            elif value in ("", None):
                display = Text("未设置", style=colors.muted)
            else:
                display = Text(str(value), style=colors.fg)
            if option.readonly:
                display.stylize(colors.muted)
            changed = Text("●", style=colors.warn) if self.model.changed(option) else ""
            title = Text(option.title, style=colors.fg)
            view.append(ListItem(Label(ui.table_row([changed, title, display], columns, width))))
        if not self.rows:
            view.append(ListItem(Label(Text("本类暂无可编辑项", style=colors.muted))))
        view.call_after_refresh(setattr, view, "index", min(previous, len(self.rows) - 1))
        self.detail()
        self.status()

    def detail(self) -> None:
        option = self.active_option()
        if option:
            colors = ui.palette(self.app)
            text = Text(option.title, style=f"bold {colors.fg}")
            if option.readonly:
                text.append("  只读", style=colors.muted)
            if option.description:
                text.append("\n" + option.description, style=colors.fg)
            if isinstance(option.default, bool):
                default = "开" if option.default else "关"
            else:
                default = option.default if option.default not in ("", None) else "空"
            text.append(f"\n默认值 {default}", style=colors.muted)
            self.query_one("#settings-detail", Static).update(text)

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
        self.query_one("#categories", ListView).border_title = label(
            "list", "分类", self.app.nerd_font
        )
        self.query_one("#options-pane", Vertical).border_title = label(
            "settings", CATEGORIES[self.category_index], self.app.nerd_font
        )
        categories = self.query_one("#categories", ListView)
        for category, item in zip(CATEGORIES, categories.children):
            item.query_one(Label).update(label("settings", category, self.app.nerd_font))
        self.status()
        self.notify(label("success", "设置已保存", self.app.nerd_font))

    def action_back(self) -> None:
        if self.model.dirty:
            self.app.push_screen(
                ConfirmLeave(),
                lambda discard: self.app.pop_screen() if discard else None,
            )
        else:
            self.app.pop_screen()
