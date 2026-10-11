"""SQLite semantic memory with optional sqlite-vec nearest-neighbour index.

The canonical memories and JSON embeddings remain portable. With sqlite-vec
installed, embeddings are indexed in vec0 tables grouped by dimension and
searched using KNN. Existing V6 embeddings are indexed lazily in batches.
FTS5 and bounded cosine-scan fallbacks keep memory useful if the extension or
embedding model is unavailable.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone

import requests
import config

_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS = set()


def _connect():
    config.ensure_dirs()
    db_path = str(Path(config.SEMANTIC_DB).resolve())
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    if db_path not in _INITIALIZED_PATHS:
        with _INIT_LOCK:
            if db_path not in _INITIALIZED_PATHS:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY, text TEXT NOT NULL, kind TEXT NOT NULL,
                    created TEXT NOT NULL, embedding TEXT)""")
                conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, content='memories', content_rowid='id')")
                conn.execute("""CREATE TABLE IF NOT EXISTS vector_index_status (
                    memory_id INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
                    dimension INTEGER NOT NULL, indexed_at TEXT NOT NULL)""")
                conn.execute("CREATE TABLE IF NOT EXISTS semantic_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.commit()
                _INITIALIZED_PATHS.add(db_path)
    return conn


def _embed(text: str):
    if not config.EMBED_MODEL:
        return None
    try:
        response = requests.post(
            f"{config.OLLAMA_URL}/api/embed",
            json={"model": config.EMBED_MODEL, "input": text},
            timeout=60,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        embeddings = data.get("embeddings")
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
            vector = [float(value) for value in embeddings[0]]
            return vector if vector and all(math.isfinite(value) for value in vector) else None
        # Compatibility with older Ollama embedding endpoint responses.
        embedding = data.get("embedding")
        if isinstance(embedding, list):
            vector = [float(value) for value in embedding]
            return vector if vector and all(math.isfinite(value) for value in vector) else None
    except Exception:
        return None
    return None


def _load_vec(conn):
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
        return sqlite_vec
    except Exception:
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass
        return None


def _vector_table_name(dimension):
    dimension = int(dimension)
    if dimension <= 0 or dimension > 65536:
        raise ValueError("Dimensión de embedding no válida.")
    return f"vec_memories_{dimension}"


def _ensure_vector_table(conn, dimension):
    table = _vector_table_name(dimension)
    # Table identifier is built exclusively from a validated integer dimension.
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} "
        f"USING vec0(embedding float[{int(dimension)}] distance_metric=cosine)"
    )
    return table


def _index_one(conn, sqlite_vec, memory_id, vector):
    if not vector:
        return False
    try:
        dimension = len(vector)
        table = _ensure_vector_table(conn, dimension)
        existing = conn.execute(
            "SELECT dimension FROM vector_index_status WHERE memory_id=?", (int(memory_id),)
        ).fetchone()
        if existing and int(existing["dimension"]) == dimension:
            return True
        if existing:
            old_table = _vector_table_name(int(existing["dimension"]))
            try:
                conn.execute(f"DELETE FROM {old_table} WHERE rowid=?", (int(memory_id),))
            except sqlite3.Error:
                pass
        blob = sqlite_vec.serialize_float32(vector)
        # Safe idempotency if a prior process inserted the vector but exited
        # before recording vector_index_status.
        conn.execute(f"DELETE FROM {table} WHERE rowid=?", (int(memory_id),))
        conn.execute(f"INSERT INTO {table}(rowid,embedding) VALUES(?,?)", (int(memory_id), blob))
        conn.execute(
            "INSERT OR REPLACE INTO vector_index_status(memory_id,dimension,indexed_at) VALUES(?,?,?)",
            (int(memory_id), dimension, datetime.now(timezone.utc).isoformat()),
        )
        return True
    except Exception:
        return False


def _backfill_vector_index(conn, sqlite_vec, batch_size=500):
    total_indexed = 0
    while True:
        rows = conn.execute("""SELECT m.id,m.embedding FROM memories m
            LEFT JOIN vector_index_status s ON s.memory_id=m.id
            WHERE m.embedding IS NOT NULL AND s.memory_id IS NULL
            ORDER BY m.id LIMIT ?""", (int(batch_size),)).fetchall()
        if not rows:
            break
        indexed_in_batch = 0
        for row in rows:
            try:
                vector = json.loads(row["embedding"])
                vector = [float(value) for value in vector]
                if _index_one(conn, sqlite_vec, row["id"], vector):
                    total_indexed += 1
                    indexed_in_batch += 1
            except Exception:
                # Avoid an endless backfill loop on a corrupt legacy embedding.
                conn.execute("UPDATE memories SET embedding=NULL WHERE id=?", (row["id"],))
        conn.commit()
        if indexed_in_batch == 0:
            break
    return total_indexed


def add(text: str, kind="conversation"):
    text = str(text).strip()
    if not text:
        return None
    embedding = _embed(text)
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO memories(text,kind,created,embedding) VALUES(?,?,?,?)",
            (text, str(kind), now, json.dumps(embedding) if embedding else None),
        )
        memory_id = int(cur.lastrowid)
        try:
            conn.execute("INSERT INTO memories_fts(rowid,text) VALUES(?,?)", (memory_id, text))
        except sqlite3.Error:
            # Memory is still saved if FTS indexing fails.
            pass
        if embedding:
            vec = _load_vec(conn)
            if vec:
                _index_one(conn, vec, memory_id, embedding)
        conn.commit()
        return memory_id
    finally:
        conn.close()


def _cos(a: list[float], b: list[float]):
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else -1.0


def _vector_search(conn, sqlite_vec, embedding, limit):
    _backfill_vector_index(conn, sqlite_vec)
    table = _vector_table_name(len(embedding))
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return None
    blob = sqlite_vec.serialize_float32(embedding)
    matches = conn.execute(
        f"SELECT rowid,distance FROM {table} "
        "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
        (blob, int(limit)),
    ).fetchall()
    ids = [int(match["rowid"]) for match in matches]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id,text,kind,created FROM memories WHERE id IN ({placeholders})", ids
    ).fetchall()
    by_id = {int(row["id"]): row for row in rows}
    return [by_id[int(match["rowid"])] for match in matches if int(match["rowid"]) in by_id]


def _fts_search(conn, query, limit):
    tokens = re.findall(r"[\w]+", query, flags=re.UNICODE)
    if not tokens:
        return []
    expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens[:32])
    try:
        return conn.execute("""SELECT m.id,m.text,m.kind,m.created,m.embedding
            FROM memories_fts f JOIN memories m ON m.id=f.rowid
            WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?""", (expression, int(limit))).fetchall()
    except sqlite3.Error:
        return []


def search(query: str, limit=8):
    query = str(query).strip()
    if not query:
        return []
    limit = max(1, min(int(limit), 100))
    conn = _connect()
    try:
        embedding = _embed(query)
        rows = None
        if embedding:
            vec = _load_vec(conn)
            if vec:
                try:
                    rows = _vector_search(conn, vec, embedding, limit)
                except Exception:
                    rows = None
        if rows is None:
            if embedding:
                scan_limit = max(limit, min(100000, int(os.getenv("KIRA_SEMANTIC_FALLBACK_SCAN_LIMIT", "5000"))))
                candidates = conn.execute("""SELECT id,text,kind,created,embedding FROM memories
                    WHERE embedding IS NOT NULL ORDER BY id DESC LIMIT ?""", (scan_limit,)).fetchall()
                scored = []
                for row in candidates:
                    try:
                        candidate_vector = json.loads(row["embedding"])
                        if not isinstance(candidate_vector, list) or len(candidate_vector) != len(embedding):
                            continue  # Don't return misleading hits from a different embedding model.
                        score = _cos(embedding, candidate_vector)
                    except Exception:
                        continue
                    scored.append((score, row))
                scored.sort(key=lambda item: item[0], reverse=True)
                rows = [row for _, row in scored[:limit]]
            else:
                rows = _fts_search(conn, query, limit)
        return [{"id": int(row["id"]), "text": row["text"], "kind": row["kind"], "created": row["created"]} for row in rows]
    finally:
        conn.close()


def build_context(query: str, limit=6):
    hits = search(query, limit)
    if not hits:
        return ""
    return "MEMORIA RELEVANTE:\n" + "\n".join(f"- {hit['text']}" for hit in hits)


def status():
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        with_embeddings = conn.execute("SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL").fetchone()[0]
        indexed = conn.execute("SELECT COUNT(*) FROM vector_index_status").fetchone()[0]
        vec = _load_vec(conn)
        version = None
        if vec:
            try:
                version = conn.execute("SELECT vec_version()").fetchone()[0]
            except sqlite3.Error:
                pass
        return {"total_memories": total, "with_embeddings": with_embeddings,
                "vector_indexed": indexed, "sqlite_vec_available": bool(vec),
                "sqlite_vec_version": version, "embedding_model": config.EMBED_MODEL or None}
    finally:
        conn.close()
