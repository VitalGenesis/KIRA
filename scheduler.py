"""Persistent SQLite task scheduler with atomic task claiming and V6 JSON migration."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config
from memory import memory as mem

_thread = None
_stop = threading.Event()
_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS = set()


def _now():
    return datetime.now(timezone.utc)


def _parse_datetime(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


def _connect():
    config.ensure_dirs()
    db_path = str(Path(config.SCHEDULES_DB).resolve())
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    if db_path not in _INITIALIZED_PATHS:
        with _INIT_LOCK:
            if db_path not in _INITIALIZED_PATHS:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS scheduled_jobs (
                        id TEXT PRIMARY KEY,
                        type TEXT NOT NULL,
                        prompt TEXT NOT NULL,
                        next_run TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        interval_seconds INTEGER,
                        last_result TEXT,
                        running INTEGER NOT NULL DEFAULT 0,
                        running_since TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_state ON scheduled_jobs(enabled,running,next_run);
                    CREATE TABLE IF NOT EXISTS scheduler_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """)
                conn.commit()
                _migrate_legacy(conn)
                _INITIALIZED_PATHS.add(db_path)
    return conn


def _migrate_legacy(conn):
    if conn.execute("SELECT 1 FROM scheduler_meta WHERE key='v6_json_imported'").fetchone():
        return
    source = Path(config.SCHEDULES_PATH)
    if source.exists():
        try:
            legacy = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            legacy = {}
        if isinstance(legacy, dict):
            now = _now().isoformat()
            for job_id, job in legacy.items():
                if not isinstance(job, dict):
                    continue
                try:
                    next_run = _parse_datetime(job.get("next_run") or now).isoformat()
                except (TypeError, ValueError):
                    next_run = now
                conn.execute("""INSERT OR IGNORE INTO scheduled_jobs
                    (id,type,prompt,next_run,enabled,interval_seconds,last_result,running,running_since,created_at)
                    VALUES(?,?,?,?,?,?,?,0,NULL,?)""",
                    (str(job.get("id", job_id)), str(job.get("type", "once")), str(job.get("prompt", "")),
                     next_run, int(bool(job.get("enabled", True))), job.get("interval_seconds"),
                     job.get("last_result"), now))
    conn.execute("INSERT OR REPLACE INTO scheduler_meta(key,value) VALUES('v6_json_imported',?)", (_now().isoformat(),))
    conn.commit()


def _as_dict(row):
    return {"id": row["id"], "type": row["type"], "prompt": row["prompt"],
            "next_run": row["next_run"], "enabled": bool(row["enabled"]),
            "interval_seconds": row["interval_seconds"], "last_result": row["last_result"],
            "running": bool(row["running"]), "running_since": row["running_since"]}


def add_once(prompt, run_at_iso):
    run_at = _parse_datetime(run_at_iso).isoformat()
    job_id = uuid.uuid4().hex[:12]
    with _connect() as conn:
        conn.execute("""INSERT INTO scheduled_jobs
            (id,type,prompt,next_run,enabled,interval_seconds,last_result,running,running_since,created_at)
            VALUES(?,?,?, ?,1,NULL,NULL,0,NULL,?)""",
            (job_id, "once", str(prompt), run_at, _now().isoformat()))
        return _as_dict(conn.execute("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)).fetchone())


def add_interval(prompt, seconds):
    seconds = max(5, int(seconds))
    next_run = (_now() + timedelta(seconds=seconds)).isoformat()
    job_id = uuid.uuid4().hex[:12]
    with _connect() as conn:
        conn.execute("""INSERT INTO scheduled_jobs
            (id,type,prompt,next_run,enabled,interval_seconds,last_result,running,running_since,created_at)
            VALUES(?,?,?, ?,1,?,NULL,0,NULL,?)""",
            (job_id, "interval", str(prompt), next_run, seconds, _now().isoformat()))
        return _as_dict(conn.execute("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)).fetchone())


def list_jobs():
    with _connect() as conn:
        return [_as_dict(row) for row in conn.execute("SELECT * FROM scheduled_jobs ORDER BY created_at DESC")]


def cancel(job_id):
    with _connect() as conn:
        cur = conn.execute("UPDATE scheduled_jobs SET enabled=0 WHERE id=?", (str(job_id),))
        if cur.rowcount == 0:
            raise ValueError("Tarea programada inexistente.")
        return _as_dict(conn.execute("SELECT * FROM scheduled_jobs WHERE id=?", (str(job_id),)).fetchone())


def _run_job(job):
    from agent import run
    memory = mem.load()
    result = run(job["prompt"], memory)
    mem.add_turn(memory, "user", "[TAREA PROGRAMADA] " + job["prompt"])
    mem.add_turn(memory, "assistant", result.get("reply", ""))
    mem.save(memory)
    return result


def _claim_due_jobs():
    now = _now()
    claimed = []
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT * FROM scheduled_jobs WHERE enabled=1 AND running=0").fetchall()
        for row in rows:
            try:
                if _parse_datetime(row["next_run"]) > now:
                    continue
            except (TypeError, ValueError):
                continue
            job = _as_dict(row)
            if job["type"] == "interval":
                interval = max(5, int(job["interval_seconds"] or 5))
                conn.execute("UPDATE scheduled_jobs SET running=1,running_since=?,next_run=? WHERE id=? AND running=0 AND enabled=1",
                             (now.isoformat(), (now + timedelta(seconds=interval)).isoformat(), job["id"]))
            else:
                # Once-only jobs are disabled when claimed, preventing duplicates after a restart.
                conn.execute("UPDATE scheduled_jobs SET running=1,running_since=?,enabled=0 WHERE id=? AND running=0 AND enabled=1",
                             (now.isoformat(), job["id"]))
            if conn.execute("SELECT changes()").fetchone()[0] == 1:
                job["running"] = True
                job["running_since"] = now.isoformat()
                claimed.append(job)
    return claimed


def _finish_job(job, result_text):
    with _connect() as conn:
        conn.execute("UPDATE scheduled_jobs SET running=0,running_since=NULL,last_result=? WHERE id=?",
                     (str(result_text)[:20000], job["id"]))


def _recover_stale_jobs():
    cutoff = (_now() - timedelta(hours=2)).isoformat()
    with _connect() as conn:
        conn.execute("""UPDATE scheduled_jobs SET running=0,running_since=NULL,
            last_result=COALESCE(last_result,'') || char(10) || '[RECOVERY] ejecución interrumpida.'
            WHERE running=1 AND running_since < ?""", (cutoff,))


def _tick():
    while not _stop.is_set():
        try:
            _recover_stale_jobs()
            for job in _claim_due_jobs():
                try:
                    result = _run_job(job)
                    text = result.get("reply", "")
                    if result.get("approval_required"):
                        text = "[PENDIENTE DE APROBACIÓN] " + text
                except Exception as exc:
                    text = f"ERROR: {type(exc).__name__}: {exc}"
                _finish_job(job, text)
        except Exception:
            # Retry transient database failures on the next tick rather than killing the worker.
            pass
        _stop.wait(1.0)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_tick, name="kira-scheduler", daemon=True)
    _thread.start()


def stop():
    _stop.set()
