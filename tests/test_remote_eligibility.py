import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.intake import remote_eligibility as mod
from app.intake import jd_fetch
from app.models import JobPosting, JobMatch, Profile, SearchResult
from app import server, task_control

URL = "https://jobs.example.test/role"


@pytest.mark.parametrize("text,remote,taiwan,status", [
    ("Location: Remote - Brazil\nTo be considered, you must reside in Brazil.\nWe work from anywhere in the world.", "pass", "fail", "fail"),
    ("Location\nRemote - Brazil", "pass", "fail", "fail"),
    ("Location Type: Remote\nLocation: Taiwan", "pass", "pass", "pass"),
    ("Location: Remote - Worldwide", "pass", "pass", "pass"),
    ("Location: Remote - APAC", "pass", "unknown", "unknown"),
    ("Location: Remote", "pass", "unknown", "unknown"),
    ("We have offices in Brazil and Taiwan. Our company is remote-first.", "unknown", "unknown", "unknown"),
    ("You will provide remote troubleshooting to customers in Brazil.", "unknown", "unknown", "unknown"),
    ("Location Type: Hybrid\nLocation: Taiwan", "fail", "pass", "fail"),
    ("This role is hybrid. Location: Taiwan", "fail", "unknown", "fail"),
    ("Location Type: On-site\nLocation: Taiwan", "fail", "pass", "fail"),
    ("This is a fully remote role.\nCandidates must reside in Canada.", "pass", "fail", "fail"),
    ("Location: Remote - US", "pass", "fail", "fail"),
    ("Location: Remote\nWork timezone: ideally PST", "pass", "unknown", "unknown"),
    ("Location: Remote\nApplicants must reside in Taiwan or Brazil.", "pass", "pass", "pass"),
    ("Location: Remote - Worldwide\nApplicants cannot work in Taiwan.", "pass", "fail", "fail"),
    ("Location Type: Remote\nLocation Type: Hybrid\nLocation: Taiwan", "unknown", "pass", "unknown"),
    ("Location: Remote - Taiwan\nApplicants must reside in Brazil.", "pass", "unknown", "unknown"),
    ("Location: Remote\nCandidates must reside in Brazil and support customers in Taiwan.", "pass", "fail", "fail"),
    ("工作方式：全遠端\n上班地點：台中市", "pass", "pass", "pass"),
    ("工作方式：全遠端\n工作地點：台灣", "pass", "pass", "pass"),
    ("部分遠端\n上班地點：台北", "fail", "pass", "fail"),
])
def test_evidence_classification(text, remote, taiwan, status):
    result = mod.assess_text(text, URL)
    assert (result.remote.value, result.taiwan.value, result.status) == (remote, taiwan, status)
    assert result.method == "page" and result.source_url == URL and result.checked_at
    for condition in [result.remote, result.taiwan]:
        if condition.value != "unknown": assert condition.evidence


def job(url=URL):
    return JobPosting(source="test", title="Support Engineer", company="Example", url=url)


def test_failed_page_never_uses_listing_remote_as_confirmation(monkeypatch):
    monkeypatch.setattr(mod, "fetch_jd", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("blocked")))
    result = mod.check_job(job().model_copy(update={"location": "Remote - Taiwan", "work_mode": "remote"}))
    assert result.remote_eligibility.status == "unknown"
    assert result.remote_eligibility.method == "unavailable"
    assert not result.remote_eligibility.checked_at


def test_fetch_budget_dedup_and_cache_do_not_mark_unread_pages_as_pass(monkeypatch):
    calls = []
    def fetch(url, **kw):
        calls.append(url)
        return SimpleNamespace(text="Location: Remote - Taiwan")
    monkeypatch.setattr(mod, "fetch_jd", fetch)
    monkeypatch.setattr(mod, "MAX_PAGES", 1)
    cache = {}
    jobs = [job(), job(), job(URL + "/2")]
    result = mod.check_jobs(jobs, task_control.TaskToken("test"), cache=cache)
    assert calls == [URL]
    assert [j.remote_eligibility.status for j in result] == ["pass", "pass", "unknown"]
    assert result[2].remote_eligibility.method == "not_checked"
    mod.check_jobs([job()], task_control.TaskToken("test"), cache=cache)
    assert calls == [URL]


def test_cancel_before_fetch(monkeypatch):
    token = task_control.TaskToken("stop")
    token.cancel()
    monkeypatch.setattr(mod, "fetch_jd", lambda *a, **kw: pytest.fail("cancelled task fetched"))
    with pytest.raises(task_control.TaskCancelled): mod.check_jobs([job()], token)


def test_jsonld_job_conditions_ignore_organization_headquarters(monkeypatch):
    data = {"@graph": [
        {"@type": "Organization", "address": {"addressCountry": "Brazil"}},
        {"@type": "JobPosting", "title": "Support Engineer", "jobLocationType": "TELECOMMUTE",
         "applicantLocationRequirements": {"@type": "Country", "name": "Taiwan"},
         "description": "<p>Support our customers by diagnosing and documenting complex product incidents.</p>"}]}
    monkeypatch.setattr(jd_fetch, "_http_html", lambda *a, **kw: '<script type="application/ld+json">' + json.dumps(data) + '</script>')
    page = jd_fetch.fetch_jd(URL)
    result = mod.assess_text(page.text, URL)
    assert result.status == "pass" and "Brazil" not in page.text


def _events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _patch_search(monkeypatch, jobs):
    monkeypatch.setattr(server, "structure_profile", lambda text: Profile(name="Support", summary="Support Engineer", raw_text=text))
    monkeypatch.setattr(server, "derive_queries", lambda profile: ["support"])
    monkeypatch.setattr(server, "search_all", lambda *a, **kw: [SearchResult(source="test", jobs=jobs)])
    monkeypatch.setattr(server, "check_remote_jobs", mod.check_jobs)


def test_search_checks_before_rank_and_applies_to_company_results(monkeypatch):
    jobs = [job(URL + "/brazil"), job(URL + "/taiwan"), job(URL + "/unknown")]
    _patch_search(monkeypatch, jobs)
    monkeypatch.setattr(mod, "fetch_jd", lambda url, **kw: SimpleNamespace(text="Location: Remote - Brazil" if "brazil" in url else "Location: Remote - Taiwan" if "taiwan" in url else "Location: Remote - APAC"))
    monkeypatch.setattr(server, "find_company_jobs", lambda *a, **kw: [job(URL + "/company-brazil")])
    ranked = []
    def rank(profile, jobs, top_k=None, **kw):
        ranked.extend(j.url for j in jobs)
        return [JobMatch(job=j, fit_score=90) for j in jobs]
    monkeypatch.setattr(server, "rank_jobs", rank)
    events = _events(TestClient(server.app).post("/api/jobs/auto", data={"resume_text": "support", "sources": "104", "taiwan_remote": "true", "work_mode": "remote", "companies": "Example"}))
    excluded = [j for e in events if e["type"] == "remote_excluded" for j in e["jobs"]]
    assert {j["url"] for j in excluded} == {URL + "/brazil", URL + "/company-brazil"}
    assert set(ranked) == {URL + "/taiwan", URL + "/unknown"}
    assert any(e["type"] == "ranked_batch" for e in events)


def test_all_geographically_excluded_does_not_load_demo(monkeypatch):
    _patch_search(monkeypatch, [job()])
    monkeypatch.setattr(mod, "fetch_jd", lambda *a, **kw: SimpleNamespace(text="Location: Remote - Brazil"))
    monkeypatch.setattr(server, "_load_fallback_jobs", lambda: pytest.fail("excluded real jobs are not source failures"))
    events = _events(TestClient(server.app).post("/api/jobs/auto", data={"resume_text": "support", "sources": "104", "taiwan_remote": "true"}))
    assert next(e for e in events if e["type"] == "rank_start")["total"] == 0
    assert next(e for e in events if e["type"] == "search_empty")["reason"] == "filtered_out"
    assert not any(e["type"] == "all_blocked" for e in events)


def test_disabled_check_keeps_legacy_behavior_without_page_requests(monkeypatch):
    _patch_search(monkeypatch, [job()])
    monkeypatch.setattr(mod, "fetch_jd", lambda *a, **kw: pytest.fail("disabled initial check fetched page"))
    monkeypatch.setattr(server, "rank_jobs", lambda profile, jobs, *args, **kw: [JobMatch(job=j, fit_score=90) for j in jobs])
    events = _events(TestClient(server.app).post("/api/jobs/auto", data={"resume_text": "support", "sources": "104", "taiwan_remote": "false"}))
    assert not any(e["type"] == "remote_excluded" for e in events)


def test_truncated_page_cannot_confirm_eligibility(monkeypatch):
    monkeypatch.setattr(mod, "fetch_jd", lambda *a, **kw: SimpleNamespace(text="Location: Remote - Taiwan", truncated=True))
    result = mod.check_job(job()).remote_eligibility
    assert result.status == result.remote.value == result.taiwan.value == "unknown"
    assert result.remote.evidence
