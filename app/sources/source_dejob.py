"""dejob.ai：Web3 遠端招聘平台。純 CSR SPA，網頁本身不可爬；改打其 JSON API
`/api/worker/topics`（`worker` = 平台對「職缺貼文」的稱呼），`keyword` 為關鍵字過濾參數
（經實測確認：帶入才會真的縮小 total 筆數，其餘常見參數名如 q/search/name 皆被忽略）。
"""
from __future__ import annotations

from urllib.parse import quote

from app.models import JobPosting, SearchResult
from app.sources.base import clean, http_get

NAME = "dejob"
SEARCHABLE = True
_API = "https://dejob.ai/api/worker/topics?page={page}&limit={limit}&keyword={kw}"


def _format_salary(d: dict) -> str | None:
    lo = d.get("minSalary") or 0
    hi = d.get("maxSalary") or 0
    if not lo and not hi:
        return None
    if lo and hi and lo != hi:
        return f"${lo:,}–{hi:,}"
    return f"${(hi or lo):,}"


_WORK_MODE = {"On-site": "onsite", "Remote": "remote", "Remote/On-site": "hybrid"}


def _work_mode(d: dict) -> str | None:
    return _WORK_MODE.get(d.get("officeModeName"))


def search(keywords: str, limit: int = 15, pages: int = 1,
           area: list[str] | None = None) -> SearchResult:
    """搜尋 dejob；pages>1 時逐頁抓取（API 吃 page 參數）並跨頁去重。

    area：保留參數，本來源不支援來源端地區篩選（多為 remote 職缺，地區意義不大）。
    """
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    for page in range(1, max(1, pages) + 1):
        try:
            r = http_get(_API.format(page=page, limit=limit, kw=quote(keywords)))
            if not r.ok:
                if page == 1:
                    return SearchResult(source=NAME, blocked=True, error=f"HTTP {r.status_code}")
                break
            results = (r.json().get("data") or {}).get("results") or []
        except Exception as e:  # 連線/解析錯誤 → 降級
            if page == 1:
                return SearchResult(source=NAME, blocked=True, error=str(e)[:150])
            break
        if not results:
            break  # 沒有更多職缺，提早停止翻頁
        for d in results:
            url = d.get("url") or ""
            title = d.get("positionName") or ""
            if not url or not title or url in seen:
                continue
            seen.add(url)
            location = d.get("location") or d.get("base") or d.get("officeModeName") or None
            tags = d.get("tags") or []
            jobs.append(JobPosting(
                source=NAME,
                title=clean(title),
                company=clean(d.get("company") or ""),
                location=clean(location) or None,
                salary=_format_salary(d),
                url=url,
                snippet=clean((d.get("content") or "")[:200]) or None,
                requirements=[clean(t.get("tagName", "")) for t in tags if isinstance(t, dict)][:10],
                work_mode=_work_mode(d),
            ))
    if not jobs:
        return SearchResult(source=NAME, blocked=True, error="解析不到職缺")
    return SearchResult(source=NAME, jobs=jobs)
