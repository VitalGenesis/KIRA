"""Persistent task plans backed by SQLite, with a one-time V6 JSON import."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config

_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS = set()


def _connect():
    config.ensure_dirs()
    db_path = str(Path(config.PLANS_DB).resolve())
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    if db_path not in _INITIALIZED_PATHS:
        with _INIT_LOCK:
            if db_path not in _INITIALIZED_PATHS:
                conn.execute("PRAGMA journal_mode=WAL")
                _schema(conn)
                _migrate_legacy(conn)
                _INITIALIZED_PATHS.add(db_path)
    return conn


def _schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS plans (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plan_steps (
            plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            step_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            PRIMARY KEY (plan_id, step_id)
        );
        CREATE INDEX IF NOT EXISTS idx_plans_status_created ON plans(status, created);
        CREATE TABLE IF NOT EXISTS planner_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    conn.commit()


def _migrate_legacy(conn):
    if conn.execute("SELECT 1 FROM planner_meta WHERE key='v6_json_imported'").fetchone():
        return
    source = Path(config.PLANS_PATH)
    if source.exists():
        try:
            legacy = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            legacy = {}
        if isinstance(legacy, dict):
            for pid, plan in legacy.items():
                if not isinstance(plan, dict) or not pid:
                    continue
                actual_id = str(plan.get("id", pid))
                conn.execute(
                    "INSERT OR IGNORE INTO plans(id,title,status,created) VALUES(?,?,?,?)",
                    (actual_id, str(plan.get("title", "Plan migrado")),
                     str(plan.get("status", "pending")),
                     str(plan.get("created", datetime.now(timezone.utc).isoformat()))),
                )
                for index, step in enumerate(plan.get("steps", []), 1):
                    if not isinstance(step, dict):
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO plan_steps(plan_id,step_id,text,status,result_json) VALUES(?,?,?,?,?)",
                        (actual_id, int(step.get("id", index)), str(step.get("text", "")),
                         str(step.get("status", "pending")),
                         json.dumps(step.get("result"), ensure_ascii=False, default=str)),
                    )
    conn.execute("INSERT OR REPLACE INTO planner_meta(key,value) VALUES('v6_json_imported',?)",
                 (datetime.now(timezone.utc).isoformat(),))
    conn.commit()


def _safe_json(raw):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw


def _read_plan(conn, plan_id):
    row = conn.execute("SELECT id,title,status,created FROM plans WHERE id=?", (str(plan_id),)).fetchone()
    if not row:
        return None
    steps = conn.execute(
        "SELECT step_id,text,status,result_json FROM plan_steps WHERE plan_id=? ORDER BY step_id",
        (str(plan_id),),
    ).fetchall()
    return {
        "id": row["id"], "title": row["title"], "status": row["status"], "created": row["created"],
        "steps": [{"id": s["step_id"], "text": s["text"], "status": s["status"],
                   "result": _safe_json(s["result_json"])} for s in steps],
    }


def create(title, steps):
    steps = [str(step).strip() for step in steps if str(step).strip()]
    if not steps:
        raise ValueError("El plan necesita pasos.")
    if len(steps) > config.MAX_PLAN_STEPS:
        raise ValueError("Demasiados pasos.")
    plan_id = uuid.uuid4().hex[:12]
    created = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute("INSERT INTO plans(id,title,status,created) VALUES(?,?,?,?)",
                     (plan_id, str(title).strip(), "pending", created))
        conn.executemany(
            "INSERT INTO plan_steps(plan_id,step_id,text,status,result_json) VALUES(?,?,?,?,NULL)",
            [(plan_id, index, step, "pending") for index, step in enumerate(steps, 1)],
        )
        return _read_plan(conn, plan_id)


def list_plans():
    with _connect() as conn:
        plan_ids = [row[0] for row in conn.execute("SELECT id FROM plans ORDER BY created DESC")]
        return [plan for pid in plan_ids if (plan := _read_plan(conn, pid)) is not None]


def get(plan_id):
    with _connect() as conn:
        return _read_plan(conn, plan_id)


def update(plan_id, step_id, status, result=None):
    status = str(status)
    if status not in {"pending", "running", "done", "failed"}:
        raise ValueError(f"Estado inválido: {status}")
    result_json = json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM plans WHERE id=?", (str(plan_id),)).fetchone():
            raise ValueError("Plan inexistente.")
        cur = conn.execute(
            "UPDATE plan_steps SET status=?,result_json=? WHERE plan_id=? AND step_id=?",
            (status, result_json, str(plan_id), int(step_id)),
        )
        if cur.rowcount == 0:
            raise ValueError("Paso inexistente.")
        states = [row[0] for row in conn.execute(
            "SELECT status FROM plan_steps WHERE plan_id=?", (str(plan_id),))]
        if states and all(state == "done" for state in states):
            plan_status = "done"
        elif any(state == "failed" for state in states):
            plan_status = "failed"
        elif any(state in {"running", "done"} for state in states):
            plan_status = "running"
        else:
            plan_status = "pending"
        conn.execute("UPDATE plans SET status=? WHERE id=?", (plan_status, str(plan_id)))
        return _read_plan(conn, plan_id)


def next_step(plan_id):
    plan = get(plan_id)
    if not plan:
        return None
    return next((step for step in plan["steps"] if step["status"] in {"pending", "running"}), None)


def execute(plan_id):
    plan = get(plan_id)
    if not plan:
        raise ValueError("Plan inexistente.")
    from agent import run
    from memory import memory as mem
    outputs = []
    for step in plan["steps"]:
        if step["status"] == "done":
            outputs.append({"step": step["id"], "status": "done", "result": step.get("result")})
            continue
        update(plan_id, step["id"], "running")
        memory = mem.load()
        result = run(step["text"], memory)
        mem.add_turn(memory, "user", f"[PLAN {plan_id}] {step['text']}")
        mem.add_turn(memory, "assistant", result.get("reply", ""))
        mem.save(memory)
        has_error = any(
            isinstance(event, dict) and isinstance(event.get("result"), dict) and event["result"].get("error")
            for event in result.get("tool_events", [])
        )
        pending_approval = bool(result.get("approval_required"))
        state = "failed" if has_error else ("running" if pending_approval else "done")
        update(plan_id, step["id"], state, result.get("reply"))
        outputs.append({"step": step["id"], "status": state, "reply": result.get("reply")})
        if state != "done":
            break
        plan = get(plan_id)
    return {"plan": get(plan_id), "outputs": outputs}
