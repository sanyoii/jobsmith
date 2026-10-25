"""職缺來源共用工具：HTTP 取得、文字清理。

部分台灣站台（yourator/cake）在本環境憑證鏈驗證失敗（非被擋），對這些站以
verify=False 取公開唯讀資料；104 憑證正常。各 source 失敗一律回 blocked，不拋例外。
"""
from __future__ import annotations

import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 20

_HIGHLIGHT = re.compile(r"\[\[\[|\]\]\]")  # 104 關鍵字高亮標記


def clean(text: str | None) -> str:
    return _HIGHLIGHT.sub("", text or "").strip()


def http_get(url: str, *, referer: str | None = None, verify: bool = True, timeout: int = TIMEOUT):
    headers = {"User-Agent": UA, "Accept": "application/json, text/html"}
    if referer:
        headers["Referer"] = referer
    return requests.get(url, headers=headers, verify=verify, timeout=timeout)


def http_post(url: str, *, json=None, headers: dict | None = None, timeout: int = TIMEOUT):
    merged = {"User-Agent": UA, "Accept": "application/json, text/html"}
    if headers:
        merged.update(headers)
    return requests.post(url, json=json, headers=merged, timeout=timeout)
