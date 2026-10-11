import tempfile
from pathlib import Path
import config
from tools.filesystem import write_file, read_file, copy_path, move_path, delete_path, create_directory


def test_file_lifecycle():
    with tempfile.TemporaryDirectory() as d:
        old = config.BASE_DIR
        try:
            config.BASE_DIR = Path(d)
            p = Path(d) / "a.txt"
            write_file(str(p), "hola")
            assert read_file(str(p))["content"] == "hola"
            q = Path(d) / "b.txt"
            copy_path(str(p), str(q))
            r = Path(d) / "c.txt"
            move_path(str(q), str(r))
            delete_path(str(p))
            assert r.exists() and not p.exists()
            folder = Path(d) / "folder"
            create_directory(str(folder))
            assert folder.exists()
        finally:
            config.BASE_DIR = old


def test_overwrite_same_file():
    with tempfile.TemporaryDirectory() as d:
        old = config.BASE_DIR
        try:
            config.BASE_DIR = Path(d)
            p = Path(d) / 'arbol.py'
            write_file(str(p), 'print(1)')
            write_file(str(p), 'print(2)')
            assert p.name == 'arbol.py'
            assert read_file(str(p))['content'] == 'print(2)'
        finally:
            config.BASE_DIR = old
