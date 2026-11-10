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
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, Label, ListView, Static

from ojaudit.tui.interaction import Breadcrumb
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.settings_model import CATEGORIES, Option, SettingsModel


class EditValue(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消", priority=True),
    ]

    CSS = """
    EditValue { align: center middle; }
    #edit-dialog { width: 66; height: auto; padding: 1 2; border: round $accent;
                   background: $panel; }
    """

    def __init__(self, option: Option, value: Any) -> None:
        super().__init__()
        self.option = option
        self.current = str(value)

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-dialog"):
            yield Label(f"{self.option.title} · 默认：{self.option.default}")
            yield Input(value=self.current, id="edit-value")
            with Horizontal():
                yield Button("确定", id="accept", variant="primary")
                yield Button("取消", id="cancel")

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

    CSS = """
    ConfirmLeave { align: center middle; }
    #confirm { width: 58; height: auto; border: round $warning;
               background: $panel; padding: 1 2; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Label("设置尚未保存，是否放弃更改？")
            with Horizontal():
                yield Button("放弃更改", id="discard", variant="warning")
                yield Button("继续编辑", id="stay", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#stay", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "discard")


class SettingsScreen(Screen):
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
        ("tab", "focus_next", "切换窗格"),
        ("shift+tab", "focus_next", "切换窗格"),
    ]
    CSS = """
    #settings-columns { height: 1fr; margin: 1 2; }
    #categories { width: 23; height: 1fr; border: round $panel; }
    #options-pane { width: 1fr; height: 1fr; border: round $panel; }
    #options-pane:focus-within, #categories:focus-within { border: round $accent; }
    #settings-values { height: 1fr; }
    #settings-detail { height: 5; padding: 0 1; }
    #settings-help { height: 2; padding: 0 2; }
    """

    def __init__(self, model: SettingsModel | None = None) -> None:
        super().__init__()
        self.model = model or SettingsModel()
        self.category_index = 0
        self.rows: list[Option] = []
        self.focus_values = False

    def compose(self) -> ComposeResult:
        yield Breadcrumb("首页 › 设置", id="breadcrumb")
        with Horizontal(id="settings-columns"):
            yield ListView(
                *(ListItem(Label(category)) for category in CATEGORIES),
                id="categories",
            )
            with Vertical(id="options-pane"):
                yield ListView(id="settings-values")
                yield Static("", id="settings-detail")
        yield Static(
            "↑↓/jk 移动 · ←/h 返回 · →/l/Enter 进入 · Space 切换 · Ctrl+S 保存",
            id="settings-help",
        )
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#categories", ListView).border_title = "分类"
        self.query_one("#options-pane", Vertical).border_title = "选项"
        self.query_one("#categories", ListView).index = 0
        self.reload()
        self.query_one("#categories", ListView).focus()
        self.status()

    def status(self) -> None:
        self.query_one("#status", Static).update(
            " NORMAL  ›  设置 · " + ("● 未保存" if self.model.dirty else "已保存")
        )

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
            view.append(ListItem(Label(f"{marker}{option.title}   {display}")))
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
        self.notify("设置已保存")

    def action_back(self) -> None:
        if self.model.dirty:
            self.app.push_screen(
                ConfirmLeave(),
                lambda discard: self.app.pop_screen() if discard else None,
            )
        else:
            self.app.pop_screen()
