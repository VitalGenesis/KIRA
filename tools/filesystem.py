from pathlib import Path
import shutil
import os
import stat

import config
from .registry import register


class FilesystemError(Exception):
    pass


def _path(user_path):
    raw = str(user_path or "").strip()
    if not raw:
        raise FilesystemError("Falta la ruta.")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (config.BASE_DIR / p)
    return p.resolve(strict=False)


def list_files(path=".", recursive=False, limit=5000):
    base = _path(path)
    if not base.exists():
        raise FilesystemError(f"No existe: {base}")
    if not base.is_dir():
        raise FilesystemError(f"No es una carpeta: {base}")
    limit = max(1, min(int(limit), 20000))
    iterator = base.rglob("*") if recursive else base.iterdir()
    items = []
    for p in iterator:
        try:
            st = p.stat()
            items.append({
                "path": str(p),
                "name": p.name,
                "type": "dir" if p.is_dir() else "file",
                "size": st.st_size if p.is_file() else None,
                "modified": st.st_mtime,
            })
        except OSError as e:
            items.append({"path": str(p), "error": str(e)})
        if len(items) >= limit:
            break
    return {"path": str(base), "items": items, "truncated": len(items) >= limit}


def read_file(path, max_bytes=1000000):
    target = _path(path)
    if not target.exists():
        raise FilesystemError(f"No existe: {target}")
    if not target.is_file():
        raise FilesystemError(f"No es un archivo: {target}")
    max_bytes = max(1, min(int(max_bytes), 10000000))
    # Read max_bytes + 1 only. The extra byte detects truncation without
    # loading a potentially huge file into RAM.
    with target.open("rb") as stream:
        data = stream.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    text = data.decode("utf-8", errors="replace")
    return {
        "path": str(target),
        "content": text,
        "bytes": len(data),
        "total_bytes": target.stat().st_size,
        "truncated": truncated,
    }


def write_file(path, content, encoding="utf-8"):
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_dir():
        raise FilesystemError(f"No se puede escribir sobre una carpeta: {target}")
    target.write_text(str(content), encoding=encoding)
    return {"path": str(target), "bytes": target.stat().st_size, "action": "written"}


def append_file(path, content, encoding="utf-8"):
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding=encoding) as f:
        f.write(str(content))
    return {"path": str(target), "bytes": target.stat().st_size, "action": "appended"}


def create_directory(path):
    target = _path(path)
    target.mkdir(parents=True, exist_ok=True)
    return {"path": str(target), "action": "created"}


def copy_path(source, destination, overwrite=False):
    src = _path(source)
    dst = _path(destination)
    if not src.exists():
        raise FilesystemError(f"Origen inexistente: {src}")
    if dst.exists() and not overwrite:
        raise FilesystemError(f"Destino ya existe: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists() and overwrite:
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return {"source": str(src), "destination": str(dst), "action": "copied"}


def move_path(source, destination, overwrite=False):
    src = _path(source)
    dst = _path(destination)
    if not src.exists():
        raise FilesystemError(f"Origen inexistente: {src}")
    if dst.exists() and not overwrite:
        raise FilesystemError(f"Destino ya existe: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and overwrite:
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    shutil.move(str(src), str(dst))
    return {"source": str(src), "destination": str(dst), "action": "moved"}


def delete_path(path, recursive=False):
    target = _path(path)
    if not target.exists():
        return {"path": str(target), "action": "already_absent"}
    if target.is_dir():
        if not recursive:
            try:
                target.rmdir()
            except OSError as e:
                raise FilesystemError(f"La carpeta no está vacía; usa recursive=true: {e}") from e
        else:
            shutil.rmtree(target)
    else:
        target.unlink()
    return {"path": str(target), "action": "deleted"}


def exists(path):
    target = _path(path)
    return {"path": str(target), "exists": target.exists(), "is_file": target.is_file(), "is_dir": target.is_dir()}


def make_empty_file(path):
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(exist_ok=True)
    return {"path": str(target), "action": "touched"}


register("list_files", "Lista archivos/carpetas en cualquier ruta accesible.", list_files,
         {"path": "string", "recursive": "boolean opcional", "limit": "number opcional"})
register("read_file", "Lee un archivo de texto en cualquier ruta accesible.", read_file,
         {"path": "string", "max_bytes": "number opcional"})
register("write_file", "Crea o reemplaza un archivo de texto.", write_file,
         {"path": "string", "content": "string", "encoding": "string opcional"})
register("append_file", "Agrega texto al final de un archivo.", append_file,
         {"path": "string", "content": "string", "encoding": "string opcional"})
register("create_directory", "Crea una carpeta y sus padres.", create_directory,
         {"path": "string"})
register("copy_path", "Copia un archivo o carpeta.", copy_path,
         {"source": "string", "destination": "string", "overwrite": "boolean opcional"})
register("move_path", "Mueve o renombra un archivo/carpeta.", move_path,
         {"source": "string", "destination": "string", "overwrite": "boolean opcional"})
register("delete_path", "Elimina un archivo o carpeta.", delete_path,
         {"path": "string", "recursive": "boolean opcional"})
register("exists", "Comprueba si una ruta existe y su tipo.", exists,
         {"path": "string"})
register("touch_file", "Crea un archivo vacío si no existe.", make_empty_file,
         {"path": "string"})
