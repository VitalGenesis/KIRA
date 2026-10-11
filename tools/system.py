import ctypes
import os
import platform
import socket
import subprocess
from datetime import datetime

from .registry import register


def _is_admin():
    if os.name != 'nt': return False
    try: return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception: return False


def system_info():
    return {'os':platform.platform(),'computer':platform.node(),'python':platform.python_version(),
            'cpu_count':os.cpu_count(),'user':os.getenv('USERNAME') or os.getenv('USER'),
            'hostname':socket.gethostname(),'time':datetime.now().astimezone().isoformat(),
            'is_admin':_is_admin(),'cwd':os.getcwd()}


def open_in_explorer(path):
    target=os.path.abspath(os.path.expanduser(str(path)))
    if os.name=='nt': subprocess.Popen(['explorer.exe',target])
    else: subprocess.Popen(['xdg-open',target])
    return {'opened':target}

register('system_info','Devuelve información detallada del PC, usuario y permisos.',system_info,{})
register('open_in_explorer','Abre un archivo o carpeta con Windows Explorer.',open_in_explorer,{'path':'string'})
