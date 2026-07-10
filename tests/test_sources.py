import json

from app.sources import (
    source_104,
    source_cake,
    source_cryptojobslist,
    source_dejob,
    source_jobfrog,
    source_linkedin,
    source_web3career,
    source_yourator,
)


class FakeResp:
    def __init__(self, ok=True, status=200, json_data=None, text=""):
        self.ok = ok
        self.status_code = status
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def test_source_104_parses(monkeypatch):
    payload = {"data": [{
        "jobName": "[[[AI]]]工程師", "custName": "未來智能", "jobAddrNoDesc": "台北",
        "salaryDesc": "面議", "descSnippet": "做 [[[Python]]] 開發",
        "link": {"job": "https://www.104.com.tw/job/abc"},
        "remoteWorkType": 1,
    }]}
    monkeypatch.setattr(source_104, "http_get", lambda *a, **k: FakeResp(json_data=payload))
    res = source_104.search("AI", limit=5)
    assert res.blocked is False
    assert len(res.jobs) == 1
    j = res.jobs[0]
    assert j.title == "AI工程師"          # [[[ ]]] 已清除
    assert j.company == "未來智能"
    assert j.url.endswith("/abc")
    assert "Python" in j.snippet and "[[[" not in j.snippet
    assert j.work_mode == "remote"


def test_source_104_paginates_and_dedups(monkeypatch):
    # pages=2：抓兩頁、合併、跨頁去重（job/1 在兩頁都出現，只計一次）
    pages_data = {
        "1": {"data": [
            {"jobName": "A", "custName": "C", "link": {"job": "https://x/1"}},
            {"jobName": "B", "custName": "C", "link": {"job": "https://x/2"}},
        ]},
        "2": {"data": [
            {"jobName": "A", "custName": "C", "link": {"job": "https://x/1"}},  # 重複
            {"jobName": "D", "custName": "C", "link": {"job": "https://x/3"}},
        ]},
    }
    calls = []

    def fake_get(url, **k):
        # 從 URL 取出 page=N
        page = url.split("page=")[1].split("&")[0]
        calls.append(page)
        return FakeResp(json_data=pages_data[page])

    monkeypatch.setattr(source_104, "http_get", fake_get)
    res = source_104.search("AI", limit=15, pages=2)
    assert calls == ["1", "2"]                       # 真的抓了兩頁
    urls = [j.url for j in res.jobs]
    assert urls == ["https://x/1", "https://x/2", "https://x/3"]  # 去重後 3 筆


def test_source_104_area_param(monkeypatch):
    # 帶 area → URL 應出現 &area=（逗號串接、URL 編碼），不帶則沒有
    seen = {}

    def fake_get(url, **k):
        seen["url"] = url
        return FakeResp(json_data={"data": []})

    monkeypatch.setattr(source_104, "http_get", fake_get)
    source_104.search("AI", area=["6001001000", "6001016000"])
    assert "&area=6001001000%2C6001016000" in seen["url"]  # 台北,高雄（%2C = 逗號）
    source_104.search("AI")
    assert "&area=" not in seen["url"]                       # 不限地區時不帶 area


def test_source_104_pages_default_one(monkeypatch):
    # 預設 pages=1 只抓第一頁（維持舊行為）
    calls = []

    def fake_get(url, **k):
        calls.append(url)
        return FakeResp(json_data={"data": [{"jobName": "A", "custName": "C",
                                             "link": {"job": "https://x/1"}}]})

    monkeypatch.setattr(source_104, "http_get", fake_get)
    source_104.search("AI")
    assert len(calls) == 1


def test_source_104_salary_from_low_high(monkeypatch):
    # 真實 104 回傳：salaryDesc 不存在，數值在 salaryLow/salaryHigh + 型態碼 s10
    payload = {"data": [
        {"jobName": "月薪職", "custName": "A", "salaryLow": 48000, "salaryHigh": 70000,
         "s10": 50, "link": {"job": "https://x/1"}},
        {"jobName": "年薪職", "custName": "B", "salaryLow": 800000, "salaryHigh": 1300000,
         "s10": 60, "link": {"job": "https://x/2"}},
        {"jobName": "面議職", "custName": "C", "salaryLow": 0, "salaryHigh": 0,
         "s10": 10, "link": {"job": "https://x/3"}},
    ]}
    monkeypatch.setattr(source_104, "http_get", lambda *a, **k: FakeResp(json_data=payload))
    res = source_104.search("AI", limit=5)
    salaries = [j.salary for j in res.jobs]
    assert salaries[0] == "月薪 NT$48,000–70,000"
    assert salaries[1] == "年薪 NT$800,000–1,300,000"
    assert salaries[2] == "面議"


def test_source_104_open_ended_salary_sentinel(monkeypatch):
    # 104「X 元以上」回傳 salaryHigh=9999999 哨兵值，不可印成 NT$40,000–9,999,999
    payload = {"data": [{"jobName": "x", "custName": "A", "salaryLow": 40000,
                         "salaryHigh": 9999999, "s10": 50, "link": {"job": "https://x/1"}}]}
    monkeypatch.setattr(source_104, "http_get", lambda *a, **k: FakeResp(json_data=payload))
    j = source_104.search("AI").jobs[0]
    assert j.salary == "月薪 NT$40,000 以上"


def test_source_104_ignores_legacy_salarydesc(monkeypatch):
    # 即使有舊的 salaryDesc 字串也不再採用，一律以 low/high 計算
    payload = {"data": [{"jobName": "x", "custName": "A", "salaryDesc": "舊字串",
                         "salaryLow": 40000, "salaryHigh": 50000, "s10": 50,
                         "link": {"job": "https://x/1"}}]}
    monkeypatch.setattr(source_104, "http_get", lambda *a, **k: FakeResp(json_data=payload))
    j = source_104.search("AI").jobs[0]
    assert j.salary == "月薪 NT$40,000–50,000"


def test_source_104_blocked_on_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("nope")
    monkeypatch.setattr(source_104, "http_get", boom)
    res = source_104.search("AI")
    assert res.blocked is True and res.jobs == []


def test_source_104_blocked_on_non_ok(monkeypatch):
    monkeypatch.setattr(source_104, "http_get", lambda *a, **k: FakeResp(ok=False, status=403))
    res = source_104.search("AI")
    assert res.blocked is True and res.error == "HTTP 403"


def test_source_yourator_parses(monkeypatch):
    payload = {"payload": {"jobs": [{
        "name": "AI 工程師", "location": "台北市", "salary": "NT$ 40,000",
        "path": "/companies/x/jobs/1", "tags": ["AI", "Python"],
        "company": {"brand": "某公司"},
    }]}}
    monkeypatch.setattr(source_yourator, "http_get", lambda *a, **k: FakeResp(json_data=payload))
    res = source_yourator.search("AI")
    assert len(res.jobs) == 1
    j = res.jobs[0]
    assert j.company == "某公司"
    assert j.url == "https://www.yourator.co/companies/x/jobs/1"
    assert "Python" in j.requirements


def test_source_cake_blocked_when_no_next_data(monkeypatch):
    monkeypatch.setattr(source_cake, "http_get", lambda *a, **k: FakeResp(text="<html>no data</html>"))
    res = source_cake.search("AI")
    assert res.blocked is True


_CAKE_HTML = """<html><body>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"initialState":{"jobSearch":{"entityByPathId":{
"ai-engineer-1":{"path":"ai-engineer-1","title":"AI Engineer","description":"Build LLM systems",
"locations":["台北市, 台灣"],"salary":{"min":"1500000","max":"2100000","currency":"TWD","type":"per_year"},
"tags":["Python","LLM"],"page":{"path":"swag","name":"SWAG"}}
}}}}}}
</script></body></html>"""


def test_source_cake_parses_entity_state(monkeypatch):
    monkeypatch.setattr(source_cake, "http_get", lambda *a, **k: FakeResp(text=_CAKE_HTML))
    res = source_cake.search("AI", limit=5)
    assert res.blocked is False
    assert len(res.jobs) == 1
    j = res.jobs[0]
    assert j.title == "AI Engineer"
    assert j.company == "SWAG"
    assert j.url == "https://www.cake.me/companies/swag/jobs/ai-engineer-1"
    assert j.salary == "年薪 TWD 1,500,000–2,100,000"
    assert j.location == "台北市, 台灣"
    assert "Python" in j.requirements


def test_source_cake_blocked_when_no_entities(monkeypatch):
    empty = ('<script id="__NEXT_DATA__" type="application/json">'
             '{"props":{"pageProps":{"initialState":{"jobSearch":{"entityByPathId":{}}}}}}</script>')
    monkeypatch.setattr(source_cake, "http_get", lambda *a, **k: FakeResp(text=empty))
    assert source_cake.search("AI").blocked is True


_LI_HTML = """
<ul>
  <li><div class="base-card">
    <a class="base-card__full-link" href="https://tw.linkedin.com/jobs/view/ai-engineer-123?refId=x&trackingId=y">l</a>
    <h3 class="base-search-card__title">  AI Engineer  </h3>
    <h4 class="base-search-card__subtitle">Onramp Lab</h4>
    <span class="job-search-card__location">Taipei City, Taiwan</span>
  </div></li>
  <li><div class="base-card">
    <a class="base-card__full-link" href="https://tw.linkedin.com/jobs/view/ml-eng-456">l</a>
    <h3 class="base-search-card__title">ML Engineer</h3>
    <h4 class="base-search-card__subtitle">Acme</h4>
    <span class="job-search-card__location">Taiwan</span>
  </div></li>
</ul>
"""


def test_source_linkedin_parses(monkeypatch):
    monkeypatch.setattr(source_linkedin, "http_get", lambda *a, **k: FakeResp(text=_LI_HTML))
    res = source_linkedin.search("AI", limit=5)
    assert res.blocked is False
    assert len(res.jobs) == 2
    j = res.jobs[0]
    assert j.title == "AI Engineer"
    assert j.company == "Onramp Lab"
    assert j.location == "Taipei City, Taiwan"
    assert j.url == "https://tw.linkedin.com/jobs/view/ai-engineer-123"  # query 已去除
    assert j.source == "linkedin"


def test_source_linkedin_blocked_on_empty(monkeypatch):
    monkeypatch.setattr(source_linkedin, "http_get", lambda *a, **k: FakeResp(text="<html></html>"))
    assert source_linkedin.search("AI").blocked is True


def test_source_linkedin_blocked_on_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("nope")
    monkeypatch.setattr(source_linkedin, "http_get", boom)
    assert source_linkedin.search("AI").blocked is True


_WEB3CAREER_HTML = """<html><body><table><tbody>
<tr data-jobid=1><td scope=row><a href="/ai-engineer-swag/1"><h2>AI Engineer</h2></a></td>
<td class="job-location-mobile"><a href="/x"><h3>SWAG</h3></a></td>
<td><time>1d</time></td>
<td class="job-location-mobile"><a href="/web3-jobs-taipei">Taipei</a><span>,</span><a href="/web3-jobs-taiwan">Taiwan</a></td>
<td><p class="text-salary">$80k - $100k</p></td>
<td><a class="text-shadow-1px">python</a><a class="text-shadow-1px">llm</a></td>
</tr>
<tr data-jobid=2><td scope=row><a href="/backend-engineer-acme/2"><h2>Backend Engineer</h2></a></td>
<td class="job-location-mobile"><a href="/y"><h3>Acme</h3></a></td>
<td><time>2d</time></td>
<td class="job-location-mobile"><span>Remote</span></td>
<td><p class="text-salary"></p></td>
<td><a class="text-shadow-1px">rust</a></td>
</tr>
</tbody></table></body></html>"""


def test_source_web3career_parses(monkeypatch):
    monkeypatch.setattr(source_web3career, "http_get", lambda *a, **k: FakeResp(text=_WEB3CAREER_HTML))
    res = source_web3career.search("AI", limit=5)
    assert res.blocked is False
    assert len(res.jobs) == 2
    j = res.jobs[0]
    assert j.title == "AI Engineer"
    assert j.company == "SWAG"
    assert j.location == "Taipei, Taiwan"
    assert j.salary == "$80k - $100k"
    assert j.url == "https://web3.career/ai-engineer-swag/1"
    assert "python" in j.requirements
    assert j.work_mode is None
    j2 = res.jobs[1]
    assert j2.location == "Remote"
    assert j2.work_mode == "remote"


def test_source_web3career_blocked_when_no_rows(monkeypatch):
    monkeypatch.setattr(source_web3career, "http_get", lambda *a, **k: FakeResp(text="<html>no jobs</html>"))
    assert source_web3career.search("AI").blocked is True


def test_source_web3career_blocked_on_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("nope")
    monkeypatch.setattr(source_web3career, "http_get", boom)
    assert source_web3career.search("AI").blocked is True


_CJL_JSON = {
    "props": {"pageProps": {"jobs": [{
        "seoSlug": "ai-engineer-remote-at-thesoul", "jobTitle": "AI Engineer",
        "companyName": "TheSoul", "jobLocation": "Remote", "salaryString": "$100k-150k/year",
        "tags": ["remote", "developer"], "remote": True,
    }]}}
}


def test_source_cryptojobslist_parses(monkeypatch):
    html = ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(_CJL_JSON) + "</script></body></html>")
    monkeypatch.setattr(source_cryptojobslist, "http_get", lambda *a, **k: FakeResp(text=html))
    res = source_cryptojobslist.search("AI", limit=5)
    assert res.blocked is False
    assert len(res.jobs) == 1
    j = res.jobs[0]
    assert j.title == "AI Engineer"
    assert j.company == "TheSoul"
    assert j.location == "Remote"
    assert j.salary == "$100k-150k/year"
    assert j.url == "https://cryptojobslist.com/jobs/ai-engineer-remote-at-thesoul"
    assert "remote" in j.requirements
    assert j.work_mode == "remote"


def test_source_cryptojobslist_blocked_when_no_next_data(monkeypatch):
    monkeypatch.setattr(source_cryptojobslist, "http_get", lambda *a, **k: FakeResp(text="<html>no data</html>"))
    assert source_cryptojobslist.search("AI").blocked is True


def test_source_cryptojobslist_blocked_when_no_jobs(monkeypatch):
    empty = ('<script id="__NEXT_DATA__" type="application/json">'
             '{"props":{"pageProps":{"jobs":[]}}}</script>')
    monkeypatch.setattr(source_cryptojobslist, "http_get", lambda *a, **k: FakeResp(text=empty))
    assert source_cryptojobslist.search("AI").blocked is True


def test_source_dejob_parses(monkeypatch):
    payload = {"data": {"results": [{
        "positionName": "Smart Contract Engineer", "company": "GMGN", "location": "",
        "base": "HK", "minSalary": 7000, "maxSalary": 10000,
        "url": "https://dejob.ai/jobDetail?id=7105",
        "tags": [{"tagId": 1, "tagName": "DEX"}, {"tagId": 2, "tagName": "DeFi"}],
        "content": "review smart contracts for security issues",
        "officeModeName": "Remote",
    }]}}
    monkeypatch.setattr(source_dejob, "http_get", lambda *a, **k: FakeResp(json_data=payload))
    res = source_dejob.search("solidity", limit=5)
    assert res.blocked is False
    assert len(res.jobs) == 1
    j = res.jobs[0]
    assert j.title == "Smart Contract Engineer"
    assert j.company == "GMGN"
    assert j.location == "HK"           # location 空字串時 fallback 用 base
    assert j.salary == "$7,000–10,000"
    assert j.url == "https://dejob.ai/jobDetail?id=7105"
    assert "DEX" in j.requirements
    assert j.work_mode == "remote"


def test_work_modes_parse_and_match():
    from app.sources import work_modes
    assert work_modes.parse_keys("onsite, remote,bogus,onsite") == ["onsite", "remote"]
    assert work_modes.parse_keys("") == []
    assert work_modes.match("onsite", []) is True          # 沒選 → 不限
    assert work_modes.match(None, ["remote"]) is False      # 未知 → 嚴格擋（07-10 改版：precision 優先）
    assert work_modes.match(None, []) is True               # 沒選時未知照樣通過
    assert work_modes.match("onsite", ["remote"]) is False  # 不符合 → 濾掉
    assert work_modes.match("remote", ["remote", "hybrid"]) is True


def test_work_modes_infer_and_effective():
    from app.sources import work_modes
    # 推斷：標題/地點關鍵字
    assert work_modes.infer("Senior QA Engineer (Remote)") == "remote"
    assert work_modes.infer("後端工程師", "台北・全遠端") == "remote"
    assert work_modes.infer("QA 工程師（在家工作）") == "remote"
    # hybrid 優先：hybrid 敘述常同時含遠端字樣
    assert work_modes.infer("工程師", "台北（部分遠端）") == "hybrid"
    assert work_modes.infer("Engineer, hybrid remote ok") == "hybrid"
    # 無信號 → None
    assert work_modes.infer("資深後端工程師", "台北市信義區") is None
    assert work_modes.infer(None, "") is None
    # effective：來源標示優先，None 才推斷
    assert work_modes.effective("onsite", "Remote OK") == "onsite"
    assert work_modes.effective(None, "Remote OK") == "remote"
    assert work_modes.effective(None, "純現場職缺", "台北") is None


def test_source_dejob_blocked_on_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("nope")
    monkeypatch.setattr(source_dejob, "http_get", boom)
    assert source_dejob.search("AI").blocked is True


def test_source_dejob_blocked_when_no_results(monkeypatch):
    monkeypatch.setattr(source_dejob, "http_get",
                         lambda *a, **k: FakeResp(json_data={"data": {"results": []}}))
    assert source_dejob.search("AI").blocked is True


def test_source_jobfrog_parses(monkeypatch):
    payload = {"data": [{
        "id": 13695, "company": "Google", "title": "Senior Product Design Engineer",
        "location": "Taipei, Taiwan", "posted_date": "2026-07-02",
        "website_link": "https://www.google.com/about/careers/applications/jobs/results/1",
        "summary_zh_hq": "職責：產品設計", "tech_stack": ["NX", "Creo"],
        "is_hybrid_remote": True,
    }], "meta": {"total": 1, "page": 1, "pageSize": 5, "hasMore": False}}
    monkeypatch.setattr(source_jobfrog, "http_get", lambda *a, **k: FakeResp(json_data=payload))
    res = source_jobfrog.search("engineer", limit=5)
    assert res.blocked is False
    assert len(res.jobs) == 1
    j = res.jobs[0]
    assert j.title == "Senior Product Design Engineer"
    assert j.company == "Google"
    assert j.location == "Taipei, Taiwan"
    assert j.salary is None                # 外商職缺頁一律不揭露薪資
    assert j.url == "https://www.google.com/about/careers/applications/jobs/results/1"
    assert "NX" in j.requirements
    assert j.work_mode == "hybrid"


def test_source_jobfrog_blocked_on_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("nope")
    monkeypatch.setattr(source_jobfrog, "http_get", boom)
    assert source_jobfrog.search("AI").blocked is True


def test_source_jobfrog_blocked_when_no_data(monkeypatch):
    monkeypatch.setattr(source_jobfrog, "http_get",
                         lambda *a, **k: FakeResp(json_data={"data": [], "meta": {}}))
    assert source_jobfrog.search("AI").blocked is True


def test_registry_search_all_aggregates(monkeypatch):
    from app.models import SearchResult
    from app.sources import registry
    monkeypatch.setattr(registry, "SEARCHABLE", {
        "104": lambda kw, limit=15, pages=1, area=None: SearchResult(source="104"),
        "yourator": lambda kw, limit=15, pages=1, area=None: SearchResult(source="yourator"),
    })
    results = registry.search_all("AI")
    assert [r.source for r in results] == ["104", "yourator"]


def test_registry_search_all_passes_pages(monkeypatch):
    """search_all 應把 pages 下傳給各來源。"""
    from app.models import SearchResult
    from app.sources import registry
    seen = {}

    def fake(kw, limit=15, pages=1, area=None):
        seen["pages"] = pages
        seen["area"] = area
        return SearchResult(source="104")

    monkeypatch.setattr(registry, "SEARCHABLE", {"104": fake})
    registry.search_all("AI", pages=3, area=["6001001000"])
    assert seen["pages"] == 3
    assert seen["area"] == ["6001001000"]          # area 也應下傳給來源


def test_all_real_sources_accept_area_param():
    # 回歸：search_all 以位置參數傳 (keywords, limit, pages, area) 給每個來源；
    # 任一來源的 search() 漏掉 area，每次搜尋都會丟 TypeError → 被當成 blocked
    # （LinkedIn 曾因此每次都顯示「暫無」）。確保所有真實來源都吃得下 area。
    import inspect

    from app.sources import registry
    for name, fn in registry.SEARCHABLE.items():
        params = list(inspect.signature(fn).parameters)
        assert "area" in params, f"{name} 的 search() 缺少 area 參數（會被 search_all 當成 blocked）"


def test_linkedin_search_url():
    from app.sources.registry import linkedin_search_url
    url = linkedin_search_url("AI 工程師")
    assert url.startswith("https://www.linkedin.com/jobs/search/")
    assert "Taiwan" in url


def test_regions_parse_and_codes():
    from app.sources import regions
    keys = regions.parse_keys("台北市, 高雄市,不存在的縣,台北市")  # 去空白、丟未知、去重
    assert keys == ["台北市", "高雄市"]
    assert regions.area_codes(keys) == ["6001001000", "6001016000"]
    assert regions.area_codes([]) == []


def test_regions_match_location():
    from app.sources import regions
    keys = ["台北市"]
    assert regions.match_location("台北市信義區", keys) is True
    assert regions.match_location("Taipei, Taiwan", keys) is True   # 英文別名
    assert regions.match_location("台中市西屯區", keys) is False     # 外地濾掉
    assert regions.match_location(None, keys) is True               # 缺地點寬鬆保留
    assert regions.match_location("台中市", []) is True             # 不限地區一律 True
