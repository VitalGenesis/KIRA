import json
from pathlib import Path

import config

DEFAULT_MEMORY = {"history": [], "facts": []}


def load():
    config.ensure_dirs()
    if not config.MEMORY_PATH.exists():
        return {"history": [], "facts": []}
    try:
        data = json.loads(config.MEMORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"history": [], "facts": []}
        data.setdefault("history", [])
        data.setdefault("facts", [])
        return data
    except (OSError, json.JSONDecodeError):
        return {"history": [], "facts": []}


def save(memory):
    config.ensure_dirs()
    tmp = Path(str(config.MEMORY_PATH) + ".tmp")
    tmp.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(config.MEMORY_PATH)


def trimmed_history(memory):
    return memory.get("history", [])[-config.MAX_HISTORY_TURNS * 2:]


def add_turn(memory, role, content):
    memory.setdefault("history", []).append({"role": role, "content": content})


def add_fact(memory, fact):
    fact = fact.strip()
    if fact and fact not in memory.setdefault("facts", []):
        memory["facts"].append(fact)
