from pathlib import Path
import json
import tempfile
from datetime import datetime, timezone, timedelta

import config
from tools.filesystem import read_file
import planner
import scheduler
from memory import semantic


def test_read_file_is_bounded_and_reports_total_bytes():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'large.txt'
        path.write_bytes(b'a' * (10 * 1024 * 1024))
        result = read_file(str(path), max_bytes=1024)
        assert len(result['content']) == 1024
        assert result['bytes'] == 1024
        assert result['total_bytes'] == 10 * 1024 * 1024
        assert result['truncated'] is True


def test_plans_use_sqlite_and_scale_without_json_rewrites():
    with tempfile.TemporaryDirectory() as d:
        old_db, old_json = config.PLANS_DB, config.PLANS_PATH
        config.PLANS_DB = Path(d) / 'plans.sqlite3'
        config.PLANS_PATH = Path(d) / 'absent.json'
        try:
            plan = planner.create('bulk', [f'step {i}' for i in range(1, 21)])
            for i in range(1, 21):
                planner.update(plan['id'], i, 'done', {'ok': i})
            final = planner.get(plan['id'])
            assert final['status'] == 'done'
            assert len(final['steps']) == 20
            assert config.PLANS_DB.exists()
        finally:
            config.PLANS_DB, config.PLANS_PATH = old_db, old_json


def test_scheduler_sqlite_create_list_cancel():
    with tempfile.TemporaryDirectory() as d:
        old_db, old_json = config.SCHEDULES_DB, config.SCHEDULES_PATH
        config.SCHEDULES_DB = Path(d) / 'schedules.sqlite3'
        config.SCHEDULES_PATH = Path(d) / 'absent.json'
        try:
            job = scheduler.add_interval('verificar PC', 10)
            jobs = scheduler.list_jobs()
            assert any(x['id'] == job['id'] for x in jobs)
            canceled = scheduler.cancel(job['id'])
            assert canceled['enabled'] is False
            assert Path(config.SCHEDULES_DB).exists()
        finally:
            config.SCHEDULES_DB, config.SCHEDULES_PATH = old_db, old_json


def test_scheduler_legacy_json_migration():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        old_db, old_json = config.SCHEDULES_DB, config.SCHEDULES_PATH
        config.SCHEDULES_DB = d / 'schedules.sqlite3'
        config.SCHEDULES_PATH = d / 'schedules.json'
        config.SCHEDULES_PATH.write_text(json.dumps({
            'job-legacy': {
                'id': 'job-legacy', 'type': 'once', 'prompt': 'tarea antigua',
                'next_run': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                'enabled': True, 'last_result': None,
            }
        }), encoding='utf-8')
        try:
            assert any(x['id'] == 'job-legacy' for x in scheduler.list_jobs())
        finally:
            config.SCHEDULES_DB, config.SCHEDULES_PATH = old_db, old_json


def test_semantic_memory_fts_fallback():
    with tempfile.TemporaryDirectory() as d:
        old_db, old_embed = config.SEMANTIC_DB, config.EMBED_MODEL
        config.SEMANTIC_DB = Path(d) / 'semantic.sqlite3'
        config.EMBED_MODEL = ''
        try:
            semantic.add('KIRA puede actualizar archivos Python', 'test')
            semantic.add('La bicicleta necesita mantenimiento de cadena', 'test')
            results = semantic.search('Python archivos', limit=5)
            assert results
            assert any('Python' in item['text'] for item in results)
            assert semantic.status()['total_memories'] == 2
        finally:
            config.SEMANTIC_DB, config.EMBED_MODEL = old_db, old_embed


def test_semantic_embedding_fallback_search():
    # Emulate Ollama so the cosine fallback remains testable without a model server.
    with tempfile.TemporaryDirectory() as d:
        old_db, old_embed = config.SEMANTIC_DB, config.EMBED_MODEL
        original_embed = semantic._embed
        config.SEMANTIC_DB = Path(d) / 'semantic.sqlite3'
        config.EMBED_MODEL = 'fake-test-model'
        vectors = {
            'sol crypto': [1.0, 0.0, 0.0],
            'python code': [0.0, 1.0, 0.0],
            'buscar python': [0.0, 0.9, 0.1],
            'crypto question': [0.9, 0.1, 0.0],
        }
        semantic._embed = lambda text: vectors.get(text, [0.0, 1.0, 0.0])
        try:
            for text in list(vectors)[:3]:
                # Insert prepared embeddings directly so the test does not depend on network.
                c = semantic._connect()
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).isoformat()
                cur = c.execute('INSERT INTO memories(text,kind,created,embedding) VALUES(?,?,?,?)',
                                (text, 'test', now, json.dumps(vectors[text])))
                c.execute('INSERT INTO memories_fts(rowid,text) VALUES(?,?)', (cur.lastrowid, text))
                c.commit(); c.close()
            matches = semantic.search('buscar python', limit=2)
            assert matches
            assert matches[0]['text'] == 'buscar python'
        finally:
            semantic._embed = original_embed
            config.SEMANTIC_DB, config.EMBED_MODEL = old_db, old_embed


def test_sqlite_planner_concurrent_writes():
    from concurrent.futures import ThreadPoolExecutor
    with tempfile.TemporaryDirectory() as d:
        old_db, old_json = config.PLANS_DB, config.PLANS_PATH
        config.PLANS_DB = Path(d) / 'plans.sqlite3'
        config.PLANS_PATH = Path(d) / 'absent.json'
        try:
            def make(index):
                return planner.create(f'concurrent-{index}', ['one', 'two'])['id']
            with ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(make, range(80)))
            assert len(set(ids)) == 80
            assert len(planner.list_plans()) == 80
        finally:
            config.PLANS_DB, config.PLANS_PATH = old_db, old_json


def test_due_once_job_is_claimed_at_most_once():
    from concurrent.futures import ThreadPoolExecutor
    with tempfile.TemporaryDirectory() as d:
        old_db, old_json = config.SCHEDULES_DB, config.SCHEDULES_PATH
        config.SCHEDULES_DB = Path(d) / 'schedules.sqlite3'
        config.SCHEDULES_PATH = Path(d) / 'absent.json'
        try:
            job = scheduler.add_once('test due order', (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(lambda _: scheduler._claim_due_jobs(), range(2)))
            all_claims = [item for group in claims for item in group]
            assert len([item for item in all_claims if item['id'] == job['id']]) == 1
            scheduler._finish_job(job, 'done')
            current = next(x for x in scheduler.list_jobs() if x['id'] == job['id'])
            assert current['enabled'] is False and current['running'] is False
        finally:
            config.SCHEDULES_DB, config.SCHEDULES_PATH = old_db, old_json


def test_sqlite_vec_k_nearest_neighbors_if_installed():
    import pytest
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        pytest.skip('sqlite-vec dependency is not installed in this test environment')
    with tempfile.TemporaryDirectory() as d:
        old_db, old_embed = config.SEMANTIC_DB, config.EMBED_MODEL
        original_embed = semantic._embed
        config.SEMANTIC_DB = Path(d) / 'semantic.sqlite3'
        config.EMBED_MODEL = 'fake-test-model'
        vectors = {
            'alpha': [1.0, 0.0, 0.0],
            'beta': [0.0, 1.0, 0.0],
            'alpha query': [0.99, 0.01, 0.0],
        }
        semantic._embed = lambda text: vectors.get(text, [1.0, 0.0, 0.0])
        try:
            semantic.add('alpha', 'test')
            semantic.add('beta', 'test')
            status = semantic.status()
            assert status['sqlite_vec_available'] is True
            assert status['vector_indexed'] == 2
            matches = semantic.search('alpha query', limit=1)
            assert matches and matches[0]['text'] == 'alpha'
        finally:
            semantic._embed = original_embed
            config.SEMANTIC_DB, config.EMBED_MODEL = old_db, old_embed
