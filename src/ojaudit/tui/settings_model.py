"""
Module: TUI / settings model
Description: 设置页的数据模型：普通选项、过滤规则（比赛正则、手动剔除的比赛、管理者名单）、
    检测插件参数，以及「数据」：导出 / 导入配置、删除某场比赛的本地数据。
Scope: TUI
Notes:
- 只保存非机密设置；Cookie 与令牌不进入配置文件，导出时也会剔除。
- 修改先暂存在模型里，save() 时一次写入配置文件与数据库；管理者名单保存在数据库。
- 导入配置与删除比赛数据立即生效（界面先确认），不经过 save()。
"""

from __future__ import annotations

import copy
import sqlite3
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from ojaudit.core.config import config_dir, data_dir, load_config, save_config
from ojaudit.core.filters import (
    ContestFilter,
    ContestRule,
    check_pattern,
    filter_from_config,
    filter_to_config,
    matches,
)
from ojaudit.core.plugins import PluginManifest, discover_manifests, validate_parameters
from ojaudit.core.schema import Contest
from ojaudit.core.store import Store

CATEGORIES = ("账户", "过滤规则", "采集", "检测", "复核", "外观", "插件", "数据", "关于")
SECRET_KEYS = frozenset({"cookie", "token", "password"})
MANAGER_PLATFORM = "nowcoder"


def _textual_themes() -> tuple[str, ...]:
    from textual.theme import BUILTIN_THEMES

    return tuple(sorted(BUILTIN_THEMES))


def _syntax_themes() -> tuple[str, ...]:
    wanted = (
        "monokai",
        "dracula",
        "one-dark",
        "nord",
        "gruvbox-dark",
        "github-dark",
        "solarized-dark",
        "material",
        "native",
        "vim",
        "zenburn",
        "gruvbox-light",
        "solarized-light",
    )
    try:
        from pygments.styles import get_all_styles

        available = set(get_all_styles())
    except ImportError:  # pragma: no cover - rich 依赖 pygments
        available = set(wanted)
    return ("auto", "ansi_dark", "ansi_light", *(name for name in wanted if name in available))


@dataclass(frozen=True, slots=True)
class Option:
    category: str
    key: str
    title: str
    kind: str  # bool / enum / int / float / text / header / rule / manager / action
    default: Any = None
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    readonly: bool = False
    description: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(self.key.split("."))

    @property
    def editable(self) -> bool:
        return not self.readonly and self.kind != "header"

    def display(self, value: Any) -> str:
        return self.labels.get(str(value), str(value))


STATIC_OPTIONS = (
    Option(
        "账户",
        "nowcoder.uid",
        "牛客 UID",
        "text",
        "",
        description="留空时登录后自动识别；用于列出你参加过的比赛",
    ),
    Option(
        "账户",
        "storage.sqlite_path",
        "数据库路径",
        "text",
        "",
        description="留空使用默认路径；命令行 --db 优先",
    ),
    Option(
        "账户",
        "account.cookie_env",
        "Cookie 环境变量",
        "text",
        "NOWCODER_COOKIE",
        description="未在本机保存 Cookie 时，从这个环境变量读取",
    ),
    Option(
        "采集",
        "collect.phase",
        "采集范围",
        "enum",
        "contest",
        ("contest", "after", "all"),
        labels={"contest": "仅比赛期间", "after": "仅赛后补题", "all": "全部"},
    ),
    Option(
        "采集",
        "collect.threads",
        "并发线程",
        "int",
        8,
        minimum=1,
        maximum=32,
        description="同时下载源码的连接数；实测 8 线程约 47 份/秒、16 线程约 74 份/秒",
    ),
    Option(
        "采集",
        "collect.rate_limit",
        "每秒请求上限",
        "int",
        0,
        minimum=0,
        maximum=200,
        description="所有线程合计每秒最多发出的请求数，0 表示不限；被牛客限流时可调低",
    ),
    Option(
        "采集",
        "collect.timeout",
        "单次请求超时（秒）",
        "int",
        20,
        minimum=5,
        maximum=120,
    ),
    Option(
        "采集",
        "collect.retry_count",
        "失败重试次数",
        "int",
        2,
        minimum=0,
        maximum=10,
        description="网络错误、限流（429）或服务器错误时按 0.5、1、2… 秒退避后重试",
    ),
    Option(
        "采集",
        "collect.incremental",
        "增量采集",
        "bool",
        True,
        description="重新采集同一场比赛时，本地已有源码的提交不再下载",
    ),
    Option("采集", "collect.auto_analyze", "采集后自动检测", "bool", True),
    Option("检测", "detector.enabled", "启用检测", "bool", True),
    Option(
        "复核",
        "review.auto_advance",
        "处理后自动跳到下一条",
        "bool",
        True,
        description="复核一条线索后，自动打开下一条待复核线索",
    ),
    Option(
        "复核",
        "review.quick_mark",
        "快速复核",
        "bool",
        True,
        description="认定某人作弊时，此人其余待复核线索一并处理，撤销结论时自动恢复"
        "（只需判断是否作弊，作弊几道题对结论没有区别）",
    ),
    Option(
        "外观",
        "appearance.theme",
        "主题",
        "enum",
        "auto",
        ("auto", "wallpaper", *_textual_themes()),
        description="auto：有 pywal / matugen 配色时跟随壁纸，否则 catppuccin-mocha；"
        "ansi-dark / ansi-light 使用终端自身配色",
        labels={"auto": "auto（跟随壁纸）", "wallpaper": "wallpaper（壁纸配色）"},
    ),
    Option(
        "外观",
        "appearance.transparent",
        "透明背景",
        "bool",
        False,
        description="使用终端背景色，与 nvim / lazygit 的透明终端一致",
    ),
    Option(
        "外观",
        "appearance.border",
        "边框样式",
        "enum",
        "round",
        ("round", "solid", "heavy", "double", "ascii"),
        labels={
            "round": "圆角 ╭─╮",
            "solid": "直角 ┌─┐",
            "heavy": "粗线 ┏━┓",
            "double": "双线 ╔═╗",
            "ascii": "ASCII +-+",
        },
    ),
    Option(
        "外观",
        "appearance.syntax_theme",
        "代码高亮",
        "enum",
        "auto",
        _syntax_themes(),
        description="auto：ANSI 主题与透明背景下用终端配色，其余用 monokai",
    ),
    Option(
        "外观",
        "appearance.max_pages",
        "最多叠放层数",
        "int",
        4,
        minimum=0,
        maximum=20,
        description="页面层数超过这个数时，最外面的几层合成一页，标题写成路径；0 表示不折叠",
    ),
    Option("外观", "appearance.line_numbers", "代码行号", "bool", True),
    Option("外观", "appearance.key_hints", "底部按键提示", "bool", True),
    Option(
        "外观",
        "appearance.nerd_font",
        "Nerd Font 图标",
        "bool",
        False,
        description="需要终端使用 Nerd Font 字体",
    ),
)

STAGE_NAMES = {
    "builtin_pair": "指纹初筛",
    "nowcoder_similarity": "相似度",
    "nowcoder_template": "公共模板识别",
    "nowcoder_timeline": "时间线",
    "nowcoder_classify": "分级",
}
REQUIRED_STAGES = frozenset({"builtin_pair", "nowcoder_similarity", "nowcoder_classify"})
FILTER_OPTIONS = (
    Option(
        "过滤规则",
        "contest_filter.mode",
        "过滤模式",
        "enum",
        "blacklist",
        ("blacklist", "whitelist"),
        description="黑名单：隐藏命中规则的比赛。白名单：只显示命中规则的比赛（无规则时全部显示）",
        labels={"blacklist": "黑名单", "whitelist": "白名单"},
    ),
    Option(
        "过滤规则",
        "contest_filter.match_field",
        "匹配内容",
        "enum",
        "name",
        ("name", "name_id"),
        labels={"name": "比赛名称", "name_id": "名称和 ID"},
    ),
    Option("过滤规则", "contest_filter.case_sensitive", "区分大小写", "bool", False),
)


def _get(data: dict[str, Any], path: tuple[str, ...], default: Any) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _set(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = data
    for part in path[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[path[-1]] = value


def plugin_manifests(directory: str | Path | None = None) -> list[PluginManifest]:
    if directory is None:
        directory = Path(str(resources.files("ojaudit.plugins"))) / "detectors"
    return discover_manifests(directory)


def generated_options(manifests: list[PluginManifest]) -> tuple[Option, ...]:
    """检测阶段的开关与参数放在「检测」；「插件」只展示内置组件信息。"""
    options = list(STATIC_OPTIONS)
    order = list(STAGE_NAMES)
    ordered = sorted(
        manifests, key=lambda m: (order.index(m.name) if m.name in order else len(order), m.name)
    )
    for manifest in ordered:
        plugin = manifest.name
        name = STAGE_NAMES.get(plugin, plugin)
        options.append(
            Option(
                "插件",
                f"about.plugins.{plugin}",
                name,
                "text",
                f"内置 v{manifest.version}",
                readonly=True,
                description=manifest.description,
            )
        )
        if not manifest.kind.startswith("detector."):
            continue
        required = plugin in REQUIRED_STAGES
        options.append(
            Option("检测", f"stage.{plugin}", name, "header", description=manifest.description)
        )
        options.append(
            Option(
                "检测",
                f"plugins.{plugin}.enabled",
                "启用",
                "bool",
                True,
                readonly=required,
                description="必需阶段，不能关闭" if required else manifest.description,
            )
        )
        for key, spec in manifest.params.items():
            if not isinstance(spec, dict) or "type" not in spec:
                continue
            options.append(
                Option(
                    "检测",
                    f"plugins.{plugin}.params.{key}",
                    str(spec.get("label", key)),
                    str(spec["type"]),
                    spec.get("default"),
                    tuple(str(x) for x in spec.get("choices", ())),
                    spec.get("min"),
                    spec.get("max"),
                    description=str(spec.get("description") or manifest.description),
                )
            )
    options.append(
        Option(
            "插件",
            "about.install",
            "第三方插件",
            "text",
            "ojaudit plugins install 登记，只记录清单、不执行代码",
            readonly=True,
        )
    )
    return tuple(options)


def parse_manager(text: str) -> dict[str, str]:
    """「UID 备注」：第一个空白前为 UID，其余为备注。"""
    parts = text.strip().split(maxsplit=1)
    if not parts:
        raise ValueError("请输入 UID，可在后面加空格和备注")
    return {"uid": parts[0], "nickname": parts[1] if len(parts) > 1 else ""}


class SettingsModel:
    def __init__(
        self,
        path: str | Path | None = None,
        manifests: list[PluginManifest] | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self.path = path
        self.db_path = (
            Path(db_path).expanduser() if db_path is not None else data_dir() / "ojaudit.sqlite"
        )
        self.manifests = manifests if manifests is not None else plugin_manifests()
        self.base_options = generated_options(self.manifests)
        self.contests = self._read_contests()
        self._load()

    # ── 读取 ────────────────────────────────────────────

    def _query(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        if not self.db_path.is_file():
            return []
        connection = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(sql, args).fetchall()
        except sqlite3.Error:
            return []
        finally:
            connection.close()

    def _read_contests(self) -> list[Contest]:
        rows = self._query("SELECT platform, contest_id, name FROM contests")
        return [Contest(**dict(row)) for row in rows]

    def _read_managers(self) -> list[dict[str, str]]:
        rows = self._query(
            "SELECT uid, nickname FROM hidden_people WHERE platform=? ORDER BY uid",
            MANAGER_PLATFORM,
        )
        return [{"uid": str(row["uid"]), "nickname": str(row["nickname"])} for row in rows]

    def _load(self) -> None:
        self.saved = load_config(self.path)
        try:
            current = filter_from_config(self.saved.get("contest_filter"))
        except (TypeError, ValueError):
            current = ContestFilter()
        self.values: dict[str, Any] = {
            opt.key: _get(self.saved, opt.path, opt.default)
            for opt in self.base_options
            if opt.kind != "header"
        }
        self.values["contest_filter.mode"] = current.mode
        self.values["contest_filter.match_field"] = current.match_field
        self.values["contest_filter.case_sensitive"] = current.case_sensitive
        self.rules = [{"pattern": r.pattern, "enabled": r.enabled} for r in current.rules]
        self.excluded = list(current.excluded)
        self.managers = self._read_managers()
        self._baseline = self._snapshot()

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            copy.deepcopy(self.values),
            copy.deepcopy(self.rules),
            copy.deepcopy(self.managers),
            list(self.excluded),
        )

    # ── 选项列表 ────────────────────────────────────────

    @property
    def options(self) -> tuple[Option, ...]:
        return (*self.base_options, *self.filter_options())

    def filter_options(self) -> list[Option]:
        rows = list(FILTER_OPTIONS)
        rows.append(Option("过滤规则", "rules.header", f"比赛规则 · {len(self.rules)}", "header"))
        rows += [
            Option("过滤规则", f"rules.{index}", rule["pattern"], "rule")
            for index, rule in enumerate(self.rules)
        ]
        rows.append(Option("过滤规则", "rules.add", "添加规则", "action"))
        names = {f"{c.platform}/{c.contest_id}": c.name for c in self.contests}
        rows.append(
            Option(
                "过滤规则",
                "excluded.header",
                f"已剔除的比赛 · {len(self.excluded)}",
                "header",
                description="在首页或比赛列表按 d 剔除，不用写正则",
            )
        )
        rows += [
            Option("过滤规则", f"excluded.{index}", names.get(key, key), "excluded")
            for index, key in enumerate(self.excluded)
        ]
        rows.append(
            Option(
                "过滤规则",
                "managers.header",
                f"管理者 · {len(self.managers)}",
                "header",
                description="管理者不参与检测，排行榜中默认剔除",
            )
        )
        rows += [
            Option("过滤规则", f"managers.{index}", row["uid"], "manager")
            for index, row in enumerate(self.managers)
        ]
        rows.append(Option("过滤规则", "managers.add", "添加管理者", "action"))
        return rows

    def about_options(self) -> list[Option]:
        from ojaudit import __version__

        return [
            Option("关于", "about.version", "版本", "text", __version__, readonly=True),
            Option(
                "关于",
                "about.config",
                "配置文件",
                "text",
                str(Path(self.path) if self.path else config_dir() / "config.toml"),
                readonly=True,
            ),
            Option("关于", "about.database", "数据库", "text", str(self.db_path), readonly=True),
        ]

    def data_options(self) -> list[Option]:
        counts = {
            (row["platform"], row["contest_id"]): (row["subs"], row["runs"])
            for row in self._query(
                "SELECT c.platform, c.contest_id, "
                "(SELECT COUNT(*) FROM submissions s WHERE s.platform=c.platform "
                "AND s.contest_id=c.contest_id) AS subs, "
                "(SELECT COUNT(*) FROM analysis_runs a WHERE a.platform=c.platform "
                "AND a.contest_id=c.contest_id) AS runs FROM contests c"
            )
        }
        self.contest_counts = counts
        stored = [c for c in self.contests if any(counts.get((c.platform, c.contest_id), (0, 0)))]
        rows = [
            Option("数据", "data.config", "配置文件", "header"),
            Option(
                "数据",
                "data.export",
                "导出配置",
                "action",
                description="把已保存的设置连同管理者名单导出为 TOML 文件（不含 Cookie），"
                "可在另一台电脑导入",
            ),
            Option(
                "数据",
                "data.import",
                "导入配置",
                "action",
                description="用导出的 TOML 文件替换当前设置与管理者名单，立即生效",
            ),
            Option("数据", "data.reviews", "复核结果", "header"),
            Option(
                "数据",
                "data.reviews_export",
                "导出复核结果",
                "action",
                description="把所有比赛的人员结论、线索复核与管理者名单导出为 JSON，"
                "发给一起排查的人；不含代码与 Cookie",
            ),
            Option(
                "数据",
                "data.reviews_import",
                "导入复核结果（合并）",
                "action",
                description="合并别人导出的复核结果：作弊 > 存疑 > 正常取更重的结论，"
                "备注合并并注明来源，不同的结论列为冲突供复查",
            ),
            Option(
                "数据",
                "data.contests",
                f"本地比赛数据 · {len(stored)} 场",
                "header",
                description="删除后可重新采集；只登记未采集的比赛不在这里",
            ),
        ]
        rows += [
            Option("数据", f"data.contest.{c.platform}/{c.contest_id}", c.name, "contest")
            for c in sorted(stored, key=lambda c: c.name)
        ]
        return rows

    def options_for(self, category: str) -> list[Option]:
        if category == "过滤规则":
            return self.filter_options()
        if category == "数据":
            return self.data_options()
        if category == "关于":
            return self.about_options()
        return [opt for opt in self.base_options if opt.category == category]

    def value(self, option: Option) -> Any:
        if option.kind == "rule":
            return self.rules[int(option.key.split(".")[1])]
        if option.kind == "manager":
            return self.managers[int(option.key.split(".")[1])]
        if option.kind == "excluded":
            return self.excluded[int(option.key.split(".")[1])]
        if option.kind == "contest":
            platform, contest_id = option.key.removeprefix("data.contest.").split("/", 1)
            return getattr(self, "contest_counts", {}).get((platform, contest_id), (0, 0))
        return self.values.get(option.key, option.default)

    # ── 修改 ────────────────────────────────────────────

    def changed(self, option: Option) -> bool:
        values, rules, managers, excluded = self._baseline
        if option.kind == "excluded":
            index = int(option.key.split(".")[1])
            return index >= len(excluded) or excluded[index] != self.excluded[index]
        if option.kind in {"rule", "manager"}:
            index = int(option.key.split(".")[1])
            before, after = (
                (rules, self.rules) if option.kind == "rule" else (managers, self.managers)
            )
            return index >= len(before) or before[index] != after[index]
        if option.key in values:
            return self.values[option.key] != values[option.key]
        return False

    @property
    def dirty(self) -> bool:
        return self._snapshot() != self._baseline

    def change(self, option: Option, value: Any) -> None:
        if not option.editable or option.kind in {
            "rule",
            "manager",
            "action",
            "excluded",
            "contest",
        }:
            raise ValueError("只读设置")
        if option.kind == "bool" and not isinstance(value, bool):
            raise TypeError("开关需使用布尔值")
        if option.kind == "enum" and value not in option.choices:
            raise ValueError("无效选项")
        if option.kind in {"int", "float"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("数值类型无效")
            if option.kind == "int" and not isinstance(value, int):
                raise TypeError("需要整数")
            if option.minimum is not None and value < option.minimum:
                raise ValueError(f"不能小于 {option.minimum:g}")
            if option.maximum is not None and value > option.maximum:
                raise ValueError(f"不能大于 {option.maximum:g}")
        if option.kind == "text" and not isinstance(value, str):
            raise TypeError("文本类型无效")
        if isinstance(value, str):
            value = value.strip()
        if (
            option.key == "nowcoder.uid"
            and isinstance(value, str)
            and value
            and not value.isdigit()
        ):
            raise ValueError("UID 只能是数字")
        self.values[option.key] = value

    def parse(self, option: Option, text: str) -> Any:
        """把输入框文字转换为选项值；格式错误抛 ValueError。"""
        if option.kind == "int":
            try:
                return int(text)
            except ValueError:
                raise ValueError("请输入整数") from None
        if option.kind == "float":
            try:
                return float(text)
            except ValueError:
                raise ValueError("请输入数字") from None
        return text

    def check(self, option: Option, text: str) -> str | None:
        """输入框的实时校验：返回错误文字或 None。"""
        try:
            value = self.parse(option, text)
            saved = self.values.get(option.key)
            self.change(option, value)
            self.values[option.key] = saved
        except (TypeError, ValueError) as exc:
            return str(exc)
        return None

    def validate_pattern(self, pattern: str) -> str | None:
        if not pattern:
            return "规则不能为空"
        try:
            check_pattern(pattern, bool(self.values["contest_filter.case_sensitive"]))
        except ValueError as exc:
            return str(exc)
        return None

    def rule_hits(self, pattern: str) -> int:
        if self.validate_pattern(pattern):
            return 0
        config = ContestFilter(
            match_field=self.values["contest_filter.match_field"],
            case_sensitive=self.values["contest_filter.case_sensitive"],
        )
        rule = ContestRule(pattern)
        return sum(matches(contest, rule, config) for contest in self.contests)

    def set_rule(self, index: int | None, pattern: str) -> int:
        error = self.validate_pattern(pattern)
        if error:
            raise ValueError(error)
        if index is None:
            self.rules.append({"pattern": pattern, "enabled": True})
            return len(self.rules) - 1
        self.rules[index]["pattern"] = pattern
        return index

    def toggle_rule(self, index: int) -> None:
        self.rules[index]["enabled"] = not self.rules[index]["enabled"]

    def set_manager(self, index: int | None, text: str) -> int:
        row = parse_manager(text)
        others = [m["uid"] for i, m in enumerate(self.managers) if i != index]
        if row["uid"] in others:
            raise ValueError(f"管理者 {row['uid']} 已存在")
        if index is None:
            self.managers.append(row)
            return len(self.managers) - 1
        self.managers[index] = row
        return index

    def remove(self, option: Option) -> None:
        index = int(option.key.split(".")[1])
        if option.kind == "rule":
            del self.rules[index]
        elif option.kind == "manager":
            del self.managers[index]
        elif option.kind == "excluded":
            del self.excluded[index]
        else:
            raise ValueError("只能删除规则、管理者或剔除的比赛")

    def restore(self, category: str) -> None:
        if category == "过滤规则":
            self.rules = []
            self.excluded = []
            for option in FILTER_OPTIONS:
                self.values[option.key] = option.default
            return
        for option in self.base_options:
            if option.category == category and option.editable and option.key in self.values:
                self.values[option.key] = option.default

    def discard(self) -> None:
        self._load()

    def appearance(self) -> dict[str, Any]:
        return {
            key.removeprefix("appearance."): value
            for key, value in self.values.items()
            if key.startswith("appearance.")
        }

    # ── 保存 ────────────────────────────────────────────

    def save(self) -> None:
        values, _, managers, _ = self._baseline
        contest_filter = ContestFilter(
            excluded=tuple(self.excluded),
            rules=tuple(ContestRule(r["pattern"], r["enabled"]) for r in self.rules),
            mode=self.values["contest_filter.mode"],
            match_field=self.values["contest_filter.match_field"],
            case_sensitive=self.values["contest_filter.case_sensitive"],
        )
        for manifest in self.manifests:
            specs = {
                key: self.values[f"plugins.{manifest.name}.params.{key}"]
                for key in manifest.params
                if f"plugins.{manifest.name}.params.{key}" in self.values
            }
            if specs:
                validate_parameters(manifest, specs)
        config = load_config(self.path)
        for option in self.base_options:
            if not option.editable or option.key not in values:
                continue
            # 未修改的值不回写，避免把默认值写满配置文件。
            if self.values[option.key] != values[option.key]:
                _set(config, option.path, self.values[option.key])
        config["contest_filter"] = filter_to_config(contest_filter)
        people = config.get("people")
        if isinstance(people, dict):
            people.pop("manager_entries", None)
            people.pop("manager_uids", None)
        if self.managers != managers:
            before = {row["uid"]: row for row in managers}
            after = {row["uid"]: row for row in self.managers}
            with Store(self.db_path) as store, store.transaction():
                for uid in before.keys() - after.keys():
                    store.remove_hidden_person(MANAGER_PLATFORM, uid)
                for uid, row in after.items():
                    if before.get(uid) != row:
                        store.put_hidden_person(MANAGER_PLATFORM, uid, row["nickname"])
        save_config(config, self.path)
        self.contests = self._read_contests()
        self._load()

    # ── 数据（立即生效） ─────────────────────────────────

    def export_config(self, destination: str | Path) -> Path:
        """导出已保存的配置（剔除机密字段）与管理者名单。"""

        def clean(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items() if k.lower() not in SECRET_KEYS}
            return value

        exported = clean(load_config(self.path))
        exported["managers"] = [dict(row) for row in self._read_managers()]
        target = Path(destination).expanduser()
        return save_config(exported, target)

    @staticmethod
    def read_import(source: str | Path) -> dict[str, Any]:
        """读取并校验要导入的文件；格式不对时抛 ValueError。"""
        path = Path(source).expanduser()
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"无法读取：{exc.strerror or exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"不是有效的 TOML：{exc}") from exc
        try:
            filter_from_config(data.get("contest_filter"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"过滤规则无效：{exc}") from exc
        managers = data.get("managers", [])
        if not isinstance(managers, list) or not all(
            isinstance(row, dict) and isinstance(row.get("uid"), str) for row in managers
        ):
            raise ValueError("managers 必须是含 uid 的表数组")
        return data

    def import_config(self, source: str | Path) -> None:
        """用导入文件替换配置与管理者名单；未保存的修改会被放弃。"""
        data = self.read_import(source)
        managers = data.pop("managers", [])
        for key in SECRET_KEYS:
            data.pop(key, None)
        with Store(self.db_path) as store, store.transaction():
            for row in self._read_managers():
                store.remove_hidden_person(MANAGER_PLATFORM, row["uid"])
            for row in managers:
                store.put_hidden_person(MANAGER_PLATFORM, row["uid"], str(row.get("nickname", "")))
        save_config(data, self.path)
        self._load()

    def delete_contest(self, platform: str, contest_id: str) -> None:
        with Store(self.db_path) as store:
            store.clear_contest_data(platform, contest_id)
        self.contests = self._read_contests()

    def export_reviews(self, destination: str | Path) -> tuple[Path, int]:
        from ojaudit.core.review_exchange import export_reviews, write_reviews

        with Store(self.db_path) as store:
            data = export_reviews(store)
        return write_reviews(data, destination), len(data["contests"])

    def import_reviews(self, source: str | Path) -> Any:
        from ojaudit.core.review_exchange import import_reviews, read_reviews

        data = read_reviews(source)
        with Store(self.db_path) as store:
            report = import_reviews(store, data, Path(source).name)
        self.contests = self._read_contests()
        self.managers = self._read_managers()
        self._baseline = (*self._baseline[:2], list(self.managers), *self._baseline[3:])
        return report
