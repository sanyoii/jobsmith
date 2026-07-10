"""cryptojobslist.com：解析搜尋頁 __NEXT_DATA__ 的 pageProps.jobs（Next.js SSR，同 cake 套路）。

搜尋端點 `/search?q=kw&page=N`；實測 page 參數對此站無效（永遠回第一批結果），
故 pages>1 時第二頁會與第一頁完全重複、跨頁去重後不新增，迴圈自然提早停止。
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from app.models import JobPosting, SearchResult
from app.sources.base import clean, http_get

NAME = "cryptojobslist"
SEARCHABLE = True
_SEARCH = "https://cryptojobslist.com/search?q={kw}&page={page}"
_BASE = "https://cryptojobslist.com/jobs/"
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def search(keywords: str, limit: int = 15, pages: int = 1,
           area: list[str] | None = None) -> SearchResult:
    """搜尋 cryptojobslist；pages>1 時逐頁抓取並跨頁去重（見上方 page 參數限制）。

    area：保留參數，本來源不支援來源端地區篩選（多為 remote 職缺，地區意義不大）。
    """
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    cap = limit * max(1, pages)
    first_error = None
    for page in range(1, max(1, pages) + 1):
        try:
            r = http_get(_SEARCH.format(kw=quote(keywords), page=page))
            if not r.ok:
                first_error = f"HTTP {r.status_code}"
                break
            m = _NEXT.search(r.text)
            if not m:
                first_error = "找不到 __NEXT_DATA__"
                break
            data = json.loads(m.group(1))
            raw_jobs = data.get("props", {}).get("pageProps", {}).get("jobs") or []
        except Exception as e:
            first_error = str(e)[:150]
            break

        before = len(jobs)
        for d in raw_jobs:
            if not isinstance(d, dict):
                continue
            slug = d.get("seoSlug")
            title = d.get("jobTitle")
            if not slug or not title:
                continue
            url = _BASE + slug
            if url in seen:
                continue
            seen.add(url)
            tags = d.get("tags") or []
            work_mode = "remote" if d.get("remote") is True else None
            jobs.append(JobPosting(
                source=NAME,
                title=clean(title),
                company=clean(d.get("companyName") or ""),
                location=clean(d.get("jobLocation")) or None,
                salary=d.get("salaryString") or None,
                url=url,
                snippet=None,
                requirements=[str(t) for t in tags][:10] if isinstance(tags, list) else [],
                work_mode=work_mode,
            ))
            if len(jobs) >= cap:
                break
        if len(jobs) >= cap or len(jobs) - before == 0:
            break  # 已達上限，或這一頁沒有新職缺 → 停止翻頁
    if not jobs:
        return SearchResult(source=NAME, blocked=True, error=first_error or "解析不到職缺")
    return SearchResult(source=NAME, jobs=jobs)
