from app.models import JobPosting, JobMatch, Profile
from app.sources.query_plan import plan_queries, source_queries, grouped_requests
from app.sources import source_defijobs
from app.agents import job_search
from tests.conftest import FakeLLM


def test_bilingual_roles_preserve_all_primary_targets_and_budget():
    queries = ["QA 工程師", "測試工程師", "自動化測試工程師"]
    plan = plan_queries(queries, ["104", "linkedin", "defijobs"], ["manual test"])
    assert plan["104"][:4] == ["manual test", *queries]
    assert plan["linkedin"][:4] == ["manual test", "QA Engineer", "Software Test Engineer", "QA Automation Engineer"]
    assert all(len(terms) <= 5 for terms in plan.values())
    requests = grouped_requests(plan)
    assert sum("defijobs" in sources for _, sources in requests) == 1
    assert next(q for q, sources in requests if "defijobs" in sources) == plan["defijobs"]


def test_unknown_terms_and_literal_custom_are_preserved_without_invented_translation():
    assert source_queries(["未知職務", "SDET"], "linkedin", ["手動指定"])[:3] == ["手動指定", "未知職務", "SDET"]


def test_defi_matches_whole_phrase_in_title_and_fetches_once(monkeypatch):
    html = """<div class="w-dyn-item"><a class="job-link" href="/qa"></a><div class="j-title">QA Engineer</div><div class="org">Example</div></div>
    <div class="w-dyn-item"><a class="job-link" href="/backend"></a><div class="j-title">Backend Engineer</div><div class="org">QA Company</div></div>"""
    calls = []
    class Response:
        ok = True
        text = html
    def fetch(*args, **kwargs):
        calls.append(1)
        return Response()
    monkeypatch.setattr(source_defijobs, "http_get", fetch)
    result = source_defijobs.search(["QA Engineer", "Software Test Engineer"])
    assert len(calls) == 1
    assert [j.title for j in result.jobs] == ["QA Engineer"]
    assert not source_defijobs._matches(["qa", "engineer"], "Backend Engineer")
    assert not source_defijobs._matches(["qa"], "Squad Engineer")


def test_qa_guard_rejects_security_keyword_but_keeps_manual_test(monkeypatch):
    monkeypatch.setattr(job_search, "get_llm", lambda *args, **kw: FakeLLM(
        job_search.SearchQueries(queries=["Penetration Testing", "Manual Test"])))
    profile = Profile(name="QA", summary="Senior QA Engineer", raw_text="r")
    assert job_search.derive_queries(profile) == ["Manual Test"]


def test_role_checks_keep_backend_qa_but_cap_wrong_and_unknown_roles():
    profile = Profile(name="QA", summary="Senior QA Engineer", raw_text="r")
    jobs = [JobPosting(source="test", title=t, company="test", url=str(i), snippet="Python API")
            for i, t in enumerate(["Backend QA Engineer", "Backend Engineer", "Quality Assurance Engineer", "Hardware Test Engineer"])]
    matches = [JobMatch(job=j, fit_score=95) for j in jobs]
    result = {m.job.title: m for m in job_search._check_role_matches(profile, matches)}
    assert result["Backend QA Engineer"].fit_score == 95
    assert result["Backend Engineer"].fit_score == 30
    assert result["Quality Assurance Engineer"].fit_score == 95
    assert result["Hardware Test Engineer"].fit_score == 59
    assert "職務待確認" in result["Hardware Test Engineer"].reason


def test_web3_qa_category_collapses_derived_queries_but_keeps_custom_literal():
    assert source_queries(["QA 工程師", "自動化測試工程師"], "web3career") == ["quality assurance"]
    assert source_queries(["QA 工程師"], "web3career", ["manual test"])[0] == "manual test"


def test_web3_qa_query_uses_verified_category(monkeypatch):
    from app.sources import source_web3career
    calls = []
    class Response:
        ok = True
        text = '<tr data-jobid="1"><h2>QA Engineer</h2><a href="/qa">job</a><td class="job-location-mobile">Company</td></tr>'
    def fetch(url, **kw):
        calls.append(url)
        return Response()
    monkeypatch.setattr(source_web3career, "http_get", fetch)
    source_web3career.search("QA Engineer", pages=1)
    assert calls == ["https://web3.career/quality-assurance-jobs?page=1"]


def test_support_aliases_use_english_overseas_and_do_not_enter_web3_qa_category():
    plan = plan_queries(["技術支援工程師"], ["104", "linkedin", "web3career"])
    assert plan["104"] == ["技術支援工程師", "Technical Support Engineer", "Support Engineer"]
    assert plan["linkedin"] == ["Technical Support Engineer", "Support Engineer"]
    assert plan["web3career"] == plan["linkedin"]


def test_manager_aliases_preserve_level_in_all_sources():
    plan = plan_queries(["QA 經理"], ["104", "linkedin", "web3career"])
    assert plan["104"] == ["QA 經理", "QA Manager", "Test Manager", "Quality Assurance Manager"]
    assert plan["linkedin"] == ["QA Manager", "Test Manager", "Quality Assurance Manager"]
    assert plan["web3career"] == plan["linkedin"]


def test_web3_manager_category_filters_engineers_without_calling_zero_a_failure(monkeypatch):
    from app.sources import source_web3career as source
    class Response:
        ok = True
        text = '<tr data-jobid="1"><h2>QA Engineer</h2><a href="/qa-engineer">job</a></tr><tr data-jobid="2"><h2>Engineering Manager QA</h2><a href="/qa-manager">job</a></tr>'
    calls = []
    def fetch(url):
        calls.append(url)
        return Response()
    monkeypatch.setattr(source, "http_get", fetch)
    result = source.search("QA Manager")
    assert calls == ["https://web3.career/quality-assurance-jobs?page=1"]
    assert [j.title for j in result.jobs] == ["Engineering Manager QA"]
    Response.text = '<tr data-jobid="1"><h2>QA Engineer</h2><a href="/qa-engineer">job</a></tr>'
    result = source.search("QA Manager")
    assert not result.blocked and result.jobs == []
