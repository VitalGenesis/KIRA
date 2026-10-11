from __future__ import annotations

import ast
import difflib
import io
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from tools.registry import register

MAX_SOURCE_BYTES = 2_000_000
MAX_REPAIR_ATTEMPTS = 3
MIN_REPAIR_SIMILARITY = 0.55


def _read_source(path: Path) -> tuple[str, str, bytes]:
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError(
            f"El archivo tiene {len(raw):,} bytes; el límite de análisis es "
            f"{MAX_SOURCE_BYTES:,} bytes."
        )
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        source = raw.decode(encoding)
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise ValueError(f"No pude decodificar el archivo Python: {exc}") from exc
    return source, encoding, raw


def _categorize_syntax_error(exc: SyntaxError) -> tuple[str, str]:
    message = (exc.msg or str(exc)).lower()
    if "expected ':'" in message or "expected ':'" in message.replace("'", ""):
        return "missing_colon", "Revisá dos puntos al final de if/elif/else, for, while, def, class, try, except, finally, with o match/case."
    if "expected an indented block" in message or "unexpected indent" in message or "unindent does not match" in message:
        return "indentation", "Revisá la indentación del bloque y que uses espacios de forma consistente."
    if "never closed" in message or "was never closed" in message or "unexpected eof" in message:
        return "unclosed_delimiter", "Buscá paréntesis, corchetes o llaves sin cerrar; revisá también continuaciones de línea."
    if "unterminated string" in message or "eol while scanning string" in message:
        return "unterminated_string", "Revisá comillas simples/dobles, cadenas multilínea y escapes de barra invertida."
    if "f-string" in message:
        return "f_string", "Revisá las llaves, expresiones y comillas dentro de la f-string."
    if "invalid character" in message or "non-utf-8" in message:
        return "encoding_or_character", "Revisá caracteres invisibles, codificación y la declaración coding: del archivo."
    if "can't assign" in message or "cannot assign" in message:
        return "invalid_assignment", "Revisá el lado izquierdo de la asignación y expresiones que no sean asignables."
    return "syntax", "Revisá la expresión indicada y las líneas inmediatamente anteriores; el parser puede señalar el efecto de un error anterior."


def _diagnose_source(source: str, filename: str) -> dict[str, Any]:
    try:
        # ast.parse gives a structural diagnostic; compile additionally checks
        # contextual constraints without executing any user code.
        ast.parse(source, filename=filename, mode="exec", type_comments=True)
        compile(source, filename, "exec", dont_inherit=True)
        return {"syntax_ok": True, "diagnostics": []}
    except SyntaxError as exc:
        category, suggestion = _categorize_syntax_error(exc)
        lines = source.splitlines()
        line_no = exc.lineno or 0
        start = max(1, line_no - 2)
        end = min(len(lines), (exc.end_lineno or line_no) + 2)
        context = [
            {"line": n, "text": lines[n - 1], "error_line": n == line_no}
            for n in range(start, end + 1)
        ]
        diagnostic = {
            "type": type(exc).__name__,
            "message": exc.msg or str(exc),
            "line": line_no or None,
            "column": exc.offset,
            "end_line": getattr(exc, "end_lineno", None),
            "end_column": getattr(exc, "end_offset", None),
            "source_line": (lines[line_no - 1] if 1 <= line_no <= len(lines) else exc.text),
            "category": category,
            "suggestion": suggestion,
            "context": context,
        }
        return {"syntax_ok": False, "diagnostics": [diagnostic]}
    except (ValueError, TypeError) as exc:
        return {
            "syntax_ok": False,
            "diagnostics": [{"type": type(exc).__name__, "message": str(exc), "category": "parser_error"}],
        }


def _extract_repaired_code(raw: str) -> tuple[str, str]:
    """Parse a repair response without trusting surrounding prose as code."""
    text = str(raw or "").strip()

    marked = re.search(
        r"<KIRA_PYTHON_REPAIR>\s*(.*?)\s*</KIRA_PYTHON_REPAIR>", text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if marked:
        code = marked.group(1).strip()
        notes_match = re.search(r"<KIRA_NOTES>\s*(.*?)\s*</KIRA_NOTES>", text, re.I | re.S)
        return _strip_fence(code), notes_match.group(1).strip() if notes_match else "Corrección propuesta por el modelo local."

    # Common response format when a model ignores the requested markers.
    fence = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        notes = (text[:fence.start()] + text[fence.end():]).strip()
        return fence.group(1).strip(), notes[:1000] or "Código extraído de un bloque Markdown."

    # Accept plain source only if the response appears code-like and does not
    # start with explanatory text. Do not try to salvage arbitrary prose.
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    code_starters = ("import ", "from ", "def ", "class ", "if ", "for ", "while ", "try:", "with ", "@", "#", "async def ", "match ", "print(")
    if first_line.startswith(code_starters) or first_line.startswith(('"""', "'''")):
        return text, "El modelo devolvió código sin delimitadores."

    raise ValueError("El modelo no devolvió código identificable en un bloque de reparación.")


def _strip_fence(code: str) -> str:
    text = code.strip()
    m = re.fullmatch(r"```(?:python|py)?\s*(.*?)\s*```", text, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else text


def _repair_with_model(source: str, filename: str, diagnostics: list[dict[str, Any]], previous_attempt: int) -> tuple[str, str]:
    from llm_backend import chat

    diagnostic_text = "\n".join(
        f"{d.get('type')}: {d.get('message')} (línea {d.get('line')}, columna {d.get('column')}); "
        f"categoría={d.get('category')}; sugerencia={d.get('suggestion')}"
        for d in diagnostics
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Sos un reparador conservador de sintaxis Python. Tu tarea es corregir ÚNICAMENTE "
                "errores de sintaxis/parseo y conservar la intención, nombres, lógica, imports, "
                "operaciones y comportamiento del programa. No agregues funciones ni capacidades. "
                "No agregues imports, llamadas al sistema, red, procesos, borrados ni escritura adicional. "
                "No ejecutes el código. No respondas con explicaciones fuera del formato pedido. "
                "Respondé exactamente así:\n<KIRA_PYTHON_REPAIR>\n(código Python completo)\n</KIRA_PYTHON_REPAIR>\n"
                "<KIRA_NOTES>breve explicación</KIRA_NOTES>"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Reparación {previous_attempt} para {filename}.\nDiagnósticos del compilador:\n"
                f"{diagnostic_text}\n\nCódigo Python original/actual:\n"
                f"<SOURCE>\n{source}\n</SOURCE>\n\n"
                "Devolvé el archivo completo con la corrección mínima. Si no podés corregirlo con confianza, "
                "devolvé exactamente <KIRA_PYTHON_REPAIR></KIRA_PYTHON_REPAIR> y explicalo en KIRA_NOTES."
            ),
        },
    ]
    raw = chat(messages, model=config.OLLAMA_MODEL)
    return _extract_repaired_code(raw)


def _repair_is_conservative(original: str, candidate: str) -> tuple[bool, str, float]:
    ratio = difflib.SequenceMatcher(a=original, b=candidate, autojunk=False).ratio()
    if ratio < MIN_REPAIR_SIMILARITY:
        return False, (
            f"La propuesta cambió demasiado el contenido (similitud {ratio:.0%}; "
            f"mínimo {MIN_REPAIR_SIMILARITY:.0%}). No se aplicó."
        ), ratio
    if len(candidate) > max(len(original) * 2, len(original) + 1000):
        return False, "La propuesta aumentó demasiado el tamaño del archivo. No se aplicó.", ratio

    # A syntax fixer must not introduce new high-impact capabilities absent
    # from the source text. This is not a sandbox; it is a conservative guard.
    dangerous_patterns = {
        "subprocess": r"\b(?:import\s+subprocess|from\s+subprocess\s+import|subprocess\.(?:run|Popen|call|check_call|check_output))",
        "os_system": r"\bos\.system\s*\(",
        "dynamic_exec": r"\b(?:exec|eval|__import__)\s*\(",
        "socket": r"\b(?:import\s+socket|from\s+socket\s+import)",
        "ctypes": r"\b(?:import\s+ctypes|from\s+ctypes\s+import)",
        "registry": r"\b(?:import\s+winreg|from\s+winreg\s+import)",
        "recursive_delete": r"\bshutil\.rmtree\s*\(",
        "file_delete": r"\b(?:os\.remove|os\.unlink)\s*\(",
    }
    for label, pattern in dangerous_patterns.items():
        if re.search(pattern, candidate) and not re.search(pattern, original):
            return False, f"La propuesta introdujo una operación no presente en el original ({label}). No se aplicó.", ratio
    return True, "La propuesta pasó los controles conservadores.", ratio


def _atomic_write(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _backup_path(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return target.with_name(f"{target.name}.kira_backup_{stamp}.bak")


def verify_python(path, run=False, args=None, timeout=None, auto_fix=False, max_fix_attempts=2):
    """Diagnose Python syntax and, when requested, ask local Ollama for a guarded repair.

    `auto_fix=True` proposes a minimal syntax-only fix. The source is never
    replaced unless the repaired code compiles and passes conservative change
    checks. The original is copied to a timestamped backup before an atomic
    replacement. Validation never executes the source; execution happens only
    when the caller explicitly supplies `run=True`.
    """
    target = Path(str(path)).expanduser().resolve()
    if not target.is_file() or target.suffix.lower() != ".py":
        raise ValueError(f"No es un archivo Python: {target}")

    source, encoding, original_bytes = _read_source(target)
    diagnosis = _diagnose_source(source, str(target))
    result: dict[str, Any] = {
        "path": str(target),
        "syntax_ok": diagnosis["syntax_ok"],
        "diagnostics": diagnosis["diagnostics"],
        "auto_fix_requested": bool(auto_fix),
        "auto_fix_attempted": False,
        "auto_fix_applied": False,
    }

    if not diagnosis["syntax_ok"] and auto_fix:
        result["auto_fix_attempted"] = True
        attempts = max(1, min(int(max_fix_attempts or 1), MAX_REPAIR_ATTEMPTS))
        current_source = source
        current_diagnostics = diagnosis["diagnostics"]
        repair_notes: list[str] = []
        last_error = None

        for attempt in range(1, attempts + 1):
            try:
                candidate, notes = _repair_with_model(current_source, str(target), current_diagnostics, attempt)
                # Preserve the original file's newline convention and final newline.
                newline = "\r\n" if "\r\n" in source else "\n"
                candidate = candidate.replace("\r\n", "\n").replace("\r", "\n")
                if source.endswith(("\n", "\r")) and candidate and not candidate.endswith("\n"):
                    candidate += "\n"
                if newline == "\r\n":
                    candidate = candidate.replace("\n", "\r\n")
                repair_notes.append(notes[:1000])
                if not candidate.strip():
                    last_error = "El modelo no propuso código para reparar."
                    break
                candidate_diagnosis = _diagnose_source(candidate, str(target))
                if candidate_diagnosis["syntax_ok"]:
                    conservative, message, similarity = _repair_is_conservative(source, candidate)
                    result["repair_similarity"] = round(similarity, 4)
                    result["conservative_check"] = message
                    if not conservative:
                        last_error = message
                        break
                    try:
                        candidate_bytes = candidate.encode(encoding)
                    except UnicodeEncodeError as exc:
                        last_error = f"La propuesta no puede guardarse con la codificación original {encoding}: {exc}"
                        break
                    backup = _backup_path(target)
                    backup.write_bytes(original_bytes)
                    try:
                        _atomic_write(target, candidate_bytes)
                        # Re-read exactly what was written and compile it again.
                        written_source, _, _ = _read_source(target)
                        written_diagnosis = _diagnose_source(written_source, str(target))
                        if not written_diagnosis["syntax_ok"]:
                            raise RuntimeError("La validación posterior a escritura no pasó.")
                    except Exception:
                        try:
                            _atomic_write(target, original_bytes)
                        finally:
                            raise
                    result.update({
                        "syntax_ok": True,
                        "diagnostics": [],
                        "auto_fix_applied": True,
                        "backup_path": str(backup),
                        "repair_notes": repair_notes,
                        "message": "Sintaxis corregida y validada. No se ejecutó el programa.",
                    })
                    break
                current_source = candidate
                current_diagnostics = candidate_diagnosis["diagnostics"]
                last_error = "La propuesta del modelo todavía tiene errores de sintaxis."
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                # Retry once with the newest diagnostic if we have source for it.
                if attempt >= attempts:
                    break
        else:
            last_error = last_error or "No se pudo corregir la sintaxis."

        if not result["auto_fix_applied"]:
            result["repair_error"] = last_error or "No se pudo corregir la sintaxis."
            result["repair_notes"] = repair_notes
            # Ensure original bytes are untouched after any failed attempt.
            if target.read_bytes() != original_bytes:
                _atomic_write(target, original_bytes)

    if run and result["syntax_ok"]:
        cmd = [sys.executable, str(target)] + [str(x) for x in (args or [])]
        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or config.COMMAND_TIMEOUT,
                cwd=str(target.parent),
            )
            result.update({
                "run": True,
                "returncode": p.returncode,
                "stdout": p.stdout[-config.MAX_COMMAND_OUTPUT:],
                "stderr": p.stderr[-config.MAX_COMMAND_OUTPUT:],
                "success": p.returncode == 0,
            })
        except subprocess.TimeoutExpired as exc:
            result.update({
                "run": True,
                "timed_out": True,
                "timeout_seconds": timeout or config.COMMAND_TIMEOUT,
                "stdout": str(exc.stdout or "")[-config.MAX_COMMAND_OUTPUT:],
                "stderr": str(exc.stderr or "")[-config.MAX_COMMAND_OUTPUT:],
                "success": False,
            })
    return result


def verify_project(path, run_tests=True):
    root = Path(str(path)).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"No existe la carpeta: {root}")
    files = list(root.rglob("*.py"))[:2000]
    errors = []
    for file_path in files:
        try:
            source, _, _ = _read_source(file_path)
            diagnosis = _diagnose_source(source, str(file_path))
            if not diagnosis["syntax_ok"]:
                errors.append({"path": str(file_path), "diagnostics": diagnosis["diagnostics"]})
        except Exception as exc:
            errors.append({"path": str(file_path), "error": f"{type(exc).__name__}: {exc}"})
    result: dict[str, Any] = {
        "path": str(root),
        "python_files": len(files),
        "syntax_errors": errors,
        "syntax_ok": not errors,
    }
    if run_tests and not errors:
        test_dirs = [root / "tests", root / "test"]
        if any(directory.exists() for directory in test_dirs):
            try:
                p = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=config.COMMAND_TIMEOUT,
                )
                result.update({
                    "tests_run": True,
                    "tests_returncode": p.returncode,
                    "tests_stdout": p.stdout[-12000:],
                    "tests_stderr": p.stderr[-12000:],
                    "tests_ok": p.returncode == 0,
                })
            except Exception as exc:
                result.update({"tests_run": False, "tests_error": f"{type(exc).__name__}: {exc}"})
        else:
            result["tests_run"] = False
    return result


register(
    "verify_python",
    "Diagnostica sintaxis Python con línea/columna/contexto y categorías; con auto_fix=True solicita a Ollama una reparación mínima conservadora, valida sin ejecutar, hace backup y reemplaza atómicamente solo si compila. run=True ejecuta explícitamente el archivo.",
    verify_python,
    {
        "path": "string",
        "run": "boolean opcional; ejecuta el script después de validar",
        "args": "array opcional de argumentos para el script",
        "timeout": "number opcional",
        "auto_fix": "boolean opcional; intenta reparar sintaxis con el modelo local y conserva backup; no ejecuta el código",
        "max_fix_attempts": "integer opcional, 1-3",
    },
    risk="medium",
    confirm=False,
)
register(
    "verify_project",
    "Compila/analiza Python en un proyecto con diagnósticos de sintaxis detallados y ejecuta pytest si hay tests y no hay errores de sintaxis.",
    verify_project,
    {"path": "string", "run_tests": "boolean opcional"},
    risk="medium",
    confirm=False,
)
