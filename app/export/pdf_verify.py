"""ATS 文字層驗證（確定性檢查，無 LLM）：驗證 PDF 實際會被 ATS 讀到的文字。

兩層（參考 ai-job-search apply.md 的設計）：
1. Parseability：文字層是否可抽取、有無 (cid:NNN) 亂碼。
2. Keyword coverage：
   - covered        ：ats_keywords_hit 中逐字出現於 PDF 文字層
   - rendering-loss ：履歷宣稱有命中（ats_keywords_hit）但 PDF 文字層讀不到 → 版面吃字，要修
   - gap            ：ats_keywords_missing（真的沒有的技能）→ 誠實承認，不硬塞、不計入警告
   synonym-only 態需要同義詞資料來源，pkg 內沒有 → 本版不判，留待有詞庫再加。
"""
from __future__ import annotations

import re
import unicodedata
from io import BytesIO

from pypdf import PdfReader


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _norm(s: str) -> str:
    # NFKC：Chromium 產 PDF 的 font subset 會把部分中文字映射成康熙部首碼位
    # （工→⼯、自→⾃），肉眼相同但 codepoint 不同；NFKC 正規化回統一漢字再比對。
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).lower()


def ats_check(pdf_bytes: bytes, pkg: dict) -> dict:
    resume = pkg.get("resume") if isinstance(pkg.get("resume"), dict) else {}
    try:
        text = _pdf_text(pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"PDF 文字層抽取失敗：{exc}", "warnings": 1}

    norm = _norm(text)
    coverage: list[dict] = []
    for kw in (resume.get("ats_keywords_hit") or []):
        k = str(kw).strip()
        if not k:
            continue
        status = "covered" if _norm(k) in norm else "rendering-loss"
        coverage.append({"keyword": k, "status": status})
    for kw in (resume.get("ats_keywords_missing") or []):
        k = str(kw).strip()
        if k:
            coverage.append({"keyword": k, "status": "gap"})

    parseability = {
        "empty_text_layer": not norm.strip(),
        "cid_garbage": "(cid:" in text,
    }
    warnings = (
        sum(1 for c in coverage if c["status"] == "rendering-loss")
        + (1 if parseability["empty_text_layer"] else 0)
        + (1 if parseability["cid_garbage"] else 0)
    )
    return {"ok": True, "parseability": parseability, "coverage": coverage, "warnings": warnings}
