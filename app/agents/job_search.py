"""職缺探索 agent：從履歷推導搜尋關鍵字、對搜到的職缺依履歷排序。"""
import re

from pydantic import BaseModel, Field, field_validator

from app.agents.skill_lexicon import extract_skills
from app.agents.resume_eval import QA_MANAGEMENT_RE
from app.llm import get_llm
from app.models import JobMatch, JobPosting, Profile, coerce_str, coerce_str_list

QUERY_SYSTEM = (
    "你是台灣求職顧問。根據求職者背景，產出 1-3 個最適合在台灣求職網站（104/Cake/Yourator）"
    "搜尋的『職務關鍵字』（例如『QA 工程師』『自動化測試』『後端工程師』『資料分析師』）。"
    "優先依據明示期望職務與履歷主要職稱，再以技能細化，不要太長；QA Manager 目標必須搜尋 QA／測試管理職，不能降成工程師。"
    "Python、API、SQL 是工具或測試範圍，不能單獨推定後端職務；QA 履歷應搜尋 QA／測試相關職務；Technical Support 履歷應搜尋技術支援職務，除錯工具不代表開發職務。"
)

RANK_SYSTEM = (
    "你是台灣求職顧問。下面是求職者背景與一批職缺清單（每筆有索引）。"
    "請對『每一筆』職缺評估與求職者的適配分數（fit_score 0-100），"
    "並列出符合點(matched)、落差點(gaps)、一句適配理由(reason)。"
    "務實評分：技能/年資/領域吻合度高才給高分。全程繁體中文。"
)


class SearchQueries(BaseModel):
    queries: list[str] = Field(default_factory=list, description="1-3 個搜尋關鍵字詞")

    # codex/gpt 可能把 queries 回成 null 或單一字串，先收斂避免結構化解析失敗。
    @field_validator("queries", mode="before")
    @classmethod
    def _coerce_queries(cls, v):
        return coerce_str_list(v)


class _RankItem(BaseModel):
    index: int = Field(description="對應職缺清單的索引")
    fit_score: int = Field(ge=0, le=100)
    matched: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    reason: str = ""

    @field_validator("matched", "gaps", mode="before")
    @classmethod
    def _coerce_lists(cls, v):
        return coerce_str_list(v)

    @field_validator("reason", mode="before")
    @classmethod
    def _coerce_reason(cls, v):
        return coerce_str(v)


class _RankResult(BaseModel):
    rankings: list[_RankItem] = Field(default_factory=list)

    @field_validator("rankings", mode="before")
    @classmethod
    def _coerce_rankings(cls, v):
        return v if v is not None else []


def _profile_brief(profile: Profile) -> str:
    """精簡的求職者描述（不含 raw_text 全文，控制 prompt 大小）。"""
    return (
        f"姓名：{profile.name}\n定位：{profile.summary}\n"
        f"技能：{'、'.join(profile.skills) or '（無）'}\n"
        f"經歷：{'；'.join(profile.experiences) or '（無）'}\n"
        f"年資：{profile.years_experience}\n"
        f"期望職務：{'、'.join(profile.preferred_roles) or '（無）'}"
    )


_QA_QUERY = re.compile(r"\b(?:qa|quality assurance|sdet)\b|(?:manual|software|automation) test(?:ing)?|test automation|測試工程師|自動化測試|軟體測試|品保工程師", re.IGNORECASE)


def _qa_management_queries(profile: Profile) -> list[str]:
    roles = [r.strip() for r in profile.preferred_roles if r.strip()]
    if roles:
        return list(dict.fromkeys(roles))[:3] if all(QA_MANAGEMENT_RE.search(r) for r in roles) else []
    if QA_MANAGEMENT_RE.match(profile.summary.strip().removeprefix("Senior ").removeprefix("資深")):
        return ["QA 經理"]
    return []


def _qa_queries(profile: Profile) -> list[str]:
    roles = [r.strip() for r in profile.preferred_roles if r.strip()]
    # Explicit mixed targets remain available rather than enforcing a single career.
    if roles:
        return list(dict.fromkeys(roles))[:3] if all(_QA_QUERY.search(r) for r in roles) else []
    if re.search(r"^(?:(?:senior|junior|lead|staff|資深)\s+)?(?:qa\b|quality assurance\b|sdet\b|(?:software |automation )?test(?:ing)? engineer\b|測試工程師|品保工程師)", profile.summary.strip(), re.IGNORECASE):
        result = ["QA 工程師", "測試工程師"]
        if re.search(r"automation|selenium|playwright|robot framework|自動化", " ".join(profile.skills), re.IGNORECASE):
            result.append("自動化測試工程師")
        return result
    return []


_SUPPORT_QUERY = re.compile(r"\b(?:(?:technical|application|customer) support(?: engineer)?|support engineer)\b|技術支援|技術支持", re.IGNORECASE)


def _support_queries(profile: Profile) -> list[str]:
    roles = [r.strip() for r in profile.preferred_roles if r.strip()]
    if roles:
        return list(dict.fromkeys(roles))[:3] if all(_SUPPORT_QUERY.search(r) for r in roles) else []
    if re.search(r"^(?:(?:senior|junior|lead|staff|資深)\s+)?(?:(?:technical|application|customer) support engineer\b|技術支援工程師|技術支持工程師)", profile.summary.strip(), re.IGNORECASE):
        return ["技術支援工程師"]
    return []


def _fallback_queries(profile: Profile) -> list[str]:
    """LLM 結構化輸出失敗時的本機查詢詞備援。"""
    management = _qa_management_queries(profile)
    if management:
        return management
    qa = _qa_queries(profile)
    if qa:
        return qa
    support = _support_queries(profile)
    if support:
        return support
    candidates: list[str] = []
    candidates.extend(str(r).strip() for r in (profile.preferred_roles or []) if str(r).strip())
    skills = [str(s).strip() for s in (profile.skills or []) if str(s).strip()]
    skill_blob = " ".join(skills).lower()
    summary = (profile.summary or "").lower()
    if any(k in skill_blob for k in ("llm", "rag", "langchain", "langgraph", "openai")):
        candidates.append("AI 工程師")
    if "python" in skill_blob:
        candidates.append("Python 後端")
    if any(k in summary for k in ("data", "資料", "數據")):
        candidates.append("資料工程師")
    candidates.extend(skills[:3])
    out = []
    for c in candidates:
        if c and c not in out:
            out.append(c)
    return out[:3] or ["工程師"]


def derive_queries(profile: Profile) -> list[str]:
    """從履歷推導搜尋關鍵字（cheap 分層）。"""
    try:
        llm = get_llm("cheap").with_structured_output(SearchQueries)
        out = llm.invoke([("system", QUERY_SYSTEM), ("human", _profile_brief(profile))])
        queries = [q.strip() for q in out.queries if q.strip()][:3]
    except Exception:
        return _fallback_queries(profile)
    management = _qa_management_queries(profile)
    if management:
        relevant = [q for q in queries if QA_MANAGEMENT_RE.search(q)]
        return relevant or management
    qa = _qa_queries(profile)
    if qa:
        relevant = [q for q in queries if _QA_QUERY.search(q)]
        return relevant or qa
    support = _support_queries(profile)
    if support:
        relevant = [q for q in queries if _SUPPORT_QUERY.search(q)]
        return relevant or support
    if queries:
        return queries
    return _fallback_queries(profile)


_RANK_INPUT_MAX = 50  # 送 LLM 排序的職缺上限（控 prompt 大小/成本）；超出者不送排序


def _job_blob(j: JobPosting) -> str:
    return " ".join([
        j.title or "", j.company or "", j.location or "", j.snippet or "",
        " ".join(str(r) for r in (j.requirements or [])), j.raw_text or "",
    ]).lower()


def _profile_blob(profile: Profile) -> str:
    return " ".join([
        profile.summary or "", " ".join(profile.skills or ""),
        " ".join(profile.experiences or ""), " ".join(profile.preferred_roles or ""),
    ])


def qa_role_relation(job: JobPosting) -> str:
    title = job.title.lower()
    if re.search(r"penetration|滲透|硬體|hardware|manufacturing|製造|機械", title):
        return "unknown"
    if re.search(r"\b(?:qa|sdet)\b|software test|test automation|automation test|軟體測試|自動化測試", title):
        return "related"
    if "quality assurance" in title or "測試工程師" in title:
        context = " ".join([job.snippet or "", job.raw_text, " ".join(job.requirements)]).lower()
        if re.search(r"software|api|selenium|playwright|軟體|web|pytest", context):
            return "related"
        return "unknown"
    if re.search(r"backend|back.end|frontend|front.end|full.stack|後端|前端|全端|sales|行銷", title):
        return "unrelated"
    return "unknown"


def _check_role_matches(profile: Profile, matches: list[JobMatch]) -> list[JobMatch]:
    if not _qa_queries(profile):
        return matches
    checked = []
    for match in matches:
        relation = qa_role_relation(match.job)
        if relation != "related":
            message = ("職稱偏向其他職務；共同工具不代表符合 QA 職務。" if relation == "unrelated"
                       else "職務待確認：現有資訊不足以判斷為軟體 QA。")
            match = match.model_copy(update={"fit_score": min(match.fit_score, 30 if relation == "unrelated" else 59),
                                            "reason": message + " " + match.reason})
        checked.append(match)
    checked.sort(key=lambda m: (-m.fit_score, m.job.url))
    return checked


def _fallback_rank_jobs(profile: Profile, jobs: list[JobPosting], top_k: int | None = None) -> list[JobMatch]:
    """LLM 排序失敗時仍給使用者可用列表：以技能/職稱關鍵字重疊估分。"""
    have_skills = set(extract_skills(_profile_blob(profile)))
    raw_skills = [str(s).strip() for s in (profile.skills or []) if str(s).strip()]
    roles = [str(r).strip().lower() for r in (profile.preferred_roles or []) if str(r).strip()]
    matches: list[JobMatch] = []
    for job in jobs:
        blob = _job_blob(job)
        job_skills = set(extract_skills(blob))
        skill_hits = sorted(have_skills & job_skills)
        raw_hits = [s for s in raw_skills if s.lower() in blob and s not in skill_hits]
        role_hits = [r for r in roles if r and r in blob]
        score = 35 + min(40, 12 * len(skill_hits) + 8 * len(raw_hits)) + min(15, 15 * len(role_hits))
        if not skill_hits and not raw_hits and not role_hits:
            score = 30
        gaps = sorted(job_skills - have_skills)[:6]
        reason = "AI 排序暫時不可用，已改用本機技能與職稱關鍵字比對。"
        matches.append(JobMatch(
            job=job,
            fit_score=min(90, score),
            matched=[*skill_hits, *raw_hits, *role_hits],
            gaps=gaps,
            reason=reason,
        ))
    matches.sort(key=lambda m: (-m.fit_score, m.job.url or (m.job.title + m.job.company)))
    matches = _check_role_matches(profile, matches)
    return matches if top_k is None else matches[:top_k]


def fallback_rank_jobs(profile: Profile, jobs: list[JobPosting], top_k: int | None = None) -> list[JobMatch]:
    """Public fallback scorer for callers that need to recover from batch-level failures."""
    return _fallback_rank_jobs(profile, jobs, top_k)


def rank_jobs(profile: Profile, jobs: list[JobPosting], top_k: int | None = None) -> list[JobMatch]:
    """以一次 LLM 呼叫對職缺評分排序（standard 分層）。

    top_k=None（預設）回傳全部排序結果（不截斷，由前端分頁）；為控 prompt，最多送
    _RANK_INPUT_MAX 筆給 LLM 排序，超出部分以 fit_score=0 附在後面。
    """
    if not jobs:
        return []
    ranked_pool, overflow = jobs[:_RANK_INPUT_MAX], jobs[_RANK_INPUT_MAX:]
    jobs = ranked_pool
    listing = "\n".join(
        f"[{i}] {j.title} @ {j.company}｜{j.location or ''}｜{(j.snippet or '')[:120]}"
        for i, j in enumerate(jobs)
    )
    llm = get_llm("standard", max_tokens=4000, timeout=90).with_structured_output(_RankResult)
    human = f"【求職者】\n{_profile_brief(profile)}\n\n【職缺清單】\n{listing}"
    try:
        out = llm.invoke([("system", RANK_SYSTEM), ("human", human)])
    except Exception:
        return _fallback_rank_jobs(profile, jobs + overflow, top_k)
    if not out.rankings:
        return _fallback_rank_jobs(profile, jobs + overflow, top_k)
    by_idx = {r.index: r for r in out.rankings}

    matches: list[JobMatch] = []
    for i, job in enumerate(jobs):
        r = by_idx.get(i)
        if r is not None:
            matches.append(JobMatch(job=job, fit_score=r.fit_score,
                                    matched=r.matched, gaps=r.gaps, reason=r.reason))
        else:
            matches.append(JobMatch(job=job, fit_score=0, reason="未評分"))
    # 穩定排序：同分時以 url 決定先後，讓同一批職缺的顯示順序可重現（不隨並行/批次到達順序變動）。
    matches.sort(key=lambda m: (-m.fit_score, m.job.url or (m.job.title + m.job.company)))
    # 超出排序上限的職缺仍保留（附在後面、未評分），確保「不設限」顯示全部
    matches.extend(JobMatch(job=j, fit_score=0, reason="未評分") for j in overflow)
    matches = _check_role_matches(profile, matches)
    return matches if top_k is None else matches[:top_k]
