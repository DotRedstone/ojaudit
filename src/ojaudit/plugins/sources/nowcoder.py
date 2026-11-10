"""
Module: Source / nowcoder
Description: 只读采集牛客 ACM 比赛信息、报名用户与提交代码。
Scope: Source
Notes:
- Cookie 仅从显式配置值或指定环境变量读取，不写数据库、不写日志。
- 只发起 GET 请求；不执行账号写操作，返回核心标准数据对象。
"""

from __future__ import annotations

import gzip
import html
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from ojaudit.core.schema import Contest, Participant, Problem, Submission, language_bucket

BASE_URL = "https://ac.nowcoder.com"
USER_AGENT = "ojaudit/0.1 (+read-only contest import)"


class _Retryable(Exception):
    """可重试的 HTTP 状态（429 限流、5xx 服务器错误）。"""

    def __init__(self, status: int, retry_after: float | None) -> None:
        super().__init__(status)
        self.status = status
        self.retry_after = retry_after


class _RateLimiter:
    """所有线程共享的请求速率上限；rate 为每秒请求数，0 表示不限。"""

    def __init__(self, rate: float) -> None:
        self.interval = 1.0 / rate if rate > 0 else 0.0
        self.next_time = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_time)
            self.next_time = start + self.interval
        if start > now:
            time.sleep(start - now)


@dataclass(frozen=True, slots=True)
class NowcoderBundle:
    contest: Contest
    problems: tuple[Problem, ...]
    participants: tuple[Participant, ...]
    submissions: tuple[Submission, ...]


def _code_from_html(page: str) -> tuple[str, str, str, float]:
    match = re.search(r'<pre[^>]*class="prettyprint[^"]*"[^>]*>([\s\S]*?)</pre>', page)
    code = html.unescape(match.group(1)).strip() if match else ""
    legend_match = re.search(r'<div class="coder-cont-legend">([\s\S]*?)</div>', page)
    legend = legend_match.group(1) if legend_match else ""

    def pick(pattern: str) -> str:
        found = re.search(pattern, legend)
        return found.group(1).strip() if found else ""

    language = pick(r"语言[:：]\s*([^<>\n]+)")
    verdict = pick(r"运行状态[:：]\s*<[^>]*>\s*([^<>\n]+)")
    score_text = pick(r"得分[:：]\s*<[^>]*>\s*([\d.]+)")
    try:
        score = float(score_text) if score_text else 0.0
    except ValueError:
        score = 0.0
    return code, language, verdict or "未知", score


class NowcoderSource:
    """通过配置/环境变量读取凭据；不接受命令行 Cookie 参数。"""

    def __init__(self, config: dict[str, Any] | None = None, opener: Any = None):
        self.config = config or {}
        self.base = str(self.config.get("base_url", BASE_URL)).rstrip("/")
        # 注入 opener 时（测试）逐次请求；否则每个线程复用自己的 HTTPS 长连接。
        self.opener = opener
        self._local = threading.local()
        self._limiter = _RateLimiter(float(self.config.get("rate_limit", 0) or 0))

    def _cookie(self) -> str:
        direct = self.config.get("cookie")
        env_name = str(self.config.get("cookie_env", "NOWCODER_COOKIE"))
        value = str(direct or os.environ.get(env_name, "")).strip()
        if not value:
            raise RuntimeError("缺少牛客登录凭据：请配置 cookie 或设置对应环境变量")
        return value

    def _get(self, url: str, cookie: str) -> str:
        retries = self.config.get("retry_count", 2)
        if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 10:
            raise ValueError("retry_count 必须为 0–10 的整数")
        timeout = float(self.config.get("timeout", 20))
        headers = {"Cookie": cookie, "User-Agent": USER_AGENT, "Accept": "*/*"}
        for attempt in range(retries + 1):
            self._limiter.wait()
            try:
                if self.opener is not None:
                    request = urllib.request.Request(url, headers=headers)
                    return self.opener(request, timeout=timeout).read().decode("utf-8", "replace")
                return self._keepalive(url, headers, timeout)
            except _Retryable as exc:
                if attempt == retries:
                    raise RuntimeError(f"牛客只读请求失败：HTTP {exc.status}") from None
                time.sleep(exc.retry_after or min(0.5 * 2**attempt, 8))
            except (OSError, TimeoutError, http.client.HTTPException) as exc:
                if attempt == retries:
                    raise RuntimeError(f"牛客只读请求失败：{type(exc).__name__}") from None
                time.sleep(min(0.5 * 2**attempt, 8))
        raise RuntimeError("牛客只读请求失败")

    def _keepalive(self, url: str, headers: dict[str, str], timeout: float) -> str:
        """每个线程一条长连接，省去每个请求的 TCP 与 TLS 握手（实测速度约翻倍）。"""
        parts = urllib.parse.urlsplit(url)
        connections = self._local.__dict__.setdefault("connections", {})
        key = (parts.scheme, parts.netloc)
        connection = connections.get(key)
        if connection is None:
            factory = (
                http.client.HTTPSConnection
                if parts.scheme == "https"
                else http.client.HTTPConnection
            )
            connection = connections[key] = factory(parts.netloc, timeout=timeout)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        try:
            connection.request(
                "GET",
                path,
                headers={**headers, "Connection": "keep-alive", "Accept-Encoding": "gzip"},
            )
            response = connection.getresponse()
            body = response.read()
        except (OSError, http.client.HTTPException):
            connection.close()
            connections.pop(key, None)
            raise
        if response.will_close:
            connection.close()
            connections.pop(key, None)
        if response.status in (301, 302, 303, 307, 308):
            # 少见的跳转（例如登录失效跳到登录页）交给 urllib 处理。
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as fallback:
                return fallback.read().decode("utf-8", "replace")
        if response.status == 429 or response.status >= 500:
            retry_after = response.getheader("Retry-After") or ""
            raise _Retryable(response.status, float(retry_after) if retry_after.isdigit() else None)
        if response.status >= 400:
            raise RuntimeError(f"牛客只读请求失败：HTTP {response.status}")
        if response.getheader("Content-Encoding", "") == "gzip":
            body = gzip.decompress(body)
        return body.decode("utf-8", "replace")

    def _json(self, url: str, cookie: str) -> dict[str, Any]:
        try:
            value = json.loads(self._get(url, cookie).lstrip("\ufeff"))
        except (json.JSONDecodeError, TypeError):
            raise ValueError("牛客接口返回了无效 JSON") from None
        if not isinstance(value, dict):
            raise TypeError("牛客接口返回结构无效")
        return value

    def detect_uid(self) -> str:
        """从当前登录态读取自己的牛客 UID（ac.nowcoder.com 首页中的个人主页链接）。"""
        page = self._get(f"{self.base}/", self._cookie())
        match = re.search(r"/acm/contest/profile/(\d+)", page)
        if match is None:
            raise RuntimeError("无法从登录态识别牛客 UID：Cookie 可能已失效")
        return match.group(1)

    def list_joined(self, uid: str | None = None, max_pages: int = 50) -> list[dict[str, Any]]:
        """列出该用户参加过且已结束的全部比赛（自动翻页）。"""
        user_id = str(uid or self.config.get("uid") or os.environ.get("NOWCODER_UID", ""))
        if not user_id:
            user_id = self.detect_uid()
        if not user_id.isdigit():
            raise ValueError("牛客 UID 必须是数字")
        cookie = self._cookie()
        result: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            query = urllib.parse.urlencode(
                {
                    "uid": user_id,
                    "page": page,
                    "pageSize": 30,
                    "onlyJoinedFilter": "true",
                    "searchContestName": "",
                    "onlyRatingFilter": "false",
                    "contestEndFilter": "true",
                }
            )
            payload = self._json(
                f"{self.base}/acm-heavy/acm/contest/profile/contest-joined-history?{query}",
                cookie,
            )
            data = payload.get("data") or {}
            rows = data.get("dataList") or []
            for row in rows:
                if not str(row.get("contestId", "")).isdigit():
                    continue
                result.append(
                    {
                        "contest_id": str(row["contestId"]),
                        "name": html.unescape(str(row.get("contestName") or row["contestId"])),
                        "start_time": row.get("startTime"),
                        "end_time": row.get("endTime"),
                    }
                )
            info = data.get("pageInfo") or {}
            total = info.get("totalCount") if isinstance(info, dict) else None
            if not rows or (isinstance(total, int) and len(result) >= total):
                break
        return result

    list_recent = list_joined

    def _fetch_after_submissions(self, contest_id: str, cookie: str) -> list[dict[str, Any]]:
        collected = []
        first_url = f"{self.base}/acm/contest/status-list?token=&id={contest_id}&page=1&pageSize=50"
        first = self._json(first_url, cookie).get("data") or {}
        basic = first.get("basicInfo") or {}
        try:
            page_count = max(1, min(int(basic.get("pageCount") or 1), 1000))
        except (TypeError, ValueError):
            page_count = 1
        collected.extend(first.get("data") or [])
        for page in range(2, page_count + 1):
            url = f"{self.base}/acm/contest/status-list?token=&id={contest_id}&page={page}&pageSize=50"
            payload = self._json(url, cookie).get("data") or {}
            collected.extend(payload.get("data") or [])
        return collected

    def fetch_contest(
        self,
        session: Any,
        contest_id: str,
        *,
        progress: Callable[[str, int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        known: dict[str, tuple[str, str, str, float]] | None = None,
    ) -> NowcoderBundle:
        """progress(阶段, 已完成, 总数) 报告进度；cancelled() 返回 True 时尽快停止并抛出
        InterruptedError（正在进行的单个请求会先完成）。known 为本地已有提交的
        {提交 ID: (代码, 语言, 结果, 得分)}，这些提交不再下载源码（增量采集）。"""
        del session  # 网络会话由本插件的只读 opener 管理。
        report = progress or (lambda _stage, _done, _total: None)
        stop = cancelled or (lambda: False)

        def check() -> None:
            if stop():
                raise InterruptedError("采集已取消")

        if not str(contest_id).isdigit():
            raise ValueError("牛客比赛 ID 必须为数字字符串")
        if self.config.get("readonly", True) is not True:
            raise ValueError("牛客数据源仅支持只读采集，请启用 collect.readonly")
        cookie = self._cookie()
        threads = self.config.get("threads", 8)
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 32:
            raise ValueError("threads 必须为 1–32 的整数")
        phase = str(self.config.get("phase", "contest"))
        if phase not in {"contest", "after", "all"}:
            raise ValueError("phase 仅支持 contest、after、all")
        report("读取比赛信息", 0, 0)
        info = (
            self._json(
                f"{self.base}/acm/contest/contest-info?{urllib.parse.urlencode({'id': contest_id})}",
                cookie,
            ).get("data")
            or {}
        )
        rank_query = urllib.parse.urlencode(
            {
                "currentContestId": contest_id,
                "contestList": contest_id,
                "rankScope": "ALL",
            }
        )
        check()
        report("读取榜单", 0, 0)
        rank_data = (
            self._json(
                f"{self.base}/acm/contest/rank/submit-list?{rank_query}",
                cookie,
            ).get("data")
            or {}
        )
        problems_raw = rank_data.get("problemData") or []
        submit_groups = rank_data.get("submitDataList") or [{}]
        group = submit_groups[0] if submit_groups else {}
        signup = group.get("signUpUsers") or []
        rank_submissions = group.get("submissions") or []

        contest = Contest(
            platform="nowcoder",
            contest_id=str(info.get("sourceId") or contest_id),
            name=html.unescape(str(info.get("name") or contest_id)),
            start_time=info.get("startTime"),
            end_time=info.get("endTime"),
            raw_meta={"description": str(info.get("description") or "")},
        )
        problem_by_id: dict[str, Problem] = {}
        problem_by_label: dict[str, Problem] = {}
        problems = []
        for raw in problems_raw:
            problem_id = str(raw.get("problemId", ""))
            label = str(raw.get("index", len(problems)))
            try:
                index = int(label)
            except (TypeError, ValueError):
                index = len(problems)
            problem = Problem(
                platform="nowcoder",
                contest_id=contest.contest_id,
                index=index,
                problem_id=problem_id,
                title=html.unescape(str(raw.get("title") or "")),
                full_score=float(raw.get("score") or 0),
            )
            problems.append(problem)
            problem_by_id[problem_id] = problem
            problem_by_label[label] = problem

        participants = tuple(
            Participant(
                platform="nowcoder",
                contest_id=contest.contest_id,
                uid=str(row.get("uid", "")),
                name=html.unescape(str(row.get("name") or "")),
            )
            for row in signup
            if row.get("uid") is not None
        )
        names = {str(row.get("uid")): html.unescape(str(row.get("name") or "")) for row in signup}
        selected: list[tuple[dict[str, Any], Problem, str]] = []
        if phase in {"contest", "all"}:
            for raw in rank_submissions:
                problem = problem_by_id.get(str(raw.get("problemId") or ""))
                if problem is not None:
                    selected.append((raw, problem, "contest"))
        if phase in {"after", "all"}:
            check()
            report("读取赛后提交", 0, 0)
            for raw in self._fetch_after_submissions(contest_id, cookie):
                try:
                    stamp = int(raw.get("submitTime") or 0)
                except (TypeError, ValueError):
                    stamp = 0
                if contest.end_time is None or stamp <= int(contest.end_time):
                    continue
                problem = problem_by_label.get(str(raw.get("index") or ""))
                if problem is not None:
                    selected.append(
                        (
                            {
                                "uid": raw.get("userId"),
                                "submissionId": raw.get("submissionId"),
                                "submitTime": stamp,
                            },
                            problem,
                            "after",
                        )
                    )

        # 并发选项仅作用于独立的 GET 源码请求；原有提交顺序不变。
        def read_code(item: tuple[dict[str, Any], Problem, str]) -> tuple[str, str, str, float]:
            raw, _problem, _phase = item
            check()  # 已取消时，排队中的下载在发出请求前就放弃
            submission_id = str(raw.get("submissionId") or "")
            if not submission_id:
                return "", "", "", 0.0
            if known and submission_id in known:
                return known[submission_id]
            url = (
                f"{self.base}/acm/contest/view-submission?"
                f"{urllib.parse.urlencode({'submissionId': submission_id})}"
            )
            return _code_from_html(self._get(url, cookie))

        # 本地已有源码的提交直接复用，只下载新的提交。
        reused = {
            i
            for i, (raw, _p, _ph) in enumerate(selected)
            if known and str(raw.get("submissionId") or "") in known
        }
        codes: list[tuple[str, str, str, float]] = [("", "", "", 0.0)] * len(selected)
        for i in reused:
            codes[i] = known[str(selected[i][0].get("submissionId"))]  # type: ignore[index]
        pending = [i for i in range(len(selected)) if i not in reused]
        total = len(pending)
        stage = f"下载源码（已有 {len(reused)} 份跳过）" if reused else "下载源码"
        report(stage, 0, total)
        if threads > 1 and total > 1:
            executor = ThreadPoolExecutor(max_workers=threads)
            try:
                futures = {executor.submit(read_code, selected[i]): i for i in pending}
                for done, future in enumerate(as_completed(futures), 1):
                    codes[futures[future]] = future.result()
                    report(stage, done, total)
                    check()
            finally:
                # 取消或出错时丢弃尚未开始的请求，不让后台线程继续跑完全部源码。
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            for done, i in enumerate(pending, 1):
                check()
                codes[i] = read_code(selected[i])
                report(stage, done, total)
        submissions = []
        seen = set()
        for (raw, problem, submission_phase), parsed in zip(selected, codes):
            submission_id = str(raw.get("submissionId") or "")
            uid = str(raw.get("uid") or "")
            if not submission_id or not uid or submission_id in seen:
                continue
            seen.add(submission_id)
            code, language_text, verdict, score = parsed
            try:
                submit_time = int(raw.get("submitTime") or 0)
            except (TypeError, ValueError):
                submit_time = 0
            if raw.get("status") == 5 and not score:
                score = float(problem.full_score or 0)
            submissions.append(
                Submission(
                    platform="nowcoder",
                    contest_id=contest.contest_id,
                    submission_id=submission_id,
                    uid=uid,
                    problem_index=problem.index,
                    language=language_bucket(language_text),
                    verdict=verdict,
                    score=score,
                    submit_time=submit_time,
                    phase=submission_phase,
                    code=code,
                    raw_meta={
                        "participant_name": names.get(uid, ""),
                        "problem_id": problem.problem_id,
                    },
                )
            )
        return NowcoderBundle(
            contest=contest,
            problems=tuple(sorted(problems, key=lambda item: item.index)),
            participants=tuple(sorted(participants, key=lambda item: item.uid)),
            submissions=tuple(
                sorted(
                    submissions,
                    key=lambda item: (
                        item.uid,
                        item.problem_index,
                        item.submit_time,
                        item.submission_id,
                    ),
                )
            ),
        )
