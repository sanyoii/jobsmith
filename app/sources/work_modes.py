"""工作形式（現場辦公／部分遠端／全遠端）— 結果端過濾，仿 regions.py 但固定 enum。

07-10 改版：原設計對 work_mode=None（未知）一律放行，但多數來源（cake/yourator/linkedin 全部、
其餘來源的無信號分支）都是 None，導致選「全遠端」仍整批混入非遠端職缺。工作形式是硬約束
（不能通勤就是不能），precision 優先：

1. 先用標題/地點文字推斷補 None（真遠端職缺幾乎都會寫 Remote/遠端 字樣）；
2. 有選 work_mode 時，推斷後仍未知 → 一律擋。

代價（明知且接受）：完全沒寫遠端字樣的未標示職缺會被濾掉。
"""
from __future__ import annotations

WORK_MODES = ["onsite", "hybrid", "remote"]

# hybrid 關鍵字必須先比對：hybrid 敘述常同時含 remote/遠端 字樣（如「部分遠端」「hybrid remote」）。
_HYBRID_KWS = ("hybrid", "混合", "部分遠端")
_REMOTE_KWS = ("remote", "wfh", "work from home", "全遠端", "遠端", "在家工作")


def parse_keys(raw: str | None) -> list[str]:
    """前端傳來的逗號字串 → 有效 work_mode key（保序、去重、丟未知值）。"""
    out: list[str] = []
    for part in (raw or "").split(","):
        k = part.strip()
        if k in WORK_MODES and k not in out:
            out.append(k)
    return out


def infer(*texts: str | None) -> str | None:
    """從標題/地點等文字推斷工作形式；無關鍵字 → None。

    已知限制：「遠端監控」「遠端醫療」這類產品詞會誤判為 remote——誤放行等同舊行為，
    比誤殺（漏掉真遠端職缺）便宜，接受。
    """
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    if any(k in blob for k in _HYBRID_KWS):
        return "hybrid"
    if any(k in blob for k in _REMOTE_KWS):
        return "remote"
    return None


def effective(work_mode: str | None, *texts: str | None) -> str | None:
    """來源已標示就信來源的；沒有才用文字推斷補。"""
    return work_mode if work_mode is not None else infer(*texts)


def match(work_mode: str | None, keys: list[str]) -> bool:
    """keys 空 → True（不限）；否則嚴格比對——未知(None) 一律擋（precision 優先，見模組 docstring）。"""
    return not keys or work_mode in keys
