"""web3.career：伺服器端渲染的職缺列表頁（純 HTML table，無需 JS/API）。

搜尋頁 `/?search=kw&page=N` 直接把職缺塞進 `<tr data-jobid=...>`，桌面/行動版各渲染一份
（同 job id 出現兩次），靠 url 去重即可。個人低頻使用、被擋即降級。
"""
from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from app.models import JobPosting, SearchResult
from app.sources.base import clean, http_get

NAME = "web3career"
SEARCHABLE = True
_PAGE = "https://web3.career/?search={kw}&page={page}"
_BASE = "https://web3.career"


def search(keywords: str, limit: int = 15, pages: int = 1,
           area: list[str] | None = None) -> SearchResult:
    """搜尋 web3.career；pages>1 時逐頁抓取（網址帶 page 參數）並跨頁去重。

    area：保留參數，本來源不支援來源端地區篩選（多為 remote 職缺，地區意義不大）。
    """
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    cap = limit * max(1, pages)
    for page in range(1, max(1, pages) + 1):
        try:
            r = http_get(_PAGE.format(kw=quote(keywords), page=page))
            if not r.ok:
                if page == 1:
                    return SearchResult(source=NAME, blocked=True, error=f"HTTP {r.status_code}")
                break
        except Exception as e:  # 連線錯誤 → 降級
            if page == 1:
                return SearchResult(source=NAME, blocked=True, error=str(e)[:150])
            break

        soup = BeautifulSoup(r.text, "html.parser")
        before = len(jobs)
        for row in soup.select("tr[data-jobid]"):
            title_el = row.select_one("h2")
            link_el = row.select_one("a[href]")
            if not title_el or not link_el:
                continue
            url = _BASE + link_el["href"] if link_el["href"].startswith("/") else link_el["href"]
            if url in seen:
                continue
            seen.add(url)
            loc_tds = row.select("td.job-location-mobile")
            company_el = loc_tds[0].select_one("h3") if loc_tds else None
            location_td = loc_tds[1] if len(loc_tds) > 1 else None
            location = (re.sub(r"\s*,\s*", ", ", location_td.get_text(" ", strip=True))
                        if location_td else None)
            salary_el = row.select_one("p.text-salary")
            tags = [clean(a.get_text(strip=True)) for a in row.select("a.text-shadow-1px")]
            work_mode = "remote" if location and "remote" in location.lower() else None
            jobs.append(JobPosting(
                source=NAME,
                title=clean(title_el.get_text(strip=True)),
                company=clean(company_el.get_text(strip=True)) if company_el else "",
                location=clean(location) or None,
                salary=clean(salary_el.get_text(strip=True)) if salary_el and salary_el.get_text(strip=True) else None,
                url=url,
                snippet=None,
                requirements=[t for t in tags if t],
                work_mode=work_mode,
            ))
            if len(jobs) >= cap:
                break
        if len(jobs) >= cap or len(jobs) - before == 0:
            break  # 已達上限，或這一頁沒有新職缺 → 停止翻頁
    if not jobs:
        return SearchResult(source=NAME, blocked=True, error="解析不到職缺")
    return SearchResult(source=NAME, jobs=jobs)
