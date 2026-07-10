"""job-frog.com（職缺青蛙）：外商科技公司在台職缺，官方 JSON API `/api/search`。

網頁本身是 Next.js RSC（無法直接爬 HTML），但同一 API 供前端「展開公司」用，
不需帶 companyExact 即可拿到跨公司的關鍵字搜尋結果（已實測確認）。
website_link 直接是各公司官網申請頁，無 104/cake 那種站內詳情頁。
"""
from __future__ import annotations

from urllib.parse import quote

from app.models import JobPosting, SearchResult
from app.sources.base import clean, http_get

NAME = "jobfrog"
SEARCHABLE = True
_API = "https://www.job-frog.com/api/search?q={kw}&page={page}&pageSize={size}"


def search(keywords: str, limit: int = 15, pages: int = 1,
           area: list[str] | None = None) -> SearchResult:
    """搜尋 job-frog；pages>1 時逐頁抓取（API 吃 page 參數）並跨頁去重。

    area：保留參數，本來源不支援來源端地區篩選（多為外商台灣據點，地區意義不大）。
    """
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    for page in range(1, max(1, pages) + 1):
        try:
            r = http_get(_API.format(kw=quote(keywords), page=page, size=limit))
            if not r.ok:
                if page == 1:
                    return SearchResult(source=NAME, blocked=True, error=f"HTTP {r.status_code}")
                break
            data = r.json().get("data") or []
        except Exception as e:  # 連線/解析錯誤 → 降級
            if page == 1:
                return SearchResult(source=NAME, blocked=True, error=str(e)[:150])
            break
        if not data:
            break  # 沒有更多職缺，提早停止翻頁
        for d in data:
            url = d.get("website_link") or ""
            title = d.get("title") or ""
            if not url or not title or url in seen:
                continue
            seen.add(url)
            tech = d.get("tech_stack") or []
            work_mode = "hybrid" if d.get("is_hybrid_remote") is True else None
            jobs.append(JobPosting(
                source=NAME,
                title=clean(title),
                company=clean(d.get("company") or ""),
                location=clean(d.get("location")) or None,
                salary=None,  # 外商職缺頁一律不揭露薪資
                url=url,
                snippet=clean(d.get("summary_zh_hq") or d.get("summary_zh") or "") or None,
                requirements=[str(t) for t in tech][:10] if isinstance(tech, list) else [],
                work_mode=work_mode,
            ))
    if not jobs:
        return SearchResult(source=NAME, blocked=True, error="解析不到職缺")
    return SearchResult(source=NAME, jobs=jobs)
