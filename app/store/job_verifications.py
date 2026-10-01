"""Manual job-condition records. No web fetches or model calls."""
import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.store import db

CRITERIA = ("taiwan_eligibility", "work_mode", "schedule", "salary", "employment_type")


def utcnow():
    return datetime.now(timezone.utc)


def safe_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError("請提供有效 HTTPS 來源，勿包含空白或控制字元")
    u = urlsplit(value)
    if u.scheme.lower() != "https" or not u.hostname or u.username is not None or u.password is not None:
        raise ValueError("來源須為 HTTPS，不能包含帳號密碼")
    try:
        u.port
    except ValueError:
        raise ValueError("來源網址無效") from None
    if chr(92) in value:
        raise ValueError("來源網址無效")
    return urlunsplit(("https", u.netloc.lower(), u.path, u.query, ""))


def checked_time(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError()
        dt = dt.astimezone(timezone.utc)
    except (ValueError, AttributeError, OverflowError):
        raise ValueError("請提供包含時區的有效時間") from None
    if dt > utcnow() + timedelta(minutes=5):
        raise ValueError("事件時間不能在未來")
    return dt


class JobCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    criterion: Literal["taiwan_eligibility", "work_mode", "schedule", "salary", "employment_type"]
    requirement: str = Field(min_length=1, max_length=500)
    value: Literal["pass", "fail", "unknown"]
    evidence: str = Field(default="", max_length=3000)
    source_url: str = ""
    checked_at: str | None = None

    @field_validator("source_url")
    @classmethod
    def url(cls, value):
        return safe_url(value) if value else ""

    @field_validator("checked_at")
    @classmethod
    def time(cls, value):
        return checked_time(value).isoformat() if value else None

    @model_validator(mode="after")
    def complete(self):
        if self.value != "unknown" and not (self.evidence and self.source_url and self.checked_at):
            raise ValueError("符合或不符合都需要依據、來源與查證時間")
        return self


class VerificationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_url: str
    check: JobCheck

    @field_validator("job_url")
    @classmethod
    def url(cls, value):
        return safe_url(value)


class VerificationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_urls: list[str] = Field(max_length=100)

    @field_validator("job_urls")
    @classmethod
    def urls(cls, values):
        return [safe_url(v) for v in values]


def summarize(checks):
    at = utcnow()
    rows = []
    for check in checks:
        row = dict(check)
        row["expired"] = bool(row.get("checked_at") and at - checked_time(row["checked_at"]) > timedelta(days=7))
        rows.append(row)
    active = [r for r in rows if not r["expired"] and r.get("checked_at")]
    if any(r["value"] == "fail" for r in active):
        summary = "有條件不符"
    elif len(active) == len(CRITERIA) and all(r["value"] == "pass" for r in active):
        summary = "五項均有符合依據"
    else:
        summary = "仍有條件待確認"
    return {"checks": rows, "summary": summary}


def query(job_urls):
    conn = db.get_conn()
    db.require_evidence_schema(conn)
    with db.LOCK:
        result = {}
        for url in dict.fromkeys(job_urls):
            rows = conn.execute("SELECT data FROM job_verifications WHERE job_key=?", (url,)).fetchall()
            result[url] = summarize([json.loads(r[0]) for r in rows])
    return result


def save(body: VerificationWrite):
    conn = db.get_conn()
    db.require_evidence_schema(conn)
    data = {**body.check.model_dump(), "saved_at": utcnow().isoformat()}
    with db.LOCK, conn:
        conn.execute("INSERT INTO job_verifications(job_key,criterion,data) VALUES(?,?,?) "
                     "ON CONFLICT(job_key,criterion) DO UPDATE SET data=excluded.data",
                     (body.job_url, body.check.criterion, json.dumps(data, ensure_ascii=False)))
    return query([body.job_url])[body.job_url]
