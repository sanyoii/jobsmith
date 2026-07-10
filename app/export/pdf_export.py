"""投遞包 → PDF：Jinja2 渲染 HTML 模板，Playwright Chromium 列印成 A4 PDF。

pkg 形狀與 docx_export.build_docx 相同（皆為選填）。
產出 {"resume.pdf": bytes, "cover_letter.pdf": bytes}；缺對應區塊則不產該檔。
中文字型走系統字型 fallback（Noto Sans TC / Microsoft JhengHei），不外連 webfont。
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


def _section(pkg: dict, key: str) -> dict:
    """安全取出區塊：非 dict（字串/list/None）一律視為缺，不拋例外。"""
    v = pkg.get(key)
    return v if isinstance(v, dict) else {}


def _render_htmls(pkg: dict) -> list[tuple[str, str]]:
    """回傳 [(檔名, html)]；resume / cover_letter 各自獨立成檔。"""
    out: list[tuple[str, str]] = []
    job_title = str(pkg.get("job_title") or "求職投遞包")
    company = str(pkg.get("company") or "")

    resume = _section(pkg, "resume")
    if resume:
        bullets = [str(b) for b in (resume.get("bullets") or []) if str(b).strip()]
        html = _env.get_template("resume.html").render(
            job_title=job_title, company=company,
            summary=str(resume.get("summary") or ""), bullets=bullets)
        out.append(("resume.pdf", html))

    cover = _section(pkg, "cover_letter")
    if cover:
        body_lines = [ln for ln in str(cover.get("body") or "").split("\n") if ln.strip()]
        html = _env.get_template("cover_letter.html").render(
            subject=str(cover.get("subject") or ""), body_lines=body_lines)
        out.append(("cover_letter.pdf", html))

    return out


def build_pdfs(pkg: dict) -> dict[str, bytes]:
    if not isinstance(pkg, dict):
        pkg = {}
    htmls = _render_htmls(pkg)
    if not htmls:
        return {}
    # 延後 import：FastAPI 同步端點跑在 threadpool，sync_playwright 可用；
    # 單一 browser 實例渲染全部文件，避免每檔各啟動一次。
    from playwright.sync_api import sync_playwright
    files: dict[str, bytes] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            for name, html in htmls:
                page.set_content(html, wait_until="load")
                files[name] = page.pdf(format="A4", print_background=True)
        finally:
            browser.close()
    return files
