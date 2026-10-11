'use strict';
const chat = document.getElementById('chat');
const form = document.getElementById('form');
const input = document.getElementById('input');
const send = document.getElementById('send');
const mic = document.getElementById('mic');
const approvals = document.getElementById('approvals');
const statusText = document.getElementById('status-text');
const thinking = document.getElementById('thinking');
const thinkingText = document.getElementById('thinking-text');
const welcome = document.getElementById('welcome');
const charCount = document.getElementById('char-count');
const toastRegion = document.getElementById('toast-region');

function displayText(value) {
  let text = typeof value === 'string' ? value : (value == null ? '' : JSON.stringify(value, null, 2));
  const candidates = [text.trim()];
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) candidates.unshift(fence[1].trim());
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate);
      if (parsed && typeof parsed === 'object') {
        if (parsed.type === 'final' && typeof parsed.content === 'string') return parsed.content.replace(/^\s*\\n\s*/,'').trim();
        if (typeof parsed.reply === 'string') return parsed.reply;
        if (typeof parsed.content === 'string' && Object.keys(parsed).length <= 3) return parsed.content;
      }
    } catch (_) { /* It was ordinary text, keep it intact. */ }
  }
  return text.replace(/^\s*\{\s*"type"\s*:\s*"final"\s*,\s*"content"\s*:\s*"/,'').replace(/"\s*\}\s*$/,'').replace(/\\n/g,'\n').replace(/\\"/g,'"').trim();
}

function toast(message, isError=false) {
  const node = document.createElement('div');
  node.className = `toast${isError ? ' error' : ''}`;
  node.textContent = message;
  toastRegion.appendChild(node);
  window.setTimeout(() => { node.style.opacity='0'; node.style.transform='translateY(6px)'; window.setTimeout(()=>node.remove(),240); }, 3300);
}

function hideWelcome() {
  if (welcome) welcome.hidden = true;
}

function scrollLatest(smooth=true) {
  chat.scrollTo({top:chat.scrollHeight,behavior:smooth?'smooth':'auto'});
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Mensaje copiado.');
  } catch (_) {
    const el=document.createElement('textarea'); el.value=text; el.style.position='fixed'; el.style.opacity='0'; document.body.appendChild(el); el.select();
    const ok=document.execCommand('copy'); el.remove(); toast(ok?'Mensaje copiado.':'No pude copiar automáticamente.',!ok);
  }
}

function addMessage(role, rawText, options={}) {
  const text=displayText(rawText);
  if (!text && !options.allowEmpty) return;
  hideWelcome();
  const row=document.createElement('article');
  row.className=`msg-row ${role==='user'?'user-row':'assistant-row'}`;
  const avatar=document.createElement('div'); avatar.className='avatar'; avatar.setAttribute('aria-hidden','true'); avatar.textContent=role==='user'?'TÚ':'K';
  const content=document.createElement('div'); content.className='message-content';
  const roleLabel=document.createElement('div'); roleLabel.className='message-role'; roleLabel.textContent=role==='user'?'TÚ':'KIRA · ASISTENTE LOCAL';
  const bubble=document.createElement('div'); bubble.className=`msg ${role}`; bubble.textContent=text;
  const actions=document.createElement('div'); actions.className='message-actions';
  const copy=document.createElement('button'); copy.type='button'; copy.className='mini-action'; copy.textContent='COPIAR'; copy.addEventListener('click',()=>copyText(text));
  actions.appendChild(copy);
  content.append(roleLabel,bubble,actions);
  row.append(avatar,content);
  chat.appendChild(row);
  scrollLatest();
  return row;
}

function addTool(event) {
  hideWelcome();
  const details=document.createElement('details'); details.className='tool-event';
  const summary=document.createElement('summary'); summary.textContent=`Herramienta · ${String(event.tool||'acción')} · ver detalles`;
  const pre=document.createElement('pre'); pre.textContent=JSON.stringify({args:event.args||{},result:event.result},null,2);
  details.append(summary,pre); chat.appendChild(details); scrollLatest();
}

async function loadStatus() {
  try {
    const response=await fetch('/api/status',{cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const d=await response.json();
    const model=d.model||'modelo local';
    document.getElementById('sidebar-model').textContent=model;
    document.getElementById('tool-count').textContent=Array.isArray(d.tools)?d.tools.length:'—';
    document.getElementById('admin-state').textContent=d.is_admin?'Sí':'No';
    document.getElementById('approval-count').textContent=Number(d.pending_approvals||0);
    document.getElementById('system-state').textContent='Motor conectado';
    document.getElementById('live-dot').classList.remove('offline');
    document.getElementById('header-live-dot').classList.remove('offline');
    statusText.textContent=`${model} · ${Array.isArray(d.tools)?d.tools.length:0} herramientas`;
  } catch (e) {
    statusText.textContent='No se pudo consultar el estado';
    document.getElementById('system-state').textContent='Estado desconocido';
    document.getElementById('live-dot').classList.add('offline');
    document.getElementById('header-live-dot').classList.add('offline');
  }
}

async function loadHistory() {
  try {
    const response=await fetch('/api/history',{cache:'no-store'});
    if (!response.ok) return;
    const items=await response.json();
    if (!Array.isArray(items)) return;
    items.forEach(item=>addMessage(item.role==='user'?'user':'assistant',item.content));
    if (!items.length && welcome) welcome.hidden=false;
    scrollLatest(false);
  } catch (_) { /* The chat remains usable for a new message. */ }
}

async function refreshApprovals() {
  try {
    const response=await fetch('/api/approvals',{cache:'no-store'});
    if (!response.ok) return;
    const items=await response.json();
    approvals.replaceChildren();
    const pending=Array.isArray(items)?items:[];
    document.getElementById('approval-count').textContent=pending.length;
    pending.forEach(item=>{
      const card=document.createElement('article'); card.className='approval';
      const info=document.createElement('div'); info.className='approval-info';
      const title=document.createElement('div'); title.className='approval-title'; title.textContent=`Confirmación requerida · ${item.tool||'acción'}`;
      const meta=document.createElement('span'); meta.className='approval-meta'; meta.textContent=`ID ${item.id||'—'} · RIESGO ${(item.risk||'desconocido').toString().toUpperCase()}`;
      const desc=document.createElement('div'); desc.className='approval-description'; desc.textContent=item.description||'Esta operación necesita confirmación.';
      info.append(title,meta,desc);
      const actions=document.createElement('div'); actions.className='approval-actions';
      const yes=document.createElement('button'); yes.type='button'; yes.className='approve'; yes.textContent='Aprobar'; yes.addEventListener('click',()=>resolveApproval(item.id,true,yes));
      const no=document.createElement('button'); no.type='button'; no.className='reject'; no.textContent='Rechazar'; no.addEventListener('click',()=>resolveApproval(item.id,false,no));
      actions.append(yes,no); card.append(info,actions); approvals.appendChild(card);
    });
  } catch (_) { /* Do not interrupt the conversation for status polling. */ }
}

async function resolveApproval(id, ok, button) {
  if (!id) return;
  button.disabled=true;
  try {
    const response=await fetch(`/api/approvals/${encodeURIComponent(id)}/${ok?'approve':'reject'}`,{method:'POST'});
    const data=await response.json();
    if (!response.ok) throw new Error(data.error||`HTTP ${response.status}`);
    if (data.reply) addMessage('assistant',data.reply);
    (data.tool_events||[]).forEach(addTool);
    toast(ok?'Acción aprobada.':'Acción rechazada.');
    await refreshApprovals();
  } catch (e) { toast(`No pude resolver la aprobación: ${e.message}`,true); button.disabled=false; }
}

function setThinking(show, message='Analizando tu solicitud…') {
  thinking.hidden=!show;
  thinkingText.textContent=message;
  if (show) scrollLatest();
}

async function sendMessage(message) {
  const clean=String(message||'').trim();
  if (!clean || send.disabled) return;
  addMessage('user',clean);
  input.value=''; updateComposer();
  send.disabled=true; mic.disabled=true;
  setThinking(true,'Consultando el modelo local y las herramientas…');
  try {
    const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:clean})});
    let data;
    try { data=await response.json(); } catch (_) { throw new Error(`El servidor devolvió una respuesta no JSON (HTTP ${response.status}).`); }
    if (!response.ok) throw new Error(data.error||`HTTP ${response.status}`);
    (data.tool_events||[]).forEach(addTool);
    const reply=data.reply||data.content||data.error||'KIRA terminó sin devolver texto.';
    addMessage('assistant',reply);
    if (data.approval_required || data.pending_approval) { toast('La acción necesita confirmación.'); await refreshApprovals(); }
    if (data.error) toast(data.error,true);
  } catch (e) {
    addMessage('assistant',`No pude completar la solicitud. ${e.message}`);
    toast('Falló la comunicación con KIRA.',true);
  } finally {
    setThinking(false); send.disabled=false; mic.disabled=false; input.focus(); await refreshApprovals();
  }
}

function updateComposer() {
  input.style.height='auto';
  input.style.height=`${Math.min(input.scrollHeight,180)}px`;
  charCount.textContent=`${input.value.length.toLocaleString('es-AR')} caracteres`;
}

form.addEventListener('submit',event=>{event.preventDefault();sendMessage(input.value);});
input.addEventListener('input',updateComposer);
input.addEventListener('keydown',event=>{
  if (event.key==='Enter'&&!event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
});
document.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>{
  input.value=button.dataset.prompt||''; updateComposer(); input.focus();
  input.scrollIntoView({block:'nearest',behavior:'smooth'});
}));
document.getElementById('scroll-latest').addEventListener('click',()=>scrollLatest());
mic.addEventListener('click',async()=>{
  mic.disabled=true; mic.classList.add('recording'); mic.title='Escuchando durante unos segundos…';
  toast('Grabando voz durante 5 segundos…');
  try {
    const response=await fetch('/api/voice/listen',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({seconds:5})});
    const data=await response.json();
    if (!response.ok) throw new Error(data.error||`HTTP ${response.status}`);
    if (data.text && data.text.trim()) await sendMessage(data.text.trim());
    else toast('No detecté palabras claras. Probá acercarte al micrófono.',true);
  } catch (e) { toast(`Voz no disponible: ${e.message}`,true); }
  finally {mic.disabled=false;mic.classList.remove('recording');mic.title='Grabar voz durante 5 segundos';}
});

loadStatus(); loadHistory(); refreshApprovals(); input.focus();
window.setInterval(()=>{loadStatus();refreshApprovals();},8000);
