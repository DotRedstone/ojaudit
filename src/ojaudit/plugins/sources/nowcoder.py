"""
Module: Source / nowcoder
Description: 只读采集牛客 ACM 比赛信息、报名用户与提交代码。
Scope: Source
Notes:
- Cookie 仅从显式配置值或指定环境变量读取，不写数据库、不写日志。
- 只发起 GET 请求；不执行账号写操作，返回核心标准数据对象。
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from ojaudit.core.schema import Contest, Participant, Problem, Submission, language_bucket

BASE_URL = "https://ac.nowcoder.com"
USER_AGENT = "ojaudit/0.1 (+read-only contest import)"


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
        self.opener = opener or urllib.request.urlopen

    def _cookie(self) -> str:
        direct = self.config.get("cookie")
        env_name = str(self.config.get("cookie_env", "NOWCODER_COOKIE"))
        value = str(direct or os.environ.get(env_name, "")).strip()
        if not value:
            raise RuntimeError("缺少牛客登录凭据：请配置 cookie 或设置对应环境变量")
        return value

    def _get(self, url: str, cookie: str) -> str:
        request = urllib.request.Request(
            url,
            headers={"Cookie": cookie, "User-Agent": USER_AGENT, "Accept": "*/*"},
        )
        retries = self.config.get("retry_count", 2)
        if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 10:
            raise ValueError("retry_count 必须为 0–10 的整数")
        for attempt in range(retries + 1):
            try:
                response = self.opener(request, timeout=40)
                return response.read().decode("utf-8", "replace")
            except (OSError, TimeoutError) as exc:
                if attempt == retries:
                    raise RuntimeError(f"牛客只读请求失败：{type(exc).__name__}") from None
        raise RuntimeError("牛客只读请求失败")

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
        page = self._get(f"{BASE_URL}/", self._cookie())
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
                f"{BASE_URL}/acm-heavy/acm/contest/profile/contest-joined-history?{query}",
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
                        "name": str(row.get("contestName") or row["contestId"]),
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
        first_url = f"{BASE_URL}/acm/contest/status-list?token=&id={contest_id}&page=1&pageSize=50"
        first = self._json(first_url, cookie).get("data") or {}
        basic = first.get("basicInfo") or {}
        try:
            page_count = max(1, min(int(basic.get("pageCount") or 1), 1000))
        except (TypeError, ValueError):
            page_count = 1
        collected.extend(first.get("data") or [])
        for page in range(2, page_count + 1):
            url = (
                f"{BASE_URL}/acm/contest/status-list?token=&id={contest_id}&page={page}&pageSize=50"
            )
            payload = self._json(url, cookie).get("data") or {}
            collected.extend(payload.get("data") or [])
        return collected

    def fetch_contest(self, session: Any, contest_id: str) -> NowcoderBundle:
        del session  # 网络会话由本插件的只读 opener 管理。
        if not str(contest_id).isdigit():
            raise ValueError("牛客比赛 ID 必须为数字字符串")
        if self.config.get("readonly", True) is not True:
            raise ValueError("牛客数据源仅支持只读采集，请启用 collect.readonly")
        cookie = self._cookie()
        threads = self.config.get("threads", 1)
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 16:
            raise ValueError("threads 必须为 1–16 的整数")
        phase = str(self.config.get("phase", "contest"))
        if phase not in {"contest", "after", "all"}:
            raise ValueError("phase 仅支持 contest、after、all")
        info = (
            self._json(
                f"{BASE_URL}/acm/contest/contest-info?{urllib.parse.urlencode({'id': contest_id})}",
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
        rank_data = (
            self._json(
                f"{BASE_URL}/acm/contest/rank/submit-list?{rank_query}",
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
            name=str(info.get("name") or contest_id),
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
                title=str(raw.get("title") or ""),
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
                name=str(row.get("name") or ""),
            )
            for row in signup
            if row.get("uid") is not None
        )
        names = {str(row.get("uid")): str(row.get("name") or "") for row in signup}
        selected: list[tuple[dict[str, Any], Problem, str]] = []
        if phase in {"contest", "all"}:
            for raw in rank_submissions:
                problem = problem_by_id.get(str(raw.get("problemId") or ""))
                if problem is not None:
                    selected.append((raw, problem, "contest"))
        if phase in {"after", "all"}:
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
            submission_id = str(raw.get("submissionId") or "")
            if not submission_id:
                return "", "", "", 0.0
            url = (
                f"{BASE_URL}/acm/contest/view-submission?"
                f"{urllib.parse.urlencode({'submissionId': submission_id})}"
            )
            return _code_from_html(self._get(url, cookie))

        if threads > 1 and len(selected) > 1:
            with ThreadPoolExecutor(max_workers=threads) as executor:
                codes = list(executor.map(read_code, selected))
        else:
            codes = [read_code(item) for item in selected]
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
