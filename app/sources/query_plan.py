"""Bounded role aliases and source-specific query planning; no AI calls."""
from collections import OrderedDict

MAX_QUERIES = 5
BILINGUAL = {"104", "yourator", "cake"}
# These are search aliases, not new career preferences or skill-derived roles.
ROLE_ALIASES = (
    (("QA 經理", "QA 主管", "測試經理", "測試主管", "品保經理", "品保主管", "品質保證經理", "品質保證主管", "QA Manager", "Test Manager", "Testing Manager", "Quality Assurance Manager"),
     ("QA Manager", "Test Manager", "Quality Assurance Manager")),
    (("技術支援工程師", "技術支持工程師", "Technical Support Engineer", "Support Engineer"),
     ("Technical Support Engineer", "Support Engineer")),
    (("QA 工程師", "Quality Assurance Engineer", "QA Engineer"), ("QA Engineer", "Quality Assurance Engineer")),
    (("測試工程師", "軟體測試工程師", "Software Test Engineer", "Test Engineer"), ("Software Test Engineer",)),
    (("自動化測試工程師", "自動化測試", "QA Automation", "QA Automation Engineer", "Test Automation Engineer"),
     ("QA Automation Engineer", "Test Automation Engineer")),
    (("SDET",), ("SDET",)),
)


def unique(values):
    result, seen = [], set()
    for value in values:
        value = value.strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return result


def source_queries(queries, source, custom=()):
    # Literal custom input is always preserved; known translations supplement it.
    selected = unique(custom)
    primary, extra = [], []
    for query in unique(queries):
        group = next((group for group in ROLE_ALIASES
                      if query.casefold() in {v.casefold() for v in group[0]}), None)
        if group:
            primary.append(group[0][0] if source in BILINGUAL else group[1][0])
            extra.extend(group[1] if source in BILINGUAL else group[1][1:])
        else:
            primary.append(query)
    terms = unique(selected + primary + extra)[:MAX_QUERIES]
    if source == "web3career":
        known_qa = {v.casefold() for group in ROLE_ALIASES if group[0][0] not in {"技術支援工程師", "QA 經理"} for v in (*group[0], *group[1])}
        terms = unique(["quality assurance" if term.casefold() in known_qa and term.casefold() not in {v.casefold() for v in custom} else term for term in terms])
    return terms


def plan_queries(queries, sources, custom=()):
    return {source: source_queries(queries, source, custom) for source in sources}


def grouped_requests(plan):
    groups = OrderedDict()
    for source, queries in plan.items():
        # Full-list source: all phrases evaluated after a single fetch.
        key = tuple(queries) if source == "defijobs" and len(queries) > 1 else None
        if key:
            groups.setdefault(key, []).append(source)
        else:
            for query in queries:
                groups.setdefault(query, []).append(source)
    return [(list(query) if isinstance(query, tuple) else query, sources)
            for query, sources in groups.items()]


def english_query(query):
    return source_queries([query], "linkedin")[0] if query else ""
