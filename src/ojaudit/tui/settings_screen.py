"""
Module: TUI / settings screen
Description: 左右分栏的设置页；过滤规则可逐条增删改，外观修改即时预览。
Scope: TUI
Notes:
- 修改先暂存，Ctrl+S 写入；未保存离开时确认，放弃则恢复外观预览。
- 输入统一走 lazygit 风格弹窗，正则输入时实时校验并显示命中的本地比赛数。
"""

from __future__ import annotations

from typing import Any, ClassVar

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Label, ListView, Static

from ojaudit.tui import ui
from ojaudit.tui.icons import label
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView
from ojaudit.tui.popup import ConfirmPopup, InputPopup, MenuPopup
from ojaudit.tui.screens import Chrome
from ojaudit.tui.settings_model import CATEGORIES, Option, SettingsModel
from ojaudit.tui.splitter import Splitter, start_drag


class EditValue(InputPopup):
    """编辑单个文本或数值选项。"""

    def __init__(self, option: Option, value: Any, model: SettingsModel | None = None) -> None:
        note = option.description
        if option.minimum is not None or option.maximum is not None:
            low = "" if option.minimum is None else f"{option.minimum:g}"
            high = "" if option.maximum is None else f"{option.maximum:g}"
            note = f"{note}  范围 {low}–{high}".strip()
        super().__init__(
            option.title,
            "" if value is None else str(value),
            note=note,
            validate=(lambda text: model.check(option, text)) if model else None,
            input_id="edit-value",
        )


class ConfirmLeave(ConfirmPopup):
    """True 表示放弃修改。"""

    def __init__(self) -> None:
        super().__init__("未保存", "设置有修改尚未保存，放弃并离开？", default=False)


class SettingsScreen(Chrome, Screen):
    PAGE_ICON = "settings"
    TITLE = "设置"
    PATH = "首页 › 设置"
    HINTS = (
        ("tab", "切换栏"),
        ("↵", "编辑"),
        ("space", "开关"),
        ("a/d", "添加/删除"),
        ("ctrl+s", "保存"),
        ("esc", "返回"),
    )
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "back", "返回（有修改时确认）"),
        ("left,h", "previous", "回到分类栏"),
        ("right,l,enter", "edit", "进入 / 编辑"),
        ("space", "toggle", "开关 / 切换"),
        ("up,k", "up", "上移"),
        ("down,j", "down", "下移"),
        ("g", "first", "首项"),
        ("shift+g", "last", "末项"),
        ("a", "add", "添加规则或管理者"),
        ("d,delete", "delete", "删除规则或管理者"),
        ("r", "reset", "恢复本类默认"),
        ("ctrl+s", "save", "保存"),
        ("tab,shift+tab", "focus_next", "切换栏"),
    ]

    def __init__(self, model: SettingsModel | None = None) -> None:
        super().__init__()
        self.model = model or SettingsModel()
        self.category_index = 0
        self.rows: list[Option] = []
        self.focus_values = False

    # ── 布局 ────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            yield Static("", id="heading")
            with Horizontal(id="settings-columns"):
                yield NavigateListView(
                    *(ListItem(Label(category)) for category in CATEGORIES),
                    id="categories",
                    classes="panel",
                )
                yield Splitter("categories", "settings", minimum=14)
                with Vertical(id="options-pane", classes="panel"):
                    yield NavigateListView(id="settings-values")
                    yield Static("", id="settings-detail")
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
        self.query_one("#categories").border_title = "分类"
        self.query_one("#categories", ListView).index = 0
        self.reload()
        self.query_one("#categories", ListView).focus()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        start_drag(self, event)

    def on_resize(self, _event: object) -> None:
        self.call_after_refresh(self.reload)

    def on_layout_change(self) -> None:
        self.reload()

    @property
    def category(self) -> str:
        return CATEGORIES[self.category_index]

    def active_view(self) -> ListView:
        return self.query_one("#settings-values" if self.focus_values else "#categories", ListView)

    def active_option(self) -> Option | None:
        view = self.query_one("#settings-values", ListView)
        index = view.index if view.index is not None else 0
        return self.rows[index] if 0 <= index < len(self.rows) else None

    # ── 渲染 ────────────────────────────────────────────

    def status(self) -> None:
        colors = ui.palette(self.app)
        heading = Text("设置", style=f"bold {colors.fg}")
        if self.model.dirty:
            heading.append("   * 有未保存的修改  ctrl+s 保存", style=colors.warn)
        else:
            heading.append("   已保存", style=colors.muted)
        self.query_one("#heading", Static).update(heading)
        self._update_status()

    def _row(self, option: Option, width: int) -> Text:
        colors = ui.palette(self.app)
        value = self.model.value(option)
        changed = (
            Text("*", style=f"bold {colors.warn}") if self.model.changed(option) else Text(" ")
        )
        if option.kind == "header":
            text = Text(option.title, style=f"bold {colors.accent}")
            return text
        if option.kind == "action":
            text = Text("  + " + option.title, style=colors.muted)
            return text
        if option.kind == "rule":
            mark = Text(
                "✓ " if value["enabled"] else "· ",
                style=colors.ok if value["enabled"] else colors.muted,
            )
            pattern = Text(value["pattern"], style=colors.fg if value["enabled"] else colors.muted)
            hits = self.model.rule_hits(value["pattern"])
            return ui.table_row(
                [changed, mark + pattern, Text(f"命中 {hits} 场", style=colors.muted)],
                (ui.Column("", 1), ui.Column(""), ui.Column("", 12, "right")),
                width,
            )
        if option.kind == "manager":
            title = Text(value["uid"], style=colors.fg)
            return ui.table_row(
                [changed, title, Text(value["nickname"] or "—", style=colors.muted)],
                (ui.Column("", 1), ui.Column("", 16), ui.Column("")),
                width,
            )
        if option.kind == "bool":
            shown = (
                Text("● 开", style=f"bold {colors.ok}")
                if value
                else Text("○ 关", style=colors.muted)
            )
        elif option.kind == "enum":
            shown = Text("‹ ", style=colors.muted)
            shown.append(option.display(value), style=f"bold {colors.accent}")
            shown.append(" ›", style=colors.muted)
        elif value in ("", None):
            shown = Text("未设置", style=colors.muted)
        else:
            shown = Text(str(value), style=colors.fg)
        if option.readonly:
            shown.stylize(colors.muted)
        return ui.table_row(
            [changed, Text(option.title, style=colors.fg), shown],
            (ui.Column("", 1), ui.Column(""), ui.Column("", min(40, width // 2))),
            width,
        )

    def reload(self, select: str | None = None) -> None:
        self.rows = self.model.options_for(self.category)
        pane = self.query_one("#options-pane", Vertical)
        pane.border_title = label("settings", self.category, self.app.nerd_font)
        view = self.query_one("#settings-values", ListView)
        previous = view.index or 0
        width = max(pane.size.width - 6, 30)
        view.clear()
        for option in self.rows:
            item = ListItem(Label(self._row(option, width)))
            if option.kind == "header":
                item.add_class("section")
            view.append(item)
        if select is not None:
            keys = [option.key for option in self.rows]
            previous = keys.index(select) if select in keys else previous
        view.call_after_refresh(setattr, view, "index", max(0, min(previous, len(self.rows) - 1)))
        self.detail()
        self.status()

    def detail(self) -> None:
        option = self.active_option()
        colors = ui.palette(self.app)
        text = Text()
        if option is not None:
            if option.kind == "rule":
                rule = self.model.value(option)
                text.append(rule["pattern"], style=f"bold {colors.fg}")
                text.append(
                    f"\n命中本地 {self.model.rule_hits(rule['pattern'])} 场比赛 · "
                    f"{'已启用' if rule['enabled'] else '已停用'}",
                    style=colors.muted,
                )
                text.append("\n↵ 编辑  space 启用/停用  d 删除", style=colors.muted)
            elif option.kind == "manager":
                row = self.model.value(option)
                text.append(f"{row['uid']} {row['nickname']}", style=f"bold {colors.fg}")
                text.append("\n不参与检测；排行榜中默认剔除\n↵ 编辑  d 删除", style=colors.muted)
            else:
                text.append(option.title, style=f"bold {colors.fg}")
                if option.description:
                    text.append("\n" + option.description, style=colors.fg)
                if (
                    option.editable
                    and option.kind not in {"action"}
                    and option.default not in ("", None)
                ):
                    default = option.display(option.default)
                    if option.kind == "bool":
                        default = "开" if option.default else "关"
                    text.append(f"\n默认 {default}", style=colors.muted)
        self.query_one("#settings-detail", Static).update(text)

    @on(ListView.Highlighted, "#categories")
    def category_changed(self, event: ListView.Highlighted) -> None:
        if event.list_view.index is not None and event.list_view.index != self.category_index:
            self.category_index = event.list_view.index
            self.query_one("#settings-values", ListView).index = 0
            self.reload()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        # 鼠标点击某一栏时同步当前栏，键盘与鼠标操作一致。
        if isinstance(event.widget, ListView):
            self.focus_values = event.widget.id == "settings-values"
            self._update_status()

    @on(ListView.Highlighted, "#settings-values")
    def option_changed(self, _event: ListView.Highlighted) -> None:
        self.detail()

    @on(NavigateListView.Activated)
    def activated(self, event: NavigateListView.Activated) -> None:
        if self.app.focused is self.query_one("#settings-values"):
            self.focus_values = True
        self.action_edit()

    # ── 导航 ────────────────────────────────────────────

    def action_focus_next(self) -> None:
        self.focus_values = not self.focus_values
        view = self.active_view()
        view.focus()
        if self.focus_values:
            self._skip_header(1)

    def _skip_header(self, step: int) -> None:
        view = self.query_one("#settings-values", ListView)
        index = view.index or 0
        while 0 <= index < len(self.rows) and self.rows[index].kind == "header":
            index += step
        if 0 <= index < len(self.rows):
            view.index = index

    def _move(self, step: int) -> None:
        view = self.active_view()
        count = len(view.children)
        if not count:
            return
        index = max(0, min((view.index or 0) + step, count - 1))
        if view.id == "settings-values":
            while 0 < index < count - 1 and self.rows[index].kind == "header":
                index += 1 if step > 0 else -1
        view.index = index

    def action_up(self) -> None:
        self._move(-1)

    def action_down(self) -> None:
        self._move(1)

    def action_first(self) -> None:
        self.active_view().index = 0
        if self.focus_values:
            self._skip_header(1)

    def action_last(self) -> None:
        view = self.active_view()
        view.index = max(0, len(view.children) - 1)

    def action_previous(self) -> None:
        if self.focus_values:
            self.action_focus_next()
        else:
            self.action_back()

    # ── 编辑 ────────────────────────────────────────────

    def _after_change(self, option: Option | None = None, select: str | None = None) -> None:
        if option is not None and option.key.startswith("appearance."):
            self.app.apply_appearance(self.model.appearance())
        self.reload(select)

    def _set(self, option: Option, value: Any) -> None:
        try:
            self.model.change(option, value)
        except (TypeError, ValueError) as exc:
            self.notify(str(exc), severity="warning")
            return
        self._after_change(option)

    def action_toggle(self) -> None:
        option = self.active_option()
        if not self.focus_values or option is None or not option.editable:
            return
        if option.kind == "bool":
            self._set(option, not self.model.value(option))
        elif option.kind == "enum":
            choices = option.choices
            current = self.model.value(option)
            index = choices.index(current) if current in choices else -1
            self._set(option, choices[(index + 1) % len(choices)])
        elif option.kind == "rule":
            self.model.toggle_rule(int(option.key.split(".")[1]))
            self._after_change(select=option.key)

    def action_edit(self) -> None:
        if not self.focus_values:
            self.action_focus_next()
            return
        option = self.active_option()
        if option is None or not option.editable:
            return
        if option.kind == "bool":
            self.action_toggle()
        elif option.kind == "enum":
            self.app.push_screen(
                MenuPopup(
                    option.title,
                    [(option.display(choice), choice) for choice in option.choices],
                    self.model.value(option),
                ),
                lambda value: value is not None and self._set(option, value),
            )
        elif option.kind == "rule":
            self._edit_rule(int(option.key.split(".")[1]))
        elif option.kind == "manager":
            self._edit_manager(int(option.key.split(".")[1]))
        elif option.key == "rules.add":
            self._edit_rule(None)
        elif option.key == "managers.add":
            self._edit_manager(None)
        else:
            self.app.push_screen(
                EditValue(option, self.model.value(option), self.model),
                lambda text: self.apply_input(option, text),
            )

    def apply_input(self, option: Option, text: str | None) -> None:
        if text is None:
            return
        try:
            self.model.change(option, self.model.parse(option, text))
        except (TypeError, ValueError) as exc:
            self.notify(f"设置无效：{exc}", severity="error")
            return
        self._after_change(option)

    def _rule_note(self, pattern: str) -> str | None:
        error = self.model.validate_pattern(pattern)
        if error:
            return error if pattern else None
        return None

    def _edit_rule(self, index: int | None) -> None:
        current = self.model.rules[index]["pattern"] if index is not None else ""
        mode = self.model.values["contest_filter.mode"]
        popup = InputPopup(
            "编辑规则"
            if index is not None
            else f"添加{'黑' if mode == 'blacklist' else '白'}名单规则",
            current,
            placeholder="正则，例如 ^新生|练习赛",
            note="Python 正则，匹配比赛名称",
            validate=self._rule_note,
            info=lambda pattern: (
                f"命中本地 {self.model.rule_hits(pattern)} 场比赛"
                if pattern
                else "Python 正则，匹配比赛名称"
            ),
            input_id="rule-value",
        )

        def done(pattern: str | None) -> None:
            if not pattern:
                return
            try:
                position = self.model.set_rule(index, pattern)
            except ValueError as exc:
                self.notify(str(exc), severity="error")
                return
            self._after_change(select=f"rules.{position}")

        self.app.push_screen(popup, done)

    def _edit_manager(self, index: int | None) -> None:
        current = ""
        if index is not None:
            row = self.model.managers[index]
            current = f"{row['uid']} {row['nickname']}".strip()
        self.app.push_screen(
            InputPopup(
                "编辑管理者" if index is not None else "添加管理者",
                current,
                placeholder="UID 备注，例如 1234567 张老师",
                note="管理者不参与检测，排行榜中默认剔除",
                validate=lambda text: None if text.strip() else "请输入 UID",
                input_id="manager-value",
            ),
            lambda text: text is not None and self._save_manager(index, text),
        )

    def _save_manager(self, index: int | None, text: str) -> None:
        try:
            position = self.model.set_manager(index, text)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self._after_change(select=f"managers.{position}")

    def action_add(self) -> None:
        if self.category != "过滤规则":
            return
        self.focus_values = True
        self.query_one("#settings-values", ListView).focus()
        option = self.active_option()
        in_managers = option is not None and option.key.startswith("managers.")
        if in_managers:
            self._edit_manager(None)
        else:
            self._edit_rule(None)

    def action_delete(self) -> None:
        option = self.active_option()
        if not self.focus_values or option is None or option.kind not in {"rule", "manager"}:
            return
        self.model.remove(option)
        self._after_change()

    def action_reset(self) -> None:
        self.model.restore(self.category)
        self.app.apply_appearance(self.model.appearance())
        self.reload()

    def action_save(self) -> None:
        try:
            self.model.save()
        except (ValueError, TypeError, OSError) as exc:
            self.notify(f"保存失败：{exc}", severity="error")
            return
        self.app.apply_appearance(self.model.appearance())
        self.reload()
        self.notify(label("success", "设置已保存", self.app.nerd_font))

    def action_back(self) -> None:
        if not self.model.dirty:
            self.app.pop_screen()
            return

        def answer(discard: bool | None) -> None:
            if discard:
                self.model.discard()
                self.app.apply_appearance(self.model.appearance())
                self.app.pop_screen()

        self.app.push_screen(ConfirmLeave(), answer)
