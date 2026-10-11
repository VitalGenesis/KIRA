from __future__ import annotations
import subprocess
from pathlib import Path

import config
from .registry import register


def run_command(command,cwd=None,timeout=None):
    workdir=str(Path(cwd).expanduser().resolve()) if cwd else str(config.BASE_DIR)
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',str(command)],cwd=workdir,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout or config.COMMAND_TIMEOUT)
    return {'command':str(command),'cwd':workdir,'returncode':p.returncode,'stdout':(p.stdout or '')[-config.MAX_COMMAND_OUTPUT:],'stderr':(p.stderr or '')[-config.MAX_COMMAND_OUTPUT:]}


def run_program(program,args=None,cwd=None,wait=False):
    program=str(Path(program).expanduser()) if ('\\' in str(program) or '/' in str(program)) else str(program)
    argv=[program]+[str(x) for x in (args or [])]
    proc=subprocess.Popen(argv,cwd=str(Path(cwd).expanduser().resolve()) if cwd else None)
    if wait:
        out,err=proc.communicate(timeout=config.COMMAND_TIMEOUT)
        return {'pid':proc.pid,'returncode':proc.returncode,'stdout':out or '','stderr':err or ''}
    return {'pid':proc.pid,'started':True,'program':program}

register('run_command','Ejecuta un comando PowerShell.',run_command,{'command':'string','cwd':'string opcional','timeout':'number opcional'},risk='high',confirm=True)
register('run_program','Inicia un programa o ejecutable.',run_program,{'program':'string','args':'array opcional','cwd':'string opcional','wait':'boolean opcional'},risk='medium')
