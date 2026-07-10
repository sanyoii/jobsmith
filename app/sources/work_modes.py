"""工作形式（現場辦公／部分遠端／全遠端）— 純結果端過濾，仿 regions.py 但更簡單（固定 enum，不用別名比對）。

未知資料（work_mode=None）一律不擋：跟 regions.match_location 對缺地點資料的寬容處理一致，
避免沒有工作形式信號的來源（cake/yourator/linkedin/web3career/cryptojobslist/jobfrog 的
false 分支）一篩就整批消失。
"""
from __future__ import annotations

WORK_MODES = ["onsite", "hybrid", "remote"]


def parse_keys(raw: str | None) -> list[str]:
    """前端傳來的逗號字串 → 有效 work_mode key（保序、去重、丟未知值）。"""
    out: list[str] = []
    for part in (raw or "").split(","):
        k = part.strip()
        if k in WORK_MODES and k not in out:
            out.append(k)
    return out


def match(work_mode: str | None, keys: list[str]) -> bool:
    """keys 空 → True；work_mode 未知(None) → True（不因缺資料誤殺）；否則看 work_mode in keys。"""
    return not keys or work_mode is None or work_mode in keys
