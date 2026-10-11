from pathlib import Path

import pytest

import config
import llm_backend
from tools.code_tools import verify_python, verify_project


def test_reports_detailed_missing_colon(tmp_path):
    source = "if True\n    print('ok')\n"
    path = tmp_path / "broken.py"
    path.write_text(source, encoding="utf-8")

    result = verify_python(path)

    assert result["syntax_ok"] is False
    diag = result["diagnostics"][0]
    assert diag["line"] == 1
    assert diag["category"] == "missing_colon"
    assert "dos puntos" in diag["suggestion"]
    assert path.read_text(encoding="utf-8") == source


def test_reports_unclosed_delimiter(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("value = some_function(1, 2\n", encoding="utf-8")
    result = verify_python(path)
    assert result["syntax_ok"] is False
    assert result["diagnostics"][0]["category"] == "unclosed_delimiter"
    assert result["diagnostics"][0]["context"]


def test_autofix_repairs_minimally_and_creates_backup(tmp_path, monkeypatch):
    path = tmp_path / "broken.py"
    original = "if True\n    print('ok')\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        llm_backend,
        "chat",
        lambda messages, model=None: (
            "<KIRA_PYTHON_REPAIR>\nif True:\n    print('ok')\n</KIRA_PYTHON_REPAIR>\n"
            "<KIRA_NOTES>Se agregó el dos puntos faltante.</KIRA_NOTES>"
        ),
    )

    result = verify_python(path, auto_fix=True)

    assert result["syntax_ok"] is True
    assert result["auto_fix_applied"] is True
    assert Path(result["backup_path"]).read_text(encoding="utf-8") == original
    assert path.read_text(encoding="utf-8") == "if True:\n    print('ok')\n"


def test_autofix_failure_leaves_original_untouched(tmp_path, monkeypatch):
    path = tmp_path / "broken.py"
    original = "if True\n    print('ok')\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(llm_backend, "chat", lambda messages, model=None: "Esto es una explicación sin código.")

    result = verify_python(path, auto_fix=True, max_fix_attempts=1)

    assert result["syntax_ok"] is False
    assert result["auto_fix_applied"] is False
    assert path.read_text(encoding="utf-8") == original


def test_rejects_repair_that_changes_too_much(tmp_path, monkeypatch):
    path = tmp_path / "broken.py"
    original = "if True\n    print('ok')\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        llm_backend,
        "chat",
        lambda messages, model=None: (
            "<KIRA_PYTHON_REPAIR>\n"
            "import os\n"
            "def unrelated():\n    os.system('echo changed')\n"
            "</KIRA_PYTHON_REPAIR>\n<KIRA_NOTES>changed</KIRA_NOTES>"
        ),
    )

    result = verify_python(path, auto_fix=True, max_fix_attempts=1)

    assert result["auto_fix_applied"] is False
    assert path.read_text(encoding="utf-8") == original


def test_valid_script_is_not_modified_even_if_autofix_requested(tmp_path, monkeypatch):
    path = tmp_path / "valid.py"
    original = "print('hello')\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(llm_backend, "chat", lambda *args, **kwargs: pytest.fail("LLM should not be called"))

    result = verify_python(path, auto_fix=True)
    assert result["syntax_ok"] is True
    assert result["auto_fix_applied"] is False
    assert path.read_text(encoding="utf-8") == original


def test_timeout_is_reported_not_raised(tmp_path):
    path = tmp_path / "slow.py"
    path.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
    result = verify_python(path, run=True, timeout=0.1)
    assert result["timed_out"] is True
    assert result["success"] is False


def test_verify_project_returns_detailed_syntax_diagnostics(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "broken.py").write_text("def broken(\n", encoding="utf-8")
    monkeypatch.setattr(config, "COMMAND_TIMEOUT", 1)
    result = verify_project(project, run_tests=False)
    assert result["syntax_ok"] is False
    assert result["syntax_errors"][0]["diagnostics"][0]["line"] == 1

@pytest.mark.parametrize(
    ("source", "category"),
    [
        ("if True:\nprint('x')\n", "indentation"),
        ("message = f'Hello {name'\n", "f_string"),
        ("value = [1, 2\n", "unclosed_delimiter"),
    ],
)
def test_complex_syntax_categories(tmp_path, source, category):
    path = tmp_path / "complex.py"
    path.write_text(source, encoding="utf-8")
    result = verify_python(path)
    assert result["syntax_ok"] is False
    assert result["diagnostics"][0]["category"] == category
    assert result["diagnostics"][0]["line"] is not None
