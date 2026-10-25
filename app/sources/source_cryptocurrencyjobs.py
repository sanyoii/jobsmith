"""cryptocurrencyjobs.co：Web3/加密貨幣職缺站，前端由 Algolia 代管搜尋索引，
直接打 Algolia 官方 REST API（`/1/indexes/jobs/query`）取結果，不需爬 HTML。

部分欄位（如 company.url）在無資料時是 `False` 而非 null/空字典，逐一用 isinstance 防呆。
"""
from __future__ import annotations

from urllib.parse import quote_plus

from app.models import JobPosting, SearchResult
from app.sources.base import http_post

NAME = "cryptocurrencyjobs"
SEARCHABLE = True
_API = "https://8EHCB38Y1U-dsn.algolia.net/1/indexes/jobs/query"
_HEADERS = {
    "X-Algolia-API-Key": "e3deada9c15551e6363ee91e7e7d59cc",
    "X-Algolia-Application-Id": "8EHCB38Y1U",
    "Referer": "https://cryptocurrencyjobs.co/",
    "Content-Type": "application/json",
}
_BASE = "https://cryptocurrencyjobs.co"


def _work_mode(hit: dict) -> str | None:
    remote_location = hit.get("remoteLocation")
    location_filter = hit.get("locationFilter") or []
    if isinstance(remote_location, dict) and remote_location:
        return "remote"
    if isinstance(location_filter, list) and any(
        isinstance(f, str) and f.lower() == "remote" for f in location_filter
    ):
        return "remote"
    return None


def _location(hit: dict) -> str | None:
    remote_location = hit.get("remoteLocation")
    if isinstance(remote_location, dict) and remote_location.get("name"):
        return remote_location["name"]
    onsite_location = hit.get("onsiteLocation")
    if isinstance(onsite_location, str) and onsite_location:
        return onsite_location
    return None


def _snippet(hit: dict) -> str | None:
    parts: list[str] = []
    role = hit.get("role")
    if isinstance(role, dict) and role.get("name"):
        parts.append(role["name"])
    employment_types = hit.get("employmentTypes") or []
    if isinstance(employment_types, list):
        parts.extend(
            t["name"] for t in employment_types if isinstance(t, dict) and t.get("name")
        )
    return ", ".join(parts) or None


def search(keywords: str, limit: int = 15, pages: int = 1,
           area: list[str] | None = None) -> SearchResult:
    """搜尋 cryptocurrencyjobs.co；Algolia 單次查詢即回滿版結果，不需逐頁翻頁。

    area：保留參數，本來源不支援來源端地區篩選（多為 remote 職缺，地區意義不大）。
    """
    hits_per_page = limit * max(1, pages)
    params = f"query={quote_plus(keywords)}&hitsPerPage={hits_per_page}"
    try:
        r = http_post(_API, json={"params": params}, headers=_HEADERS)
        if not r.ok:
            return SearchResult(source=NAME, blocked=True, error=f"HTTP {r.status_code}")
        hits = r.json().get("hits") or []
    except Exception as e:  # 連線/解析錯誤 → 降級
        return SearchResult(source=NAME, blocked=True, error=str(e)[:150])

    jobs: list[JobPosting] = []
    seen: set[str] = set()
    for hit in hits:
        title = hit.get("title") or ""
        permalink = hit.get("permalink") or ""
        if not title or not permalink:
            continue
        url = _BASE + permalink
        if url in seen:
            continue
        seen.add(url)
        company = hit.get("company")
        company_name = company.get("name") if isinstance(company, dict) else None
        jobs.append(JobPosting(
            source=NAME,
            title=title,
            company=company_name or "",
            location=_location(hit),
            salary=None,
            url=url,
            snippet=_snippet(hit),
            requirements=[],
            work_mode=_work_mode(hit),
        ))
    return SearchResult(source=NAME, jobs=jobs)
