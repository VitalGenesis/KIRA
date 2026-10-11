"""Bounded autonomous self-improvement with backup, isolated tests and rollback.

KIRA may improve selected non-critical project modules without asking the user.
The control plane (agent, config, approvals, execution tools, launchers and tests)
is deliberately immutable to this mechanism.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from llm_backend import chat, is_ollama_running

# Only these existing Python modules can be automatically edited. Critical
# control-plane modules, tests, dependency manifests and launch scripts remain
# protected even if the local model requests changes to them.
_SAFE_EDIT_FUNCTIONS = {
    "planner.py": {"_safe_json"},
    "scheduler.py": {"_now", "_parse_datetime", "_as_dict"},
    "voice.py": {"_cuda_available"},
    "memory/memory.py": {"trimmed_history", "add_turn", "add_fact"},
    "memory/semantic.py": {"_cos"},
}
_ALLOWED_FILES = set(_SAFE_EDIT_FUNCTIONS)
_MAX_EDITS = 6
_MAX_OLD_CHARS = 7000
_MAX_NEW_CHARS = 12000
_MAX_PROMPT_SOURCE_CHARS = 52000
_DEFAULT_MAX_FILES = 2
_BACKUP_RETENTION = 20

_GOAL_HINTS = {
    "memoria": ("memory/memory.py",),
    "recuerdo": ("memory/memory.py",),
    "semant": ("memory/semantic.py",),
    "vector": ("memory/semantic.py",),
    "plan": ("planner.py",),
    "tarea": ("scheduler.py",),
    "program": ("scheduler.py",),
    "schedule": ("scheduler.py",),
    "voz": ("voice.py",),
    "voice": ("voice.py",),
}

_DANGEROUS_IMPORTS = {
    "ctypes", "winreg", "subprocess", "socket", "requests", "urllib", "http",
    "ftplib", "paramiko", "importlib", "runpy", "tools", "agent", "shutil", "os", "builtins",
    "signal", "asyncio", "time",
    "sys", "pickle", "marshal", "multiprocessing", "terminal", "filesystem",
    "processes", "desktop", "browser", "tool_builder", "registry", "self_improvement",
}
_DANGEROUS_CALLS = {
    "eval", "exec", "__import__", "system", "popen", "rmtree", "unlink",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return Path(config.BASE_DIR).resolve()


def _state_dir() -> Path:
    return Path(config.RUNTIME_DIR) / "self_improve"


def _backup_root() -> Path:
    return _state_dir() / "backups"


def _history_path() -> Path:
    return _state_dir() / "history.jsonl"


def _ensure_state() -> None:
    _backup_root().mkdir(parents=True, exist_ok=True)


def _rel_path(value: Any) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    candidate = Path(raw)
    if candidate.is_absolute() or not raw or any(part in ("", ".", "..") for part in raw.split("/")):
        raise ValueError(f"Ruta relativa no válida: {raw!r}")
    normalized = candidate.as_posix()
    if normalized not in _ALLOWED_FILES:
        raise ValueError(f"Archivo protegido o fuera del alcance de auto-mejora: {normalized}")
    if candidate.suffix.lower() != ".py":
        raise ValueError("Solo se permiten archivos Python existentes.")
    return normalized


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dangerous_fingerprint(source: str) -> dict[str, int]:
    """Count security-sensitive imports/calls; only newly added ones are blocked."""
    tree = ast.parse(source)
    counts: dict[str, int] = {}

    def add(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    def dotted(node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _DANGEROUS_IMPORTS:
                    add("import:" + root)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _DANGEROUS_IMPORTS:
                add("import:" + root)
            if not node.module:
                for alias in node.names:
                    alias_root = alias.name.split(".")[0]
                    if alias_root in _DANGEROUS_IMPORTS:
                        add("import:" + alias_root)
        elif isinstance(node, ast.Call):
            call = dotted(node.func)
            if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "__import__", "getattr"}:
                add("call:" + node.func.id)
            if isinstance(node.func, ast.Name) and node.func.id == "__import__" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                dynamic_root = node.args[0].value.split(".")[0]
                if dynamic_root in _DANGEROUS_IMPORTS:
                    add("dynamic_import:" + dynamic_root)
            sensitive_calls = {
                "os.system", "os.popen", "subprocess.run", "subprocess.Popen",
                "subprocess.call", "subprocess.check_call", "subprocess.check_output",
                "shutil.rmtree", "Path.unlink", "os.remove", "os.unlink",
                "os.replace", "os.rename", "os.chmod", "os.chown", "os.kill", "os._exit",
                "os.abort", "os.execv", "os.execve", "os.startfile", "requests.get", "requests.post",
                "sqlite3.connect", "sqlite3.Connection.execute", "mem.load", "mem.save", "mem.add_turn",
                "mem.add_fact", "agent.run", "scheduler.add_once", "scheduler.add_interval",
                "scheduler.cancel", "planner.create", "planner.update", "planner.execute",
                "config.ensure_dirs", "semantic_add", "build_context", "system_info",
            }
            if call in sensitive_calls or call.startswith("requests.") or call.startswith("urllib."):
                add("call:" + call)
                add("call_ast:" + ast.dump(node, include_attributes=False))
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                add("call:open")
                add("call_ast:" + ast.dump(node, include_attributes=False))
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "unlink", "rmtree", "write_text", "write_bytes", "read_text", "read_bytes",
                "remove", "replace", "mkdir", "touch", "open", "readlink", "iterdir", "glob", "rglob",
            }:
                add("method:" + node.func.attr)
                add("method_ast:" + ast.dump(node, include_attributes=False))
    # Detect indirect escape hatches which are harder to represent as a simple call target.
    for token in ("__builtins__", "globals(", "locals(", "vars(", "setattr(", "compile(", "os.environ"):
        counts["token:" + token] = source.count(token)
    return counts


def _ensure_safe_code(before: str, after: str, path: str) -> None:
    before_counts = _dangerous_fingerprint(before)
    after_counts = _dangerous_fingerprint(after)
    increased = {
        key: count - before_counts.get(key, 0)
        for key, count in after_counts.items()
        if count > before_counts.get(key, 0)
    }
    if increased:
        raise ValueError(f"La modificación añade operaciones no permitidas en {path}: {increased}")


def _select_sources(goal: str, max_files: int) -> list[tuple[str, str]]:
    root = _root()
    ordered: list[str] = []
    lower = str(goal).lower()
    for hint, names in _GOAL_HINTS.items():
        if hint in lower:
            for name in names:
                if name in _ALLOWED_FILES and name not in ordered:
                    ordered.append(name)
    if not ordered:
        ordered = sorted(_ALLOWED_FILES)
    sources: list[tuple[str, str]] = []
    total = 0
    for name in ordered:
        if len(sources) >= max_files:
            break
        path = root / name
        if not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if len(source) > 18000:
            source = source[:18000] + "\n# [CONTENIDO TRUNCADO PARA PROPUESTA DE MEJORA]\n"
        if total + len(source) > _MAX_PROMPT_SOURCE_CHARS:
            break
        sources.append((name, source))
        total += len(source)
    return sources


# KIRA_V8_JSONISH_PROPOSAL_PARSER
def _sanitize_jsonish(raw: str) -> str:
    # Repairs invalid JSON escapes/control characters without executing anything.
    text = str(raw or "").lstrip("\ufeff")
    out = []
    in_string = False
    i = 0
    valid_escapes = set('"\\/bfnrt')
    while i < len(text):
        ch = text[i]
        if not in_string:
            out.append(ch)
            if ch == '"': in_string = True
            i += 1; continue
        if ch == '"':
            out.append(ch); in_string = False; i += 1; continue
        if ch == "\\":
            if i + 1 < len(text):
                nxt = text[i + 1]
                if nxt in valid_escapes:
                    out.extend((ch, nxt)); i += 2; continue
                if nxt == "u" and i + 5 < len(text) and all(c in "0123456789abcdefABCDEF" for c in text[i + 2:i + 6]):
                    out.append(text[i:i + 6]); i += 6; continue
            out.append("\\\\"); i += 1; continue
        if ch == "\n": out.append("\\n")
        elif ch == "\r": out.append("\\r")
        elif ch == "\t": out.append("\\t")
        elif ord(ch) < 0x20: out.append(" ")
        else: out.append(ch)
        i += 1
    return "".join(out)


def _parse_model_json(raw: str) -> dict[str, Any]:
    """Extract a single proposal JSON object, tolerating prose, fences and bad path escapes."""
    text = str(raw or "").lstrip("\ufeff").strip()
    if not text: raise ValueError("El modelo no devolvió la propuesta JSON esperada.")
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    decoder = json.JSONDecoder()
    last_error = None
    for candidate_source in (text, _sanitize_jsonish(text)):
        try:
            obj = json.loads(candidate_source)
            if isinstance(obj, dict) and ("edits" in obj or "summary" in obj): return obj
        except json.JSONDecodeError as exc:
            last_error = exc
        for index, char in enumerate(candidate_source):
            if char != "{": continue
            try: obj, _end = decoder.raw_decode(candidate_source[index:])
            except json.JSONDecodeError as exc:
                last_error = exc; continue
            if isinstance(obj, dict) and ("edits" in obj or "summary" in obj): return obj
    extra = f" Último error de parseo en posición {last_error.pos}." if last_error else ""
    raise ValueError("No se pudo extraer un objeto JSON válido de la propuesta de Ollama. Se intentó recuperar escapes, fences y el primer objeto." + extra)


def _propose(goal: str, sources: list[tuple[str, str]]) -> dict[str, Any]:
    rendered = "\n\n".join(f"===== FILE: {name} =====\n{source}" for name, source in sources)
    system = (
        "Sos el subsistema de mejora de KIRA V8. Proponé cambios pequeños, útiles y verificables a los archivos proporcionados. "
        "Devolvé UN SOLO objeto JSON válido, sin Markdown ni texto extra, con forma: "
        '{"summary":"...","edits":[{"path":"ruta/archivo.py","old":"fragmento literal exacto","new":"fragmento sustituto literal","reason":"motivo"}]}. '
        "Máximo 6 ediciones y 3 archivos. Editá exclusivamente los cuerpos de funciones seguras listadas. "
        "No cambies imports, firmas, constantes, tests, permisos, ejecución del sistema ni operaciones de red/archivo adicionales. "
        "Si no hay una mejora segura, devuelve edits []."
    )
    user = (f"OBJETIVO:\n{goal}\n\nUsá rutas relativas exactas. Cada old debe ser un fragmento único. "
            "Las cadenas JSON deben escapar \" y los saltos de línea.\n\nCÓDIGO DISPONIBLE:\n" + rendered)
    raw = chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
    try:
        return _parse_model_json(raw)
    except ValueError as first_error:
        repair_system = (
            "Convertí la salida anterior en UN SOLO objeto JSON sintácticamente válido con claves summary y edits. "
            "Conservá fielmente los valores y fragmentos de código; escapá comillas, backslashes y saltos de línea. "
            "No propongas cambios nuevos ni agregues comentarios. Devolvé solo JSON."
        )
        repaired = chat([
            {"role": "system", "content": repair_system},
            {"role": "user", "content": "La propuesta no se pudo parsear. Reescribila como JSON válido:\n" + str(raw)[:22000]},
        ])
        try:
            return _parse_model_json(repaired)
        except Exception as second_error:
            raise ValueError(
                "La propuesta de auto-mejora no pudo parsearse tras un intento de reparación. "
                f"Primer error: {first_error}. Segundo error: {second_error}. No se aplicó ningún cambio."
            ) from second_error


def _function_scope_for_edit(path: str, original: str, old: str) -> str:
    """Return the safe top-level function containing this exact source fragment."""
    allowed = _SAFE_EDIT_FUNCTIONS.get(path, set())
    if not allowed:
        raise ValueError(f"El archivo no tiene ámbitos autorizados para editar: {path}")
    start = original.find(old)
    end_offset = start + len(old)
    if end_offset > 0 and original[end_offset - 1] == "\n":
        end_offset -= 1
    start_line = original.count("\n", 0, start) + 1
    end_line = original.count("\n", 0, end_offset) + 1
    tree = ast.parse(original, filename=path)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node_end = getattr(node, "end_lineno", node.lineno)
            if node.name in allowed and node.lineno <= start_line <= node_end and node.lineno <= end_line <= node_end:
                return node.name
    raise ValueError(
        f"Edición rechazada: {path} solo permite cambiar funciones puras de la lista segura {sorted(allowed)}."
    )


def _module_shape(source: str, filename: str) -> tuple[list[str], list[str]]:
    """Capture imports and top-level APIs; self-improvement may change function bodies only."""
    tree = ast.parse(source, filename=filename)
    imports = []
    declarations = []
    editable_names = _SAFE_EDIT_FUNCTIONS.get(filename, set())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(ast.dump(node, include_attributes=False))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in editable_names:
            args = ast.dump(node.args, include_attributes=False)
            decorators = [ast.dump(d, include_attributes=False) for d in node.decorator_list]
            returns = ast.dump(node.returns, include_attributes=False) if node.returns else ""
            declarations.append(f"editable-function-signature:{node.name}:{args}:{decorators}:{returns}")
        else:
            # Freeze every other module-level node and every non-editable function body.
            declarations.append("locked-top-level:" + ast.dump(node, include_attributes=False))
    return sorted(imports), sorted(declarations)


def _validate_structure(before: str, after: str, path: str) -> None:
    if _module_shape(before, path) != _module_shape(after, path):
        raise ValueError(
            f"Edición rechazada en {path}: solo se permite cambiar el cuerpo de una función autorizada; imports, firmas y constantes deben permanecer iguales."
        )


def _validate_edits(proposal: dict[str, Any], sources: list[tuple[str, str]], max_files: int) -> list[dict[str, str]]:
    source_map = dict(sources)
    items = proposal.get("edits", [])
    if not isinstance(items, list):
        raise ValueError("El campo edits debe ser una lista.")
    if len(items) > _MAX_EDITS:
        raise ValueError(f"Demasiadas ediciones; máximo {_MAX_EDITS}.")
    edits = []
    seen_files = set()
    file_spans: dict[str, list[tuple[int, int]]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Cada edición debe ser un objeto JSON.")
        rel = _rel_path(item.get("path"))
        if rel not in source_map:
            raise ValueError(f"El archivo no se proporcionó al modelo: {rel}")
        old = item.get("old")
        new = item.get("new")
        if not isinstance(old, str) or not old.strip() or not isinstance(new, str):
            raise ValueError(f"Edición incompleta para {rel}.")
        if len(old) > _MAX_OLD_CHARS or len(new) > _MAX_NEW_CHARS:
            raise ValueError(f"Fragmento demasiado largo en {rel}.")
        original = source_map[rel]
        if original.count(old) != 1:
            raise ValueError(f"El fragmento old de {rel} debe aparecer exactamente una vez.")
        safe_scope = _function_scope_for_edit(rel, original, old)
        start = original.find(old)
        end = start + len(old)
        for prior_start, prior_end in file_spans.setdefault(rel, []):
            if max(start, prior_start) < min(end, prior_end):
                raise ValueError(f"Ediciones solapadas en {rel}.")
        file_spans[rel].append((start, end))
        seen_files.add(rel)
        edits.append({
            "path": rel, "old": old, "new": new,
            "reason": str(item.get("reason", "Mejora propuesta por el modelo"))[:500],
            "safe_scope": safe_scope,
        })
    if len(seen_files) > min(3, max_files):
        raise ValueError("La propuesta modifica demasiados archivos.")
    return edits


def _apply_edits_to_sources(sources: list[tuple[str, str]], edits: list[dict[str, str]]) -> dict[str, str]:
    contents = dict(sources)
    grouped: dict[str, list[dict[str, str]]] = {}
    for edit in edits:
        grouped.setdefault(edit["path"], []).append(edit)
    for rel, changes in grouped.items():
        original = contents[rel]
        positions = []
        for edit in changes:
            old = edit["old"]
            if original.count(old) != 1:
                raise ValueError(f"El archivo cambió durante la validación: {rel}")
            start = original.find(old)
            positions.append((start, start + len(old), edit["new"]))
        # Replace from bottom upward so earlier offsets remain valid.
        for start, end, new in sorted(positions, reverse=True):
            original = original[:start] + new + original[end:]
        ast.parse(original, filename=rel)
        before = dict(sources)[rel]
        _ensure_safe_code(before, original, rel)
        _validate_structure(before, original, rel)
        contents[rel] = original
    return {rel: contents[rel] for rel in grouped}


def _ignore_copy(directory: str, names: list[str]) -> set[str]:
    current = Path(directory)
    ignored = {n for n in names if n in {
        ".git", ".venv", "__pycache__", ".pytest_cache", "browser_data",
        "desktop_data", "voice_data", "workspace", "self_improve", ".mypy_cache",
    }}
    for name in names:
        if name.endswith((".pyc", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm")):
            ignored.add(name)
        if current.name == "runtime" and name not in {".gitkeep"} and not Path(name).is_dir():
            # Exclude local state/DB files from the isolated test copy.
            if not name.endswith(".py"):
                ignored.add(name)
        if current.name == "memory" and name in {"conversation.json", "semantic.sqlite3"}:
            ignored.add(name)
    return ignored


def _test_staged_project(contents: dict[str, str], run_tests: bool, timeout: int) -> dict[str, Any]:
    root = _root()
    with tempfile.TemporaryDirectory(prefix="kira_v8_improve_") as temp:
        staged = Path(temp) / "project"
        shutil.copytree(root, staged, ignore=_ignore_copy)
        changed = []
        for rel, content in contents.items():
            target = staged / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            changed.append(str(target))
        for file_path in changed:
            subprocess.run(
                [sys.executable, "-m", "py_compile", file_path],
                cwd=str(staged), check=True, capture_output=True, text=True, timeout=30,
            )
        result: dict[str, Any] = {"syntax_ok": True, "tests_run": False, "tests_ok": None}
        if run_tests:
            test_dir = staged / "tests"
            if not test_dir.exists():
                raise RuntimeError("No hay una carpeta tests/; se rechaza aplicar cambios sin pruebas.")
            try:
                p = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q"],
                    cwd=str(staged), capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"Las pruebas excedieron {timeout} segundos; no se aplicaron cambios.") from exc
            result.update({
                "tests_run": True,
                "tests_ok": p.returncode == 0,
                "tests_returncode": p.returncode,
                "tests_stdout": p.stdout[-10000:],
                "tests_stderr": p.stderr[-5000:],
            })
            if p.returncode != 0:
                raise RuntimeError("Las pruebas de la copia temporal fallaron; no se aplicaron cambios. " + (p.stdout + "\n" + p.stderr)[-5000:])
        return result


def _append_history(record: dict[str, Any]) -> None:
    _ensure_state()
    path = _history_path()
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _read_history(limit: int = 20) -> list[dict[str, Any]]:
    path = _history_path()
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(int(limit), 100)):]:
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                records.append(data)
        except json.JSONDecodeError:
            continue
    return records[::-1]


def _backup_and_apply(contents: dict[str, str], metadata: dict[str, Any]) -> str:
    root = _root()
    _ensure_state()
    backup_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    backup_dir = _backup_root() / backup_id
    backup_files = backup_dir / "files"
    backup_files.mkdir(parents=True, exist_ok=False)
    file_manifest = []
    originals: dict[str, bytes] = {}
    for rel in contents:
        target = (root / rel).resolve()
        # Defense in depth against path traversal/symlink escape.
        target.relative_to(root)
        if not target.is_file():
            raise ValueError(f"No existe el archivo que se pretende cambiar: {rel}")
        data = target.read_bytes()
        originals[rel] = data
        copy = backup_files / rel
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(data)
        file_manifest.append({"path": rel, "sha256_before": _sha256(data), "sha256_after": _sha256(contents[rel].encode("utf-8"))})
    manifest = {
        "id": backup_id, "created": _now(), "applied": False, "state": "prepared",
        "summary": metadata.get("summary", ""), "files": file_manifest,
        "goal": metadata.get("goal", ""),
    }
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    written = []
    try:
        manifest["state"] = "applying"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        for rel, content in contents.items():
            target = root / rel
            temp_path = target.with_name(target.name + ".kira-v8-tmp")
            temp_path.write_text(content, encoding="utf-8")
            os.replace(temp_path, target)
            written.append(rel)
        # Post-apply syntax check. The same content passed tests in the isolated copy.
        for rel in contents:
            subprocess.run([sys.executable, "-m", "py_compile", str(root / rel)], check=True, capture_output=True, timeout=30)
        manifest["applied"] = True
        manifest["state"] = "applied"
        manifest["applied_at"] = _now()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        for rel in written:
            temp_path = root / rel
            temp_restore = temp_path.with_name(temp_path.name + ".kira-v8-restore")
            temp_restore.write_bytes(originals[rel])
            os.replace(temp_restore, temp_path)
        manifest["applied"] = False
        manifest["state"] = "rolled_back"
        manifest["rolled_back_after_error"] = True
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    _prune_backups()
    return backup_id


def _prune_backups() -> None:
    dirs = sorted((p for p in _backup_root().iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    for path in dirs[_BACKUP_RETENTION:]:
        shutil.rmtree(path, ignore_errors=True)


def self_improve(goal="Mejorar robustez, rendimiento y manejo de errores de KIRA", max_files=_DEFAULT_MAX_FILES,
                 run_tests=True, test_timeout=180):
    """Propose, stage, test and automatically apply safe project improvements.

    No user approval is requested for this specific action. The code is restricted
    to the allowlist, protected control-plane files cannot be changed, all edits are
    backed up, and failed/unsafe test runs are rejected without application.
    """
    goal = str(goal or "").strip()
    if not goal:
        raise ValueError("Indicá el objetivo de mejora.")
    if not run_tests:
        return {"success": False, "applied": False,
                "error": "La auto-mejora no permite aplicar cambios sin ejecutar toda la suite de pruebas.",
                "approval_required": False}
    max_files = max(1, min(int(max_files), 3))
    test_timeout = max(30, min(int(test_timeout), 600))
    if not is_ollama_running():
        return {"success": False, "applied": False, "error": f"Ollama no está disponible en {config.OLLAMA_URL}.", "approval_required": False}
    sources = _select_sources(goal, max_files=max_files)
    if not sources:
        return {"success": False, "applied": False, "error": "No encontré archivos editables para este objetivo.", "approval_required": False}
    stage = "generar/parsear propuesta de Ollama"
    try:
        proposal = _propose(goal, sources)
        stage = "validar ediciones propuestas"
        edits = _validate_edits(proposal, sources, max_files)
        if not edits:
            return {"success": True, "applied": False, "message": "El análisis no encontró un cambio seguro y útil.", "summary": str(proposal.get("summary", "Sin cambios")), "approval_required": False}
        stage = "aplicar ediciones en copia temporal"
        contents = _apply_edits_to_sources(sources, edits)
        stage = "ejecutar pruebas aisladas"
        test_result = _test_staged_project(contents, True, test_timeout)
        stage = "crear backup y aplicar cambios"
        backup_id = _backup_and_apply(contents, {"summary": str(proposal.get("summary", "")), "goal": goal})
        record = {
            "id": backup_id, "created": _now(), "status": "applied",
            "goal": goal, "summary": str(proposal.get("summary", "")),
            "files": list(contents),
            "edits": [{"path": e["path"], "reason": e["reason"]} for e in edits],
            "tests": test_result,
            "approval_required": False,
        }
        try:
            _append_history(record)
        except Exception as history_error:
            record["history_write_error"] = f"{type(history_error).__name__}: {history_error}"
        return {"success": True, "applied": True, "backup_id": backup_id,
                "summary": record["summary"], "files_changed": list(contents),
                "edits": record["edits"], "validation": test_result,
                "approval_required": False,
                "note": "Los cambios se aplicaron sin pedir autorización y con copia de seguridad. Reiniciá KIRA si el módulo ya estaba importado y su comportamiento no se actualiza en caliente.",
                "history_warning": record.get("history_write_error")}
    except Exception as exc:
        failure = {"created": _now(), "status": "rejected", "goal": goal,
                   "error": f"Etapa: {stage}. {type(exc).__name__}: {exc}", "approval_required": False}
        try:
            _append_history(failure)
        except Exception:
            pass
        return {"success": False, "applied": False, "error": failure["error"], "stage": stage, "approval_required": False,
                "note": "No se aplicaron los cambios porque la propuesta, la validación o las pruebas fallaron."}


def self_improvement_status(limit=10):
    return {"enabled": True, "approval_required": False,
            "editable_files": sorted(_ALLOWED_FILES),
            "protected_files": ["agent.py", "app.py", "config.py", "approvals.py", "llm_backend.py", "self_improvement.py", "tools/__init__.py",
                                 "vision.py", "web_search.py",
                                 "tools/registry.py", "tools/tool_builder.py", "tools/self_improvement.py",
                                 "tools/filesystem.py", "tools/terminal.py", "tools/processes.py",
                                 "tools/desktop.py", "tools/browser.py", "tools/code_tools.py",
                                 "tools/system.py", "tools/scheduler_tools.py", "tools/voice_tools.py",
                                 "tests/", "requirements.txt", "*.ps1"],
            "editable_functions": {path: sorted(names) for path, names in _SAFE_EDIT_FUNCTIONS.items()},
            "recent_runs": _read_history(limit)}


def rollback_self_improvement(backup_id=None):
    """Restore a previous automatically-applied improvement; no user approval required."""
    _ensure_state()
    base = _backup_root()
    if backup_id:
        candidate = (base / str(backup_id)).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError:
            raise ValueError("ID de copia no válido.")
        candidates = [candidate]
    else:
        candidates = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    root = _root()
    for folder in candidates:
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not manifest.get("applied") and manifest.get("state") != "applying":
            continue
        files = manifest.get("files", [])
        # Validate all paths before writing anything.
        restored = []
        for item in files:
            rel = _rel_path(item.get("path"))
            backup_file = (folder / "files" / rel).resolve()
            backup_file.relative_to((folder / "files").resolve())
            if not backup_file.is_file():
                raise ValueError(f"Falta archivo de respaldo: {rel}")
            target = root / rel
            if manifest.get("applied") and target.is_file():
                expected_after = item.get("sha256_after")
                current_hash = _sha256(target.read_bytes())
                if expected_after and current_hash != expected_after:
                    raise ValueError(
                        f"No revierto {rel}: cambió después de esta auto-mejora. "
                        "Revertí primero la mejora más reciente o conservá el cambio manual."
                    )
            restored.append((rel, backup_file.read_bytes()))
        for rel, data in restored:
            target = root / rel
            temp_path = target.with_name(target.name + ".kira-v8-restore")
            temp_path.write_bytes(data)
            os.replace(temp_path, target)
        manifest["applied"] = False
        manifest["state"] = "rolled_back"
        manifest["rolled_back_at"] = _now()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        record = {"created": _now(), "status": "rolled_back", "backup_id": folder.name,
                  "files": [rel for rel, _ in restored], "approval_required": False}
        _append_history(record)
        return {"success": True, "rolled_back": True, "backup_id": folder.name,
                "files_restored": [rel for rel, _ in restored], "approval_required": False}
    return {"success": False, "rolled_back": False, "error": "No hay una copia aplicada disponible para revertir.", "approval_required": False}
