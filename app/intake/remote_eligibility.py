"""Evidence-based remote/Taiwan checks. Public JD only; no models or manual-record writes.

Job-specific residency restrictions outrank generic company culture. Missing, failed,
ambiguous or budget-limited checks remain unknown; remote is not worldwide employment.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from app.intake.jd_fetch import fetch_jd
from app.models import JobPosting, RemoteCondition, RemoteEligibility

MAX_PAGES = 40
TIME_BUDGET = 45
WORKERS = 4
_COUNTRIES = re.compile(r"\b(?:brazil|brasil|united states|usa|canada|united kingdom|uk|germany|france|australia|india|singapore|japan|china|europe|eu|emea|latin america|latam)\b|巴西|美國|加拿大|英國|德國|法國|澳洲|印度|新加坡|日本|中國|歐洲", re.I)
_TAIWAN = re.compile(r"\b(?:taiwan|tw)\b|台灣|臺灣|台北|臺北|新北|桃園|台中|臺中|台南|臺南|高雄|新竹|基隆|苗栗|彰化|南投|雲林|嘉義|屏東|宜蘭|花蓮|台東|臺東|澎湖|金門|連江|taipei|taichung|tainan|kaohsiung", re.I)
_GLOBAL = re.compile(r"\b(?:worldwide|anywhere in the world|all countries)\b|全球各地|全球遠端", re.I)
_LOCATION = re.compile(r"^(?:location|locations|job location|work location|工作地點|工作地區|上班地點)\s*[:：]", re.I)
_RESIDENCE = re.compile(r"(?:applicants?|candidates?|you|employees?)\s+(?:must|need to|required to)\s+(?:be based|reside|live|be located)|must (?:reside|live|be based|be located)|(?:only|exclusively) (?:hiring|available|open) (?:in|to)|限(?:居住|在)|必須(?:居住|位於)|需(?:居住|位於)", re.I)
_REMOTE = re.compile(r"^(?:location type|workplace type|work mode|工作方式)\s*[:：]\s*(?:remote|全遠端)|^location\s*:\s*remote|\b(?:fully remote|100% remote|100 percent remote|remote position|remote role)\b|全遠端|完全遠端|完全在家工作", re.I)
_NOT_REMOTE = re.compile(r"^(?:location type|workplace type|work mode|工作方式)\s*[:：]\s*(?:onsite|on-site|hybrid|現場|混合)|(?:this (?:role|position) is|work (?:arrangement|mode) is)\s+(?:hybrid|on-site|onsite)|(?:required|must|expected) to (?:work|be|attend).*?(?:office|on-site|onsite)|\b(?:no remote work|not a remote|remote work is not|hybrid remote)\b|部分遠端|混合辦公|需(?:每週|每日|定期).{0,12}(?:進辦公室|到辦公室)|必須到辦公室", re.I)


def _lines(text):
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    result = []
    for i, line in enumerate(lines):
        if re.fullmatch(r"(?:location|locations|job location|work location|location type|workplace type|work mode|工作地點|工作方式|上班地點)\s*[:：]?", line, re.I):
            line = line.rstrip(":：") + ": " + (lines[i + 1] if i + 1 < len(lines) else "")
        result.append(line)
    return result


def _condition(positive, negative, missing):
    if positive and negative:
        return RemoteCondition(reason="職缺條件有矛盾，需確認。", evidence=(negative + positive)[:3])
    if negative:
        return RemoteCondition(value="fail", reason=negative[0], evidence=negative[:3])
    if positive:
        return RemoteCondition(value="pass", reason=positive[0], evidence=positive[:3])
    return RemoteCondition(reason=missing)


def assess_text(text: str, source_url: str) -> RemoteEligibility:
    lines = _lines(text)
    remote_yes, remote_no, taiwan_yes, taiwan_no, global_yes = [], [], [], [], []
    for line in lines:
        line = line[:1200]
        if _NOT_REMOTE.search(line): remote_no.append(line)
        elif _REMOTE.search(line): remote_yes.append(line)
        excluded_tw = re.search(r"(?:cannot|can't|not|excluding|except|不接受|不含).{0,15}(?:taiwan|台灣|臺灣)", line, re.I)
        if excluded_tw:
            taiwan_no.append(line)
            continue
        # Only job/applicant location requirements, never company office locations.
        location = _LOCATION.search(line)
        residence = _RESIDENCE.search(line)
        if location or residence:
            requirement = line[(location or residence).end():]
            requirement = re.split(r"[;|]|(?:and|to)\s+(?:support|serve|service|collaborate|help|report)\b", requirement, maxsplit=1, flags=re.I)[0]
            if _TAIWAN.search(requirement): taiwan_yes.append(line)
            elif _COUNTRIES.search(requirement) or re.search(r"\b(?:US|BR)\b", requirement): taiwan_no.append(line)
            elif _GLOBAL.search(requirement): global_yes.append(line)
        elif re.search(r"(?:work from|remote|hiring|applicants).{0,40}(?:anywhere in the world|worldwide|all countries)", line, re.I):
            global_yes.append(line)
    remote = _condition(remote_yes, remote_no, "內頁未明確說明可全遠端。")
    taiwan = _condition(taiwan_yes or ([] if taiwan_no else global_yes), taiwan_no,
                        "內頁未明確說明接受從台灣工作；Remote／APAC 不足以確認。")
    status = "fail" if "fail" in (remote.value, taiwan.value) else "pass" if remote.value == taiwan.value == "pass" else "unknown"
    return RemoteEligibility(status=status, remote=remote, taiwan=taiwan, source_url=source_url,
                             checked_at=datetime.now(timezone.utc).isoformat(), method="page")


def unchecked(url: str, reason: str, method="not_checked") -> RemoteEligibility:
    return RemoteEligibility(source_url=url, method=method,
        remote=RemoteCondition(reason=reason), taiwan=RemoteCondition(reason=reason))


def check_job(job: JobPosting) -> JobPosting:
    try:
        page = fetch_jd(job.url, timeout=8)
        assessment = assess_text(page.text, job.url)
        if getattr(page, "truncated", False):
            reason = "內頁內容超過讀取上限，尚未完整確認工作地區與遠端限制。"
            assessment = assessment.model_copy(update={"status": "unknown",
                "remote": RemoteCondition(reason=reason, evidence=assessment.remote.evidence),
                "taiwan": RemoteCondition(reason=reason, evidence=assessment.taiwan.evidence)})
    except Exception:
        assessment = unchecked(job.url, "內頁讀取失敗或被擋，無法確認；可查看原職缺。", "unavailable")
    return job.model_copy(update={"remote_eligibility": assessment})


def check_jobs(jobs: list[JobPosting], token, cache=None, progress=None) -> list[JobPosting]:
    cache = {} if cache is None else cache
    started = time.monotonic()
    pending = list(dict.fromkeys(j.url for j in jobs if j.url not in cache))
    by_url = {j.url: j for j in jobs}
    checked = 0
    for offset in range(0, min(len(pending), MAX_PAGES), WORKERS):
        token.check()
        if time.monotonic() - started >= TIME_BUDGET: break
        batch = pending[offset:min(offset + WORKERS, MAX_PAGES)]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(check_job, by_url[url]): url for url in batch}
            for future in as_completed(futures):
                token.check()
                checked_job = future.result()
                cache[futures[future]] = checked_job.remote_eligibility
                checked += 1
        if progress: progress(checked, len(pending))
    return [j.model_copy(update={"remote_eligibility": cache.get(j.url) or unchecked(j.url, "本次初查額度或時間已用完，尚未讀取內頁。")}) for j in jobs]
