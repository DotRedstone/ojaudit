"""
Module: Nowcoder Source Tests
Description: 使用合成 HTTP 响应验证牛客数据源映射与凭据边界。
Scope: Test
"""

import json

import pytest

from ojaudit.plugins.sources.nowcoder import NowcoderSource


class Response:
    def __init__(self, value: str):
        self.value = value

    def read(self) -> bytes:
        return self.value.encode()


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return Response(self.responses.pop(0))


def test_source_maps_synthetic_contest_and_never_persists_cookie(monkeypatch):
    info = {"data": {"sourceId": 7, "name": "Synthetic", "startTime": 100, "endTime": 200}}
    rank = {
        "data": {
            "problemData": [{"problemId": "p1", "index": "A", "title": "Demo", "score": 100}],
            "submitDataList": [
                {
                    "signUpUsers": [{"uid": 11, "name": "Synthetic User"}],
                    "submissions": [
                        {
                            "uid": 11,
                            "problemId": "p1",
                            "submissionId": 21,
                            "submitTime": 150,
                            "status": 5,
                        }
                    ],
                }
            ],
        }
    }
    page = '<pre class="prettyprint lang-cpp">int main(){return 0;}</pre><div class="coder-cont-legend">语言：C++<br>运行状态：<b>Accepted</b><br>得分：<b>100</b></div>'
    opener = FakeOpener([json.dumps(info), json.dumps(rank), page])
    source = NowcoderSource({"cookie": "SYNTHETIC_COOKIE"}, opener=opener)
    bundle = source.fetch_contest(None, "7")
    assert bundle.contest.name == "Synthetic"
    assert bundle.problems[0].index == 0
    assert bundle.participants[0].uid == "11"
    assert bundle.submissions[0].code == "int main(){return 0;}"
    assert bundle.submissions[0].language == "cpp"
    assert all("SYNTHETIC_COOKIE" not in repr(item) for item in bundle.submissions)


def test_source_requires_configured_or_environment_cookie(monkeypatch):
    monkeypatch.delenv("NOWCODER_COOKIE", raising=False)
    with pytest.raises(RuntimeError, match="缺少牛客登录凭据"):
        NowcoderSource().fetch_contest(None, "7")


def test_source_rejects_non_numeric_contest_id():
    source = NowcoderSource({"cookie": "SYNTHETIC_COOKIE"}, opener=FakeOpener([]))
    with pytest.raises(ValueError, match="比赛 ID"):
        source.fetch_contest(None, "not-an-id")


def test_source_supports_after_phase_without_mixing_contest_submissions(monkeypatch):
    info = {"data": {"sourceId": 7, "name": "Synthetic", "startTime": 100, "endTime": 200}}
    rank = {
        "data": {
            "problemData": [{"problemId": "p1", "index": "A", "title": "Demo", "score": 100}],
            "submitDataList": [{"signUpUsers": [], "submissions": []}],
        }
    }
    status = {
        "data": {
            "basicInfo": {"pageCount": 1},
            "data": [
                {
                    "userId": 12,
                    "userName": "Synthetic After",
                    "index": "A",
                    "submissionId": 22,
                    "submitTime": 250,
                }
            ],
        }
    }
    page = '<pre class="prettyprint lang-python">print(1)</pre><div class="coder-cont-legend">语言：Python<br>运行状态：<b>Accepted</b><br>得分：<b>100</b></div>'
    opener = FakeOpener([json.dumps(info), json.dumps(rank), json.dumps(status), page])
    source = NowcoderSource({"cookie": "SYNTHETIC_COOKIE", "phase": "after"}, opener=opener)
    bundle = source.fetch_contest(None, "7")
    assert len(bundle.submissions) == 1
    assert bundle.submissions[0].phase == "after"
    assert bundle.submissions[0].uid == "12"
    assert bundle.submissions[0].language == "python"
