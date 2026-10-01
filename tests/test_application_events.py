import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from app import server
from app.store import db, history, application_events as events
from app.store.job_verifications import utcnow


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db._init(conn)
    monkeypatch.setattr(db, "_conn", conn)
    yield conn
    conn.close()


def package():
    return history.create_running_package(uuid.uuid4().hex, "QA", "QA")


def request(status="applied", expected=None):
    return {"status": status, "expected_event_id": expected, "idempotency_key": str(uuid.uuid4()),
            "occurred_at": (utcnow() - timedelta(minutes=1)).isoformat(),
            "evidence": {"evidence_kind": "application_reference" if status == "applied" else "manual",
                         "evidence_text": "本人已取得申請編號", "reference": "QA-123", "confirmed_by_user": True}}


def test_success_retry_and_changed_key_conflict():
    pid = package()
    client = TestClient(server.app)
    body = request()
    first = client.patch(f"/api/history/{pid}/outcome", json=body)
    assert first.status_code == 200
    event = first.json()["event"]
    assert first.json()["package"]["evidence_status"] == "user_confirmed"
    assert client.patch(f"/api/history/{pid}/outcome", json=body).json()["event"]["event_id"] == event["event_id"]
    assert len(events.list_events(pid)["events"]) == 1
    body["evidence"]["evidence_text"] = "另一份申請"
    assert client.patch(f"/api/history/{pid}/outcome", json=body).status_code == 409
    assert history.get_package(pid)["outcome_status"] == "applied"


@pytest.mark.parametrize("bad", ["missing_evidence", "unconfirmed", "no_reference", "future", "no_timezone", "no_expected"])
def test_invalid_evidence_never_updates_projection(bad):
    pid = package()
    body = request()
    if bad == "missing_evidence": body.pop("evidence")
    if bad == "unconfirmed": body["evidence"]["confirmed_by_user"] = False
    if bad == "no_reference": body["evidence"].pop("reference")
    if bad == "future": body["occurred_at"] = (utcnow() + timedelta(days=1)).isoformat()
    if bad == "no_timezone": body["occurred_at"] = "2026-10-01T12:00:00"
    if bad == "no_expected": body.pop("expected_event_id")
    assert TestClient(server.app).patch(f"/api/history/{pid}/outcome", json=body).status_code == 422
    assert history.get_package(pid)["outcome_status"] is None
    assert events.list_events(pid)["events"] == []


def test_transaction_rollback(isolated):
    pid = package()
    isolated.execute("CREATE TRIGGER fail_projection BEFORE UPDATE OF outcome_status ON packages "
                     "BEGIN SELECT RAISE(ABORT, 'projection failed'); END")
    with pytest.raises(sqlite3.IntegrityError):
        events.record(pid, events.Outcome.model_validate(request()))
    assert events.list_events(pid)["events"] == []
    assert history.get_package(pid)["outcome_status"] is None


def test_legacy_status_note_and_evidence_do_not_mix():
    pid = package()
    history.set_outcome(pid, "applied", "legacy", update_note=True)
    assert history.get_package(pid)["evidence_status"] == "unverified"
    previous = history.get_package(pid)["current_event_id"]
    data = request(expected=previous)
    data["occurred_at"] = utcnow().isoformat()
    events.record(pid, events.Outcome.model_validate(data))
    history.set_outcome(pid, "applied", "new note", update_note=True)
    assert history.get_package(pid)["evidence_status"] == "user_confirmed"
    history.set_outcome(pid, "rejected")
    pkg = history.get_package(pid)
    assert pkg["evidence_status"] == "unverified" and pkg["outcome_note"] == "new note"


def test_conflicts_and_explicit_correction_keep_history():
    pid = package()
    first = events.record(pid, events.Outcome.model_validate(request()))
    stale = request("interviewing")
    with pytest.raises(events.EventError) as e:
        events.record(pid, events.Outcome.model_validate(stale))
    assert e.value.code == 409
    older = request("interviewing", first["event_id"])
    older["occurred_at"] = (utcnow() - timedelta(days=1)).isoformat()
    with pytest.raises(events.EventError):
        events.record(pid, events.Outcome.model_validate(older))
    offer = request("offer", first["event_id"])
    offer["occurred_at"] = utcnow().isoformat()
    latest = events.record(pid, events.Outcome.model_validate(offer))
    rejected = request("rejected", latest["event_id"])
    with pytest.raises(events.EventError):
        events.record(pid, events.Outcome.model_validate(rejected))
    rejected.update(correction=True, correction_reason="本人核對後更正")
    correction = events.record(pid, events.Outcome.model_validate(rejected))
    clear = request(None, correction["event_id"])
    clear.update(correction=True, correction_reason="誤記投遞結果")
    events.record(pid, events.Outcome.model_validate(clear))
    assert history.get_package(pid)["outcome_status"] is None
    assert len(events.list_events(pid)["events"]) == 4


def test_parallel_forms_only_one_wins():
    pid = package()
    def save(data):
        try:
            return events.record(pid, events.Outcome.model_validate(data))["event_id"]
        except events.EventError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [request(), request()]))
    assert results.count(409) == 1
    assert len(events.list_events(pid)["events"]) == 1


def test_missing_pagination_deletion_and_clear():
    client = TestClient(server.app)
    assert client.patch("/api/history/99999/outcome", json=request()).status_code == 404
    pid = package()
    events.record(pid, events.Outcome.model_validate(request()))
    history.set_outcome(pid, "interviewing")
    page = events.list_events(pid, limit=1)
    assert page["next_cursor"] is not None
    assert len(events.list_events(pid, cursor=page["next_cursor"])["events"]) == 1
    assert client.get(f"/api/history/{pid}/events?limit=101").status_code == 422
    history.delete_package(pid)
    assert db.get_conn().execute("SELECT count(*) FROM application_events").fetchone()[0] == 0
    pid = package()
    events.record(pid, events.Outcome.model_validate(request()))
    assert client.delete("/api/privacy-data").status_code == 200
    assert db.get_conn().execute("SELECT count(*) FROM application_events").fetchone()[0] == 0
