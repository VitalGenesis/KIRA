from __future__ import annotations
import ast
import importlib
import re
import sys
from pathlib import Path

import py_compile
import config
from .registry import register, TOOLS

_BLOCKED_IMPORTS={'ctypes','winreg','subprocess','socket','shutil'}


def _safe_module_name(name):
    n=re.sub(r'[^a-zA-Z0-9_]+','_',str(name).strip())
    if not n or n[0].isdigit(): n='tool_'+n
    return n.lower()


def _validate(code):
    tree=ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in _BLOCKED_IMPORTS: raise ValueError(f'Import bloqueado: {alias.name}')
        if isinstance(node,ast.ImportFrom) and (node.module or '').split('.')[0] in _BLOCKED_IMPORTS:
            raise ValueError(f'Import bloqueado: {node.module}')
    return tree


def create_tool(name,description,code,schema=None):
    module=_safe_module_name(name)
    path=config.TOOLS_DIR/(module+'.py'); config.TOOLS_DIR.mkdir(parents=True,exist_ok=True)
    _validate(str(code)); path.write_text(str(code),encoding='utf-8'); py_compile.compile(str(path),doraise=True)
    if str(config.TOOLS_DIR) not in sys.path: sys.path.insert(0,str(config.TOOLS_DIR))
    mod=importlib.import_module(module) if module not in sys.modules else importlib.reload(sys.modules[module])
    fn=getattr(mod,'run',None)
    if not callable(fn): raise ValueError("La herramienta debe exponer una función run(**args).")
    register(str(name),str(description),fn,schema or getattr(mod,'SCHEMA',{}),risk=getattr(mod,'RISK','medium'))
    return {'tool':str(name),'module':module,'path':str(path),'loaded':True}


def list_custom_tools():
    return [{'name':k,'description':v['description'],'risk':v['risk']} for k,v in TOOLS.items() if k not in {'list_custom_tools','create_tool'}]

register('create_tool','Crea, verifica y carga una nueva herramienta Python de KIRA en tools/custom/.',create_tool,{'name':'string','description':'string','code':'string','schema':'object opcional'},risk='high',confirm=True)
register('list_custom_tools','Lista herramientas registradas actualmente.',list_custom_tools,{})


def load_custom_tools():
    config.ensure_dirs()
    if str(config.TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(config.TOOLS_DIR))
    loaded=[]
    for path in sorted(config.TOOLS_DIR.glob('*.py')):
        if path.name.startswith('_'): continue
        try:
            code=path.read_text(encoding='utf-8')
            _validate(code)
            py_compile.compile(str(path), doraise=True)
            modname=path.stem
            mod=importlib.import_module(modname) if modname not in sys.modules else importlib.reload(sys.modules[modname])
            fn=getattr(mod,'run',None)
            if callable(fn):
                spec=getattr(mod,'TOOL_SPEC',{}) or {}
                register(spec.get('name',modname),spec.get('description',f'Herramienta personalizada {modname}'),fn,spec.get('schema',getattr(mod,'SCHEMA',{})),risk=spec.get('risk',getattr(mod,'RISK','medium')))
                loaded.append(modname)
        except Exception:
            continue
    return loaded
