"""
Module: Test / nowcoder transport
Description: 用本地 HTTP 服务验证源码下载复用长连接、限流重试、gzip、速率上限与增量采集。
Scope: Test
Notes: 只连接 127.0.0.1 上的合成服务，不访问牛客。
"""

from __future__ import annotations

import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from ojaudit.plugins.sources.nowcoder import NowcoderSource


class Server:
    def __init__(self, submissions: int = 40) -> None:
        self.connections = 0
        self.code_requests: list[str] = []
        self.fail_once = {"3"}
        state = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self) -> None:
                super().setup()
                state.connections += 1

            def log_message(self, *_args) -> None:
                pass

            def send_body(self, body: bytes, status: int = 200, zipped: bool = False) -> None:
                if zipped:
                    body = gzip.compress(body)
                self.send_response(status)
                if zipped:
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                url = urlsplit(self.path)
                if url.path.endswith("contest-info"):
                    self.send_body(json.dumps({"data": {"name": "合成赛"}}).encode())
                elif url.path.endswith("submit-list"):
                    subs = [
                        {"submissionId": str(i), "uid": "u", "problemId": "p", "submitTime": i}
                        for i in range(submissions)
                    ]
                    data = {
                        "problemData": [{"problemId": "p", "index": 0, "title": "A"}],
                        "submitDataList": [{"signUpUsers": [], "submissions": subs}],
                    }
                    self.send_body(json.dumps({"data": data}).encode())
                else:
                    sid = parse_qs(url.query)["submissionId"][0]
                    state.code_requests.append(sid)
                    if sid in state.fail_once:
                        state.fail_once.discard(sid)
                        self.send_body(b"busy", status=429)
                        return
                    page = f'<pre class="prettyprint">int x = {sid};</pre>'
                    self.send_body(page.encode(), zipped=True)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()


@pytest.fixture
def server():
    instance = Server()
    yield instance
    instance.close()


def source(server: Server, **config) -> NowcoderSource:
    return NowcoderSource({"cookie": "t=x", "base_url": server.url, "threads": 4, **config})


def test_keepalive_retry_and_gzip(server):
    bundle = source(server).fetch_contest(None, "1")
    assert len(bundle.submissions) == 40
    assert {s.code for s in bundle.submissions} >= {"int x = 0;", "int x = 3;"}
    assert server.code_requests.count("3") == 2, "429 后重试一次"
    assert server.connections <= 6, "每个线程复用一条连接，而不是每个请求一条"


def test_incremental_skips_known_codes(server):
    known = {str(i): (f"old {i}", "cpp", "AC", 100.0) for i in range(30)}
    seen = []
    bundle = source(server).fetch_contest(
        None, "1", known=known, progress=lambda *args: seen.append(args)
    )
    assert sorted(server.code_requests, key=int) == [str(i) for i in range(30, 40)]
    codes = {s.submission_id: s.code for s in bundle.submissions}
    assert codes["5"] == "old 5" and codes["35"] == "int x = 35;"
    assert any("已有 30 份跳过" in stage and total == 10 for stage, _, total in seen)


def test_rate_limit_spreads_requests(server):
    started = time.monotonic()
    source(server, rate_limit=100).fetch_contest(None, "1")
    # 42 次以上请求、每秒最多 100 次，至少需要约 0.4 秒。
    assert time.monotonic() - started >= 0.38


def test_thread_range_is_validated(server):
    with pytest.raises(ValueError, match="1–32"):
        source(server, threads=64).fetch_contest(None, "1")
