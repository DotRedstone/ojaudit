"""
Module: Pipeline Tests
Description: 验证采集后按顺序执行检测器。
Scope: Test
"""

from dataclasses import dataclass

from ojaudit.core.pipeline import run_analysis


@dataclass
class Bundle:
    contest: str


class DemoSource:
    def fetch_contest(self, session, contest_id):
        return Bundle(contest_id)


class DemoDetector:
    def __init__(self, name):
        self.name = name

    def analyze(self, bundle, parameters):
        return (self.name, bundle.contest, parameters)


def test_pipeline_preserves_detector_order():
    result = run_analysis(
        DemoSource(), [(DemoDetector("a"), {}), (DemoDetector("b"), {"x": 1})],
        None, "contest-1",
    )
    assert [item[0] for item in result.outputs] == ["a", "b"]
