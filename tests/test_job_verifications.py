import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from app import server
from app.store import db, history, application_events as events, job_verifications as verification

URL = "https://careers.example/jobs/QA?ref=A"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db._init(conn)
    monkeypatch.setattr(db, "_conn", conn)
    yield conn
    conn.close()


def check(value="pass", criterion="taiwan_eligibility", age=0):
    return {"criterion": criterion, "requirement": "可聘僱台灣居民", "value": value,
            "evidence": "雇主說明接受台灣居民", "source_url": URL,
            "checked_at": (verification.utcnow() - timedelta(days=age)).isoformat()}


def test_manual_checks_and_unknown_do_not_infer_remote():
    client = TestClient(server.app)
    result = client.post("/api/job-verifications/query", json={"job_urls": [URL]}).json()["jobs"][URL]
    assert result == {"checks": [], "summary": "仍有條件待確認"}
    assert client.put("/api/job-verifications", json={"job_url": URL, "check": check()}).status_code == 200
    unknown = {"criterion": "schedule", "requirement": "無輪班", "value": "unknown"}
    r = client.put("/api/job-verifications", json={"job_url": URL, "check": unknown})
    assert r.status_code == 200
    row = next(c for c in r.json()["checks"] if c["criterion"] == "schedule")
    assert row["checked_at"] is None and row["evidence"] == ""


@pytest.mark.parametrize("field", ["evidence", "source_url", "checked_at"])
def test_pass_requires_complete_evidence(field):
    data = check()
    data.pop(field)
    r = TestClient(server.app).put("/api/job-verifications", json={"job_url": URL, "check": data})
    assert r.status_code == 422
    assert verification.query([URL])[URL]["checks"] == []


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://name:secret@example.com/a", "https://example.com/\n", "https://example.com\\bad"])
def test_safe_urls_reject_unsafe_values(url):
    with pytest.raises(ValueError):
        verification.safe_url(url)


def test_current_snapshot_requirement_expiry_and_identity():
    for key in verification.CRITERIA:
        verification.save(verification.VerificationWrite(job_url=URL, check=check(criterion=key)))
    assert verification.query([URL])[URL]["summary"] == "五項均有符合依據"
    verification.save(verification.VerificationWrite(job_url=URL, check=check(age=8)))
    data = verification.query([URL])[URL]
    assert data["summary"] == "仍有條件待確認"
    expired = next(c for c in data["checks"] if c["criterion"] == "taiwan_eligibility")
    assert expired["expired"] and expired["value"] == "pass"
    updated = check()
    updated["requirement"] = "台灣全職直接聘僱"
    updated["value"] = "fail"
    verification.save(verification.VerificationWrite(job_url=URL, check=updated))
    assert verification.query([URL])[URL]["summary"] == "有條件不符"
    assert verification.query([URL.replace("ref=A", "ref=B")])[URL.replace("ref=A", "ref=B")]["checks"] == []
    assert verification.safe_url("HTTPS://CAREERS.EXAMPLE/jobs/QA?ref=A#section") == URL


def test_source_link_privacy_and_approval():
    pid = history.create_running_package("source-test", "QA", "QA", job_url=URL)
    client = TestClient(server.app)
    history.set_approved(pid, True)
    assert history.get_package(pid)["outcome_status"] is None
    assert history.get_package(pid)["job_url"] == URL
    assert client.patch(f"/api/history/{pid}/job-source", json={"job_url": None}).json()["job_url"] is None
    assert client.patch(f"/api/history/{pid}/job-source", json={"job_url": URL}).status_code == 200
    assert client.patch("/api/history/99999/job-source", json={"job_url": URL}).status_code == 404
    verification.save(verification.VerificationWrite(job_url=URL, check=check()))
    assert client.delete("/api/privacy-data").status_code == 200
    assert verification.query([URL])[URL]["checks"] == []


def test_migration_preserves_legacy_data_and_reopen(tmp_path, monkeypatch):
    path = tmp_path / "isolated.sqlite"
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE packages(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, job_title TEXT,"
                 "company TEXT, match_score INTEGER, jd_text TEXT, profile_json TEXT, package_json TEXT, approved INTEGER)")
    conn.execute("INSERT INTO packages(job_title,approved) VALUES('legacy',1)")
    conn.commit()
    db._init(conn)
    assert not db.evidence_schema_ready(conn)
    monkeypatch.setattr(db, "_conn", conn)
    assert TestClient(server.app).post("/api/job-verifications/query", json={"job_urls": [URL]}).status_code == 503
    assert history.get_package(1)["evidence_status"] == "legacy_unverified"
    history.set_outcome(1, "applied", "舊備註", update_note=True)
    db.migrate_evidence(conn)
    db.migrate_evidence(conn)
    assert history.get_package(1)["outcome_status"] == "applied"
    assert history.get_package(1)["outcome_note"] == "舊備註"
    assert history.get_package(1)["job_url"] is None
    history.set_job_source(1, URL)
    verification.save(verification.VerificationWrite(job_url=URL, check=check()))
    event = events.record(1, events.Outcome.model_validate({
        "status": "applied", "expected_event_id": None, "idempotency_key": str(uuid.uuid4()),
        "occurred_at": verification.utcnow().isoformat(),
        "evidence": {"evidence_kind": "application_reference", "evidence_text": "測試申請紀錄",
                     "reference": "REOPEN-001", "confirmed_by_user": True},
    }))
    conn.close()
    reopened = sqlite3.connect(path, check_same_thread=False)
    reopened.row_factory = sqlite3.Row
    monkeypatch.setattr(db, "_conn", reopened)
    assert history.get_package(1)["job_url"] == URL
    assert verification.query([URL])[URL]["checks"][0]["requirement"] == "可聘僱台灣居民"
    assert history.get_package(1)["current_event_id"] == event["event_id"]
    assert history.get_package(1)["evidence_status"] == "user_confirmed"
    assert events.list_events(1)["events"][0]["reference"] == "REOPEN-001"
    reopened.close()


def test_schema_check_serializes_shared_connection_reads_and_writes(isolated):
    class CheckedConnection:
        def execute(self, sql, *args):
            assert db.LOCK._is_owned(), "schema SQL must hold shared connection lock"
            return isolated.execute(sql, *args)

    assert db.evidence_schema_ready(CheckedConnection())
    pid = history.create_running_package("concurrent-schema", "QA", "QA")

    def access(index):
        for _ in range(15):
            if index % 3 == 0:
                verification.save(verification.VerificationWrite(job_url=URL, check=check()))
            elif index % 3 == 1:
                assert len(verification.query([URL])[URL]["checks"]) <= 1
            else:
                assert events.list_events(pid)["events"] == []
            assert db.evidence_schema_ready(isolated)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(access, range(16)))
