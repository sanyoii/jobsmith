"""應用層 sqlite（與 LangGraph checkpoints 分開）：歷史投遞包 + 使用者記憶。

單一共用連線（check_same_thread=False 供 FastAPI threadpool 共用）；寫入用 LOCK 串行化。
路徑由 COPILOT_APP_DB 決定，預設 data/app.sqlite；測試用 :memory:（單例連線共用同一 in-memory DB）。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
LOCK = threading.RLock()
_conn: sqlite3.Connection | None = None


def _db_path() -> str:
    return os.environ.get("COPILOT_APP_DB", str(_ROOT / "data" / "app.sqlite"))


def _init(conn: sqlite3.Connection) -> None:
    fresh = not conn.execute("SELECT 1 FROM sqlite_master WHERE name='packages'").fetchone()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS packages("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, job_title TEXT, company TEXT, "
        "match_score INTEGER, jd_text TEXT, profile_json TEXT, package_json TEXT, approved INTEGER, "
        "thread_id TEXT)")
    # 既有資料庫缺欄位時補上：thread_id（冪等存檔用）、status（背景產生的生命週期）。
    cols = {r[1] for r in conn.execute("PRAGMA table_info(packages)").fetchall()}
    if "thread_id" not in cols:
        conn.execute("ALTER TABLE packages ADD COLUMN thread_id TEXT")
    if "status" not in cols:
        # 既有列視為已完成；新列先為 'running'，跑完有文件轉 'done'，無文件轉 'stopped'，失敗 'failed'。
        conn.execute("ALTER TABLE packages ADD COLUMN status TEXT DEFAULT 'done'")
    # 外部投遞結果（applied/interviewing/offer/rejected/ghosted；NULL=尚未投遞）。
    if "outcome_status" not in cols:
        conn.execute("ALTER TABLE packages ADD COLUMN outcome_status TEXT")
    if "outcome_updated_at" not in cols:
        conn.execute("ALTER TABLE packages ADD COLUMN outcome_updated_at TEXT")
    if "outcome_note" not in cols:
        conn.execute("ALTER TABLE packages ADD COLUMN outcome_note TEXT")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS user_memory("
        "id INTEGER PRIMARY KEY CHECK (id=1), profile_json TEXT, preferences_json TEXT, updated_at TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS searches("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, label TEXT, "
        "ai_count INTEGER, company_count INTEGER, profile_json TEXT, payload_json TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS resume_checks("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, label TEXT, resume_label TEXT, "
        "candidate_name TEXT, overall_score INTEGER, assessment_mode TEXT, fallback_reason TEXT, "
        "profile_json TEXT, assessment_json TEXT)")
    conn.commit()
    if fresh:
        migrate_evidence(conn)


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_db_path(), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init(_conn)
    return _conn


def init_db() -> None:
    get_conn()



def evidence_schema_ready(conn: sqlite3.Connection) -> bool:
    with LOCK:
        return "job_url" in {r[1] for r in conn.execute("PRAGMA table_info(packages)")} and all(
            conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            for name in ("job_verifications", "application_events"))


def require_evidence_schema(conn: sqlite3.Connection) -> None:
    if not evidence_schema_ready(conn):
        raise RuntimeError("查證功能尚未完成資料庫遷移；請先備份並取得遷移授權")


def migrate_evidence(conn: sqlite3.Connection) -> None:
    """Explicit opt-in for existing DBs. New empty DBs initialize this schema."""
    with LOCK, conn:
        if "job_url" not in {r[1] for r in conn.execute("PRAGMA table_info(packages)")}:
            conn.execute("ALTER TABLE packages ADD COLUMN job_url TEXT")
        conn.execute("CREATE TABLE IF NOT EXISTS job_verifications("
                     "job_key TEXT NOT NULL, criterion TEXT NOT NULL, data TEXT NOT NULL,"
                     "PRIMARY KEY(job_key,criterion))")
        conn.execute("CREATE TABLE IF NOT EXISTS application_events("
                     "sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,"
                     "package_id INTEGER NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,"
                     "request TEXT NOT NULL, data TEXT NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS application_events_package ON application_events(package_id,sequence)")
