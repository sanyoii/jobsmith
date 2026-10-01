"""defi.jobs：DeFi 職缺列表頁，Webflow CMS 渲染的靜態 HTML（`.w-dyn-item`），單頁列出全部
職缺、無伺服器端搜尋參數 → 抓下整頁後在本地依關鍵字過濾標題/公司/職務類型。
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from app.models import JobPosting, SearchResult
from app.sources.base import clean, http_get

NAME = "defijobs"
SEARCHABLE = True
_PAGE = "https://www.defi.jobs/"
_BASE = "https://www.defi.jobs"


def _tokens(keywords: str) -> list[str]:
    return [t.lower() for t in keywords.split() if t.strip()]


def _matches(tokens: list[str], *texts: str) -> bool:
    if not tokens:
        return True
    blob = " ".join(t.lower() for t in texts if t)
    return all(re.search(r"(?<!\w)" + re.escape(tok) + r"(?!\w)", blob) for tok in tokens)


def search(keywords: str | list[str], limit: int = 15, pages: int = 1,
           area: list[str] | None = None) -> SearchResult:
    """搜尋 defi.jobs；單頁列出全部職缺，keywords 在本地過濾（無伺服器端搜尋參數）。

    pages：保留參數，本來源只有單頁列表，不支援翻頁。
    area：保留參數，本來源不支援來源端地區篩選（多為 remote 職缺，地區意義不大）。
    """
    try:
        r = http_get(_PAGE)
        if not r.ok:
            return SearchResult(source=NAME, blocked=True, error=f"HTTP {r.status_code}")
    except Exception as e:  # 連線錯誤 → 降級
        return SearchResult(source=NAME, blocked=True, error=str(e)[:150])

    soup = BeautifulSoup(r.text, "html.parser")
    items = soup.select(".w-dyn-item")
    if not items:
        return SearchResult(source=NAME, blocked=True, error="解析不到職缺")

    phrases = [_tokens(q) for q in (keywords if isinstance(keywords, list) else [keywords])]
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    for item in items:
        if len(jobs) >= limit:
            break
        link_el = item.select_one("a.job-link[href]")
        title_el = item.select_one(".j-title")
        if not link_el or not title_el:
            continue
        href = link_el["href"]
        url = _BASE + href if href.startswith("/") else href
        if url in seen:
            continue
        title = clean(title_el.get_text(strip=True))
        company_el = item.select_one(".org")
        company = clean(company_el.get_text(strip=True)) if company_el else ""
        type_el = item.select_one(".type")
        emp_type = clean(type_el.get_text(strip=True)) if type_el else ""
        if not any(_matches(tokens, title) for tokens in phrases):
            continue
        seen.add(url)
        location_el = item.select_one(".location")
        location = clean(location_el.get_text(strip=True)) if location_el else ""
        salary_el = item.select_one(".salary")
        salary = clean(salary_el.get_text(strip=True)) if salary_el else ""
        work_mode = "remote" if location and "remote" in location.lower() else None
        jobs.append(JobPosting(
            source=NAME,
            title=title,
            company=company,
            location=location or None,
            salary=salary or None,
            url=url,
            snippet=emp_type or None,
            requirements=[],
            work_mode=work_mode,
        ))
    return SearchResult(source=NAME, jobs=jobs)
