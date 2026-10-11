from __future__ import annotations
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config

_lock = threading.RLock()


def _load():
    config.ensure_dirs()
    if not config.APPROVALS_PATH.exists():
        return {}
    try:
        data = json.loads(config.APPROVALS_PATH.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    tmp = Path(str(config.APPROVALS_PATH) + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    tmp.replace(config.APPROVALS_PATH)


def request(tool_name, args, description, risk='high', state=None):
    with _lock:
        data = _load()
        ident = uuid.uuid4().hex[:12]
        data[ident] = {
            'id': ident,
            'status': 'pending',
            'tool': tool_name,
            'args': args,
            'description': description,
            'risk': risk,
            'created': datetime.now(timezone.utc).isoformat(),
            'state': state,
        }
        _save(data)
        return data[ident]


def list_pending():
    with _lock:
        data = _load()
        return [v for v in data.values() if v.get('status') == 'pending']


def get(ident):
    with _lock:
        return _load().get(str(ident))


def resolve(ident, approved: bool):
    with _lock:
        data = _load()
        item = data.get(str(ident))
        if not item:
            return None
        item['status'] = 'approved' if approved else 'rejected'
        item['resolved'] = datetime.now(timezone.utc).isoformat()
        _save(data)
        return item
