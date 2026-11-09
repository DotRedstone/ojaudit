"""
Module: Analysis Pipeline
Description: 编排数据源采集与检测器执行顺序。
Scope: Core
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PipelineResult:
    contest: Any
    bundle: Any
    outputs: tuple[Any, ...]


class Source(Protocol):
    def fetch_contest(self, session: Any, contest_id: str) -> Any: ...


class Detector(Protocol):
    name: str

    def analyze(self, bundle: Any, parameters: dict[str, Any]) -> Any: ...


def run_analysis(
    source: Source, detectors: list[tuple[Detector, dict[str, Any]]], session: Any, contest_id: str
) -> PipelineResult:
    """按传入顺序运行检测器；不在核心层隐式并发或访问网络。"""
    bundle = source.fetch_contest(session, contest_id)
    outputs = tuple(detector.analyze(bundle, parameters) for detector, parameters in detectors)
    contest = getattr(bundle, "contest", None)
    return PipelineResult(contest=contest, bundle=bundle, outputs=outputs)
