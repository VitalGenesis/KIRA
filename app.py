from flask import Flask, jsonify, render_template, request
import config
from agent import run, approve, reject
from approvals import list_pending
from memory import memory as mem
from memory.semantic import search as semantic_search
from tools import registry
from scheduler import start as scheduler_start

app=Flask(__name__)

@app.get('/')
def index():
    return render_template('index.html',model=config.OLLAMA_MODEL,workspace='PC COMPLETO (según permisos de Windows)')

@app.post('/api/chat')
def api_chat():
    data=request.get_json(silent=True) or {}; text=str(data.get('message') or '').strip()
    if not text: return jsonify({'error':'Mensaje vacío'}),400
    memory=mem.load(); result=run(text,memory)
    return jsonify(result)

@app.get('/api/history')
def api_history(): return jsonify(mem.load().get('history',[]))

@app.get('/api/status')
def api_status():
    return jsonify({'model':config.OLLAMA_MODEL,'vision_model':config.VISION_MODEL or config.OLLAMA_MODEL,'embed_model':config.EMBED_MODEL or None,'ollama_url':config.OLLAMA_URL,'full_pc_access':config.FULL_PC_ACCESS,'is_admin':__import__('tools.system',fromlist=['system_info']).system_info()['is_admin'],'tools':registry.public_definitions(),'pending_approvals':len(list_pending()),'semantic_memory':__import__('memory.semantic',fromlist=['status']).status()})

@app.get('/api/approvals')
def api_approvals(): return jsonify(list_pending())

@app.post('/api/approvals/<approval_id>/approve')
def api_approve(approval_id): return jsonify(approve(approval_id))

@app.post('/api/approvals/<approval_id>/reject')
def api_reject(approval_id): return jsonify(reject(approval_id))

@app.get('/api/memory/search')
def api_memory_search(): return jsonify(semantic_search(request.args.get('q',''),limit=int(request.args.get('limit','8'))))

@app.post('/api/voice/listen')
def api_voice_listen():
    from voice import listen
    return jsonify(listen(float((request.get_json(silent=True) or {}).get('seconds',5))))

@app.post('/api/voice/speak')
def api_voice_speak():
    from voice import speak
    data=request.get_json(silent=True) or {}; return jsonify(speak(data.get('text',''),data.get('rate',180),data.get('volume',1.0)))

if __name__=='__main__':
    config.ensure_dirs(); scheduler_start(); print('KIRA V8 -> http://127.0.0.1:5000'); app.run(host='127.0.0.1',port=5000,debug=False)
