"""Application evidence and its package projection commit atomically."""
import json
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.store import db
from app.store.job_verifications import checked_time, safe_url, utcnow

Status = Literal["applied", "interviewing", "offer", "rejected", "ghosted"]


class EventError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    evidence_kind: Literal["success_page", "application_reference", "confirmation_email", "portal", "email", "manual"]
    evidence_text: str = Field(min_length=1, max_length=3000)
    source_url: str | None = None
    reference: str | None = Field(default=None, max_length=200)
    confirmed_by_user: Literal[True]

    @field_validator("confirmed_by_user", mode="before")
    @classmethod
    def confirmed(cls, v):
        if v is not True:
            raise ValueError("請本人明確確認憑證")
        return v

    @field_validator("source_url")
    @classmethod
    def url(cls, v):
        return safe_url(v) if v else None


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Status | None
    note: str | None = Field(default=None, max_length=3000)
    evidence: Evidence
    idempotency_key: uuid.UUID
    occurred_at: str
    expected_event_id: str | None
    correction: bool = False
    correction_reason: str = Field(default="", max_length=3000)

    @field_validator("occurred_at")
    @classmethod
    def time(cls, value):
        return checked_time(value).isoformat()

    @model_validator(mode="after")
    def complete(self):
        kinds = {"success_page", "application_reference", "confirmation_email"}
        if self.status == "applied" and self.evidence.evidence_kind not in kinds:
            raise ValueError("已投遞需要成功頁、申請編號或確認信")
        if self.status in {"interviewing", "offer", "rejected"} and self.evidence.evidence_kind not in {"portal", "email", "manual"}:
            raise ValueError("此結果需要通知或本人紀錄")
        if self.status == "ghosted" and self.evidence.evidence_kind != "manual":
            raise ValueError("無回音請記錄最後聯繫或觀察說明")
        if self.evidence.evidence_kind == "application_reference" and not self.evidence.reference:
            raise ValueError("請填申請編號")
        if (self.correction or self.status is None) and not self.correction_reason:
            raise ValueError("更正需要原因")
        if self.status is None and not self.correction:
            raise ValueError("清除結果需要明確更正")
        return self


def current(conn, pid):
    row = conn.execute("SELECT id,data FROM application_events WHERE package_id=? ORDER BY sequence DESC LIMIT 1", (pid,)).fetchone()
    return json.loads(row["data"]) if row else None


def decorate(conn, package):
    if not db.evidence_schema_ready(conn):
        return {**package, "job_url": None, "current_event_id": None, "evidence_status": "legacy_unverified"}
    event = current(conn, package["id"])
    package["current_event_id"] = event["event_id"] if event else None
    package["evidence_status"] = ("user_confirmed" if event.get("confirmed_by_user") else "unverified") if event else "legacy_unverified"
    return package


def record(pid, body: Outcome):
    conn = db.get_conn()
    db.require_evidence_schema(conn)
    request = body.model_dump(mode="json")
    payload = json.dumps(request, sort_keys=True, ensure_ascii=False)
    with db.LOCK, conn:
        pkg = conn.execute("SELECT * FROM packages WHERE id=?", (pid,)).fetchone()
        if not pkg:
            raise EventError(404, "找不到該投遞包")
        duplicate = conn.execute("SELECT package_id,request,data FROM application_events WHERE idempotency_key=?", (str(body.idempotency_key),)).fetchone()
        if duplicate:
            if duplicate["package_id"] != pid or duplicate["request"] != payload:
                raise EventError(409, "此重試識別已用於不同內容")
            return json.loads(duplicate["data"])
        prev = current(conn, pid)
        if body.expected_event_id != (prev["event_id"] if prev else None):
            raise EventError(409, "結果已由另一份表單修改，請重新讀取後確認")
        if prev and not body.correction:
            if checked_time(body.occurred_at) < checked_time(prev["effective_at"]):
                raise EventError(409, "事件早於目前結果，請明確更正")
            previous_status = prev["status"]
            order = {None: -1, "applied": 0, "interviewing": 1, "offer": 2}
            conflict = (previous_status in {"offer", "rejected", "ghosted"} and previous_status != body.status)
            conflict |= (body.status in order and previous_status in order and order[body.status] < order[previous_status])
            conflict |= (body.occurred_at == prev["effective_at"] and body.status != previous_status)
            if conflict:
                raise EventError(409, "結果倒退或與終態衝突，請明確更正")
        now = utcnow().isoformat()
        event = {**body.evidence.model_dump(), "event_id": uuid.uuid4().hex, "package_id": pid,
                 "status": body.status, "occurred_at": body.occurred_at, "recorded_at": now,
                 "effective_at": now if body.correction else body.occurred_at,
                 "correction": body.correction, "correction_reason": body.correction_reason,
                 "corrected_event_id": prev["event_id"] if body.correction and prev else None}
        conn.execute("INSERT INTO application_events(id,package_id,idempotency_key,request,data) VALUES(?,?,?,?,?)",
                     (event["event_id"], pid, str(body.idempotency_key), payload, json.dumps(event, ensure_ascii=False)))
        if "note" in body.model_fields_set:
            conn.execute("UPDATE packages SET outcome_status=?,outcome_updated_at=?,outcome_note=? WHERE id=?",
                         (body.status, now, body.note, pid))
        else:
            conn.execute("UPDATE packages SET outcome_status=?,outcome_updated_at=? WHERE id=?", (body.status, now, pid))
        return event


def legacy(pid, status, note=None, *, update_note=False):
    conn = db.get_conn()
    with db.LOCK, conn:
        pkg = conn.execute("SELECT * FROM packages WHERE id=?", (pid,)).fetchone()
        if not pkg:
            raise EventError(404, "找不到該投遞包")
        now = utcnow().isoformat()
        if pkg["outcome_status"] != status and db.evidence_schema_ready(conn):
            event = {"event_id": uuid.uuid4().hex, "package_id": pid, "status": status,
                     "occurred_at": now, "effective_at": now, "recorded_at": now,
                     "evidence_kind": "manual", "evidence_text": "", "confirmed_by_user": False}
            conn.execute("INSERT INTO application_events(id,package_id,idempotency_key,request,data) VALUES(?,?,?,?,?)",
                         (event["event_id"], pid, str(uuid.uuid4()), "legacy", json.dumps(event)))
        if update_note:
            conn.execute("UPDATE packages SET outcome_status=?,outcome_updated_at=?,outcome_note=? WHERE id=?", (status, now, note, pid))
        else:
            conn.execute("UPDATE packages SET outcome_status=?,outcome_updated_at=? WHERE id=?", (status, now, pid))


def list_events(pid, limit=50, cursor=0):
    conn = db.get_conn()
    db.require_evidence_schema(conn)
    with db.LOCK:
        if not conn.execute("SELECT id FROM packages WHERE id=?", (pid,)).fetchone():
            raise EventError(404, "找不到該投遞包")
        rows = conn.execute("SELECT sequence,data FROM application_events WHERE package_id=? AND sequence>? "
                            "ORDER BY sequence LIMIT ?", (pid, cursor, limit + 1)).fetchall()
        page = rows[:limit]
        return {"events": [json.loads(r["data"]) for r in page],
                "next_cursor": page[-1]["sequence"] if len(rows) > limit else None}
