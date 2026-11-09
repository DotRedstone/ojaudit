"""第九阶段 CLI/TUI 共用路径与榜单一致性回归。"""

from types import SimpleNamespace

from ojaudit.cli import _export, _rank_rows
from ojaudit.core.config import data_dir
from ojaudit.core.ranking import RankingOptions
from ojaudit.core.schema import Contest
from ojaudit.core.store import Store
from ojaudit.tui.data import LocalContests
from ojaudit.tui.ranking_data import derived_rows, export_ranking, final_ranking
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.settings_model import SettingsModel, plugin_manifests


def test_default_database_and_real_plugin_params(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert LocalContests().db_path == data_dir() / "ojaudit.sqlite"
    assert SettingsModel(manifests=[]).db_path == LocalContests().db_path
    manifests = plugin_manifests()
    assert any(m.params for m in manifests)
    model = SettingsModel(path=tmp_path / "settings.toml", manifests=manifests)
    option = next(o for o in model.options_for("检测") if o.key.endswith(".solid_l2"))
    assert option.default == 0.98
    model.change(option, 0.96)
    model.save()
    restored = SettingsModel(path=tmp_path / "settings.toml", manifests=manifests)
    assert restored.values[option.key] == 0.96


def test_cli_and_tui_rank_exports_match(tmp_path):
    db = tmp_path / "ojaudit.sqlite"
    with Store(db) as store:
        store.put_contest("nowcoder", "demo", "合成比赛")
        store.execute(
            "INSERT INTO participants(platform, contest_id, uid, name) VALUES (?, ?, ?, ?)",
            ("nowcoder", "demo", "u1", "测试选手"),
        )
        store.connection.commit()
        local = LocalContests(db)
        data = ReviewData(local, Contest("nowcoder", "demo", "合成比赛"))
        assert _rank_rows(store, "nowcoder", "demo") == derived_rows(data)
        policy = RankingOptions()
        assert final_ranking(data, policy).rows
        tui_path = export_ranking(data, policy, "csv", tmp_path / "tui")
        cli_path = tmp_path / "cli.csv"
        _export(
            store,
            SimpleNamespace(
                platform="nowcoder",
                contest="demo",
                output=cli_path,
                format="csv",
                cheaters="drop",
                suspects="keep",
                managers="drop",
            ),
        )
        assert tui_path.read_bytes() == cli_path.read_bytes()
