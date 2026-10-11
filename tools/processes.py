import json, subprocess
from .registry import register


def _ps(command):
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    try: data=json.loads(p.stdout or 'null')
    except json.JSONDecodeError: data=p.stdout
    return {'returncode':p.returncode,'stderr':p.stderr[-4000:],'data':data}


def list_processes(filter_text=None,limit=200):
    result=_ps('Get-Process | Select-Object Id,ProcessName,CPU,WorkingSet64,Path | ConvertTo-Json -Depth 2')
    data=result['data']
    if isinstance(data,dict): data=[data]
    if not isinstance(data,list): return result
    if filter_text:
        needle=str(filter_text).lower(); data=[x for x in data if needle in str(x.get('ProcessName','')).lower()]
    return {'count':len(data[:int(limit)]),'processes':data[:int(limit)]}


def start_process(program,args=None,cwd=None,wait=False):
    from .terminal import run_program
    return run_program(program,args,cwd,wait)


def stop_process(pid=None,name=None,force=False):
    if not pid and not name: raise ValueError('Indica pid o nombre.')
    if pid: cmd=f'Stop-Process -Id {int(pid)} {"-Force" if force else ""}'
    else:
        n=str(name).replace("'","''"); cmd=f"Stop-Process -Name '{n}' {'-Force' if force else ''}"
    return _ps(cmd)

register('list_processes','Lista procesos activos de Windows.',list_processes,{'filter_text':'string opcional','limit':'number opcional'})
register('start_process','Inicia un proceso.',start_process,{'program':'string','args':'array opcional','cwd':'string opcional','wait':'boolean opcional'},risk='medium')
register('stop_process','Finaliza un proceso.',stop_process,{'pid':'number opcional','name':'string opcional','force':'boolean opcional'},risk='high',confirm=True)
