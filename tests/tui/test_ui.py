"""
Module: Test / TUI ui
Description: 验证检测等级归并、中文列宽对齐与比赛摘要的等级计数。
Scope: Test
Notes: 仅使用合成数据。
"""

from rich.text import Text

from ojaudit.core.store import Store
from ojaudit.tui import ui
from ojaudit.tui.contest_list_data import contest_summary
from ojaudit.tui.data import LocalContests


def test_levels_merge_chinese_and_english_names():
    assert ui.level_rank("实锤") == ui.level_rank("high") == 0
    assert ui.level_rank("中偏强") == ui.level_rank("medium") == 1
    assert ui.level_rank("存疑") == ui.level_rank("LOW") == 2
    assert ui.is_high_priority("中偏强")
    assert not ui.is_high_priority("存疑")
    assert ui.level_rank("历史记录") > 3


def test_columns_align_by_terminal_cells():
    columns = (ui.Column("名称"), ui.Column("数量", 4, "right"))
    wide = ui.table_row(["训练赛第三场", "12"], columns, 20)
    narrow = ui.table_row(["abc", "3"], columns, 20)
    assert wide.cell_len == narrow.cell_len == 20
    clipped = ui.fit(Text("非常非常长的比赛名称"), 9)
    assert clipped.cell_len == 9
    assert clipped.plain.endswith("…")


def test_contest_summary_counts_chinese_levels(tmp_path):
    db = tmp_path / "synthetic.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "1", "虚构比赛")
        with store.connection:
            store.execute(
                "INSERT INTO analysis_runs(run_id,platform,contest_id,plugin_set,"
                "created_from,created_at) VALUES(?,?,?,?,?,?)",
                ("run", "synthetic", "1", "x", "test", "2026-01-01"),
            )
            for index, level in enumerate(("实锤", "中偏强", "存疑", "存疑")):
                store.execute(
                    "INSERT INTO findings(run_id,uid_a,uid_b,problem_index,language,"
                    "verdict_level,scores,reasons) VALUES(?,?,?,?,?,?,?,?)",
                    ("run", "fake-a", "fake-b", index, "cpp", level, "{}", "[]"),
                )
    local = LocalContests(db)
    summary = contest_summary(local, local.list_contests(show_all=True)[0].contest)
    assert summary.levels == (1, 1, 2)
    assert summary.findings == 4
    assert summary.reviewed == 0
