from pathlib import Path
import tempfile
import config
from approvals import request, list_pending, resolve
from planner import create, get, update


def test_plan_lifecycle():
    with tempfile.TemporaryDirectory() as d:
        old_db, old_json = config.PLANS_DB, config.PLANS_PATH
        config.PLANS_DB = Path(d) / 'plans.sqlite3'
        config.PLANS_PATH = Path(d) / 'nonexistent_legacy.json'
        try:
            p = create('demo', ['uno', 'dos'])
            assert get(p['id'])['status'] == 'pending'
            update(p['id'], 1, 'done', 'ok')
            update(p['id'], 2, 'done', 'ok2')
            assert get(p['id'])['status'] == 'done'
            assert get(p['id'])['steps'][0]['result'] == 'ok'
        finally:
            config.PLANS_DB, config.PLANS_PATH = old_db, old_json


def test_plan_legacy_json_migration():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        old_db, old_json = config.PLANS_DB, config.PLANS_PATH
        config.PLANS_DB = d / 'plans.sqlite3'
        config.PLANS_PATH = d / 'plans.json'
        config.PLANS_PATH.write_text('''{"old-plan":{"id":"old-plan","title":"Migrado","status":"pending","created":"2026-01-01T00:00:00+00:00","steps":[{"id":1,"text":"paso viejo","status":"pending","result":null}]}}''', encoding='utf-8')
        try:
            assert get('old-plan')['steps'][0]['text'] == 'paso viejo'
            # Import is idempotent and does not duplicate plans.
            assert len([p for p in __import__('planner').list_plans() if p['id'] == 'old-plan']) == 1
        finally:
            config.PLANS_DB, config.PLANS_PATH = old_db, old_json


def test_approval_lifecycle():
    with tempfile.TemporaryDirectory() as d:
        old = config.APPROVALS_PATH
        config.APPROVALS_PATH = Path(d) / 'approvals.json'
        try:
            r = request('x', {'secret': '[SENSITIVE]'}, 'test', 'high')
            assert any(x['id'] == r['id'] for x in list_pending())
            resolve(r['id'], True)
            assert not list_pending()
        finally:
            config.APPROVALS_PATH = old


def test_agent_tool_catalog_imports():
    import agent
    from tools import registry
    for expected in ['vision_analyze_desktop', 'desktop_click', 'schedule_once', 'create_tool', 'verify_python', 'voice_speak', 'plan_execute']:
        assert expected in registry.TOOLS
