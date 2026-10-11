"""Robust browser automation for KIRA V8 using Playwright."""
from __future__ import annotations

import os
import re
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import config
from .registry import register

class BrowserError(RuntimeError):
    pass

_pw = None
_context = None
_pages = []
_current_index = 0
_ref_meta = {}

INTERACTIVE_SELECTOR = (
    'a,button,input,textarea,select,option,'
    '[role="button"],[role="textbox"],[role="link"],[role="checkbox"],'
    '[role="radio"],[role="combobox"],[role="menuitem"],[role="tab"],'
    '[contenteditable="true"]'
)


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserError('Falta Playwright. Ejecutá setup_windows.ps1.') from exc
    return sync_playwright


def _detect_default_browser_executable():
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice') as key:
                prog_id, _ = winreg.QueryValueEx(key, 'ProgId')
            candidates = []
            if prog_id == 'MSEdgeHTM':
                candidates += [
                    os.path.expandvars(r'%PROGRAMFILES(X86)%\\Microsoft\\Edge\\Application\\msedge.exe'),
                    os.path.expandvars(r'%PROGRAMFILES%\\Microsoft\\Edge\\Application\\msedge.exe')]
            elif prog_id == 'ChromeHTML':
                candidates += [
                    os.path.expandvars(r'%PROGRAMFILES%\\Google\\Chrome\\Application\\chrome.exe'),
                    os.path.expandvars(r'%PROGRAMFILES(X86)%\\Google\\Chrome\\Application\\chrome.exe'),
                    os.path.expandvars(r'%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe')]
            for p in candidates:
                if Path(p).exists():
                    return p
        except Exception:
            pass
    for p in [
        os.path.expandvars(r'%PROGRAMFILES(X86)%\\Microsoft\\Edge\\Application\\msedge.exe'),
        os.path.expandvars(r'%PROGRAMFILES%\\Microsoft\\Edge\\Application\\msedge.exe'),
        os.path.expandvars(r'%PROGRAMFILES%\\Google\\Chrome\\Application\\chrome.exe'),
        os.path.expandvars(r'%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe'),
    ]:
        if Path(p).exists():
            return p
    return None


def _profile():
    p = config.BASE_DIR / 'browser_data' / 'profile'
    p.mkdir(parents=True, exist_ok=True)
    return p


def _downloads():
    p = config.BASE_DIR / 'browser_data' / 'downloads'
    p.mkdir(parents=True, exist_ok=True)
    return p


def _shots():
    p = config.BASE_DIR / 'browser_data' / 'screenshots'
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sync_pages():
    global _pages, _current_index
    if _context is None:
        return
    _pages = list(_context.pages)
    if not _pages:
        _pages = [_context.new_page()]
    _current_index = min(_current_index, len(_pages) - 1)


def _page():
    _sync_pages()
    return _pages[_current_index]


def _ensure_started():
    if _context is None:
        start_browser()
    return _page()


def _visible_text(page, limit=20000):
    try:
        text = page.locator('body').inner_text(timeout=5000)
    except Exception:
        text = ''
    return re.sub(r'\n{3,}', '\n\n', text)[:limit]


def _assign_refs(page):
    return page.evaluate(f"""(() => {{
        const selector = {INTERACTIVE_SELECTOR!r};
        let n=0;
        document.querySelectorAll(selector).forEach(el => {{
          const s=getComputedStyle(el), r=el.getBoundingClientRect();
          const visible=s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0;
          if(!visible) return; n++; el.setAttribute('data-kira-ref','k'+n);
        }}); return n;
    }})()""")


def _interactive_snapshot(page, max_items=160):
    _assign_refs(page)
    data = page.locator('[data-kira-ref]').evaluate_all("""
      els => els.map(el => {
        const r=el.getBoundingClientRect(), type=el.getAttribute('type')||'';
        const role=el.getAttribute('role')||el.tagName.toLowerCase();
        const aria=el.getAttribute('aria-label')||'';
        const label=el.getAttribute('name')||'';
        const placeholder=el.getAttribute('placeholder')||'';
        const title=el.getAttribute('title')||'';
        const text=(el.innerText||el.value||'').trim().replace(/\\s+/g,' ').slice(0,180);
        const name=(aria||label||placeholder||text||title);
        const displayName=(name||(type==='password'?'password':'' )).slice(0,180);
        return {
          ref:el.getAttribute('data-kira-ref'), tag:el.tagName.toLowerCase(), role, name:displayName, type,
          aria, label, placeholder, title,
          disabled:!!el.disabled||el.getAttribute('aria-disabled')==='true',
          checked:('checked' in el)?!!el.checked:null,
          value:type==='password'?'[HIDDEN]':String(el.value??'').slice(0,160),
          href:el.href||'',
          box:{x:Math.round(r.x),y:Math.round(r.y),width:Math.round(r.width),height:Math.round(r.height)}
        };
      })
    """)[:max_items]
    for item in data:
        _ref_meta[item['ref']] = item.copy()
    return data


def _ref_locator(ref):
    page = _page()
    ref = str(ref or '').strip()
    if not re.fullmatch(r'k\d+', ref):
        raise BrowserError('Referencia inválida.')
    loc = page.locator(f'[data-kira-ref="{ref}"]')
    if loc.count():
        return loc.first
    meta = _ref_meta.get(ref, {})
    # Recover stale refs after DOM changes.
    candidates = []
    if meta.get('aria'):
        candidates.append(page.get_by_label(meta['aria'], exact=True))
        candidates.append(page.get_by_role(meta.get('role',''), name=meta['aria'], exact=True) if meta.get('role') in {'button','link','tab','checkbox','radio','textbox','combobox','menuitem'} else None)
    if meta.get('placeholder'):
        candidates.append(page.get_by_placeholder(meta['placeholder'], exact=True))
    if meta.get('label'):
        candidates.append(page.locator(f'[name="{meta["label"].replace(chr(34), chr(92)+chr(34))}"]'))
    if meta.get('name') and len(meta['name']) < 120:
        candidates.append(page.get_by_text(meta['name'], exact=True))
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            if candidate.count():
                return candidate.first
        except Exception:
            pass
    _assign_refs(page)
    raise BrowserError(f'No encuentro {ref}; la interfaz cambió. Ejecutá browser_observe nuevamente.')


def start_browser():
    global _pw, _context, _pages, _current_index
    if _context is not None:
        return {'started': True, 'pages': len(_context.pages), 'profile': str(_profile())}
    sync_playwright = _require_playwright()
    _pw = sync_playwright().start()
    executable = _detect_default_browser_executable()
    kwargs = {
        'headless': False, 'accept_downloads': True, 'viewport': None,
        'downloads_path': str(_downloads()), 'args': ['--start-maximized']
    }
    if executable:
        kwargs['executable_path'] = executable
    try:
        _context = _pw.chromium.launch_persistent_context(user_data_dir=str(_profile()), **kwargs)
    except Exception as exc:
        if executable:
            kwargs.pop('executable_path', None)
            try:
                _context = _pw.chromium.launch_persistent_context(user_data_dir=str(_profile()), **kwargs)
            except Exception as exc2:
                _pw.stop(); _pw=None
                raise BrowserError(f'No pude iniciar Chromium: {exc2}') from exc2
        else:
            _pw.stop(); _pw=None
            raise BrowserError(f'No pude iniciar Chromium: {exc}') from exc
    _sync_pages()
    return {'started': True, 'browser': 'chromium-compatible', 'executable': executable or 'Playwright Chromium', 'profile': str(_profile()), 'persistent_login': True, 'pages': len(_pages)}


def stop_browser():
    global _pw, _context, _pages, _current_index, _ref_meta
    if _context is not None: _context.close()
    if _pw is not None: _pw.stop()
    _pw=None; _context=None; _pages=[]; _current_index=0; _ref_meta={}
    return {'stopped': True}


def _after_nav(page):
    page.wait_for_timeout(400)
    return {'url': page.url, 'title': page.title(), 'text': _visible_text(page, 7000)}


def browser_goto(url):
    page = _ensure_started()
    parsed=urlparse(str(url).strip())
    if parsed.scheme not in {'http','https'} or not parsed.netloc:
        raise BrowserError('Solo se permiten URLs http/https.')
    page.goto(str(url).strip(), wait_until='domcontentloaded', timeout=config.BROWSER_NAV_TIMEOUT*1000)
    return _after_nav(page)


def browser_observe(max_elements=160, include_aria=True):
    page=_ensure_started(); _ref_meta.clear()
    data={'url':page.url,'title':page.title(),'text':_visible_text(page),'interactive_elements':_interactive_snapshot(page,max(1,min(int(max_elements),250))),
          'tabs':[{'index':i,'url':p.url,'title':p.title()} for i,p in enumerate(_pages)]}
    if include_aria:
        try:
            data['aria_snapshot']=page.aria_snapshot(mode='ai', boxes=True, timeout=10000)[:35000]
        except Exception as exc:
            data['aria_snapshot_error']=str(exc)
    return data


def browser_screenshot(filename=None, full_page=False):
    page=_ensure_started()
    target=Path(filename).expanduser() if filename else _shots()/f'browser_{int(time.time())}.png'
    if not target.is_absolute(): target=config.BASE_DIR/target
    target=target.resolve(); target.parent.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(target), full_page=bool(full_page))
    return {'path':str(target),'url':page.url}


def browser_click(ref,button='left',click_count=1):
    page=_ensure_started(); loc=_ref_locator(ref)
    loc.scroll_into_view_if_needed(); loc.click(button=str(button), click_count=int(click_count), timeout=config.BROWSER_ACTION_TIMEOUT*1000)
    page.wait_for_timeout(350); _sync_pages()
    return {'clicked':ref,'url':page.url,'title':page.title(),'text':_visible_text(page,5000)}


def browser_click_text(text, exact=False):
    page=_ensure_started(); text=str(text)
    loc = page.get_by_text(text, exact=bool(exact)).first
    if not loc.count():
        loc = page.get_by_role('button', name=text, exact=bool(exact)).first
    if not loc.count():
        raise BrowserError(f'No encuentro texto/control: {text}')
    loc.scroll_into_view_if_needed(); loc.click(timeout=config.BROWSER_ACTION_TIMEOUT*1000); page.wait_for_timeout(350)
    return {'clicked_text':text,'url':page.url,'title':page.title()}


def browser_fill(ref,text_value):
    loc=_ref_locator(ref); value=str(text_value); loc.fill(value, timeout=config.BROWSER_ACTION_TIMEOUT*1000)
    typ=loc.get_attribute('type') or ''
    return {'filled':ref,'type':typ,'value_saved':typ!='password'}


def browser_fill_by_label(label,text_value):
    page=_ensure_started(); loc=page.get_by_label(str(label), exact=True).first
    if not loc.count(): loc=page.get_by_placeholder(str(label), exact=True).first
    if not loc.count(): raise BrowserError(f'No encuentro un campo para: {label}')
    loc.fill(str(text_value), timeout=config.BROWSER_ACTION_TIMEOUT*1000)
    return {'label':str(label),'filled':True,'value_saved':(loc.get_attribute('type') or '')!='password'}


def browser_login(username_ref,username,password_ref,password,submit_ref=None):
    browser_fill(username_ref,username); browser_fill(password_ref,password)
    if submit_ref: browser_click(submit_ref)
    return {'submitted':bool(submit_ref),'url':_page().url,'title':_page().title()}


def browser_press(ref,key):
    loc=_ref_locator(ref); loc.press(str(key)); _page().wait_for_timeout(250); return {'ref':ref,'key':key}

def browser_keypress(key):
    page=_ensure_started(); page.keyboard.press(str(key)); page.wait_for_timeout(250); return {'key':key,'url':page.url}

def browser_scroll(amount=800,direction='down'):
    page=_ensure_started(); delta=abs(int(amount)) if str(direction).lower()=='down' else -abs(int(amount)); page.mouse.wheel(0,delta); page.wait_for_timeout(250); return {'direction':direction,'scroll_y':page.evaluate('window.scrollY')}

def browser_hover(ref):
    loc=_ref_locator(ref); loc.scroll_into_view_if_needed(); loc.hover(timeout=config.BROWSER_ACTION_TIMEOUT*1000); return {'hovered':ref}

def browser_check(ref,checked=True):
    loc=_ref_locator(ref); (loc.check if checked else loc.uncheck)(timeout=config.BROWSER_ACTION_TIMEOUT*1000); return {'ref':ref,'checked':bool(checked)}

def browser_select(ref,value=None,label=None,index=None):
    loc=_ref_locator(ref)
    if value is not None: out=loc.select_option(value=str(value))
    elif label is not None: out=loc.select_option(label=str(label))
    elif index is not None: out=loc.select_option(index=int(index))
    else: raise BrowserError('Necesitás value, label o index.')
    return {'ref':ref,'selected':out}

def browser_upload(ref,file_path):
    path=Path(str(file_path)).expanduser().resolve()
    if not path.is_file(): raise BrowserError(f'No existe el archivo: {path}')
    _ref_locator(ref).set_input_files(str(path)); return {'ref':ref,'file':str(path),'uploaded':True}

def browser_tabs():
    _sync_pages(); return {'current':_current_index,'tabs':[{'index':i,'url':p.url,'title':p.title()} for i,p in enumerate(_pages)]}

def browser_switch_tab(index):
    global _current_index
    _sync_pages(); i=int(index)
    if i<0 or i>=len(_pages): raise BrowserError('Índice de pestaña inválido.')
    _current_index=i; _pages[i].bring_to_front(); return {'current':i,'url':_pages[i].url,'title':_pages[i].title()}

def browser_new_tab(url=None):
    global _current_index
    _ensure_started(); p=_context.new_page(); _sync_pages(); _current_index=_pages.index(p)
    if url: return browser_goto(url)
    return {'current':_current_index,'url':p.url,'title':p.title()}

def browser_close_tab():
    _page().close(); _sync_pages(); return {'closed':True,'current':_current_index,'tabs':len(_pages)}

def browser_back(): _page().go_back(wait_until='domcontentloaded',timeout=config.BROWSER_NAV_TIMEOUT*1000); return _after_nav(_page())
def browser_forward(): _page().go_forward(wait_until='domcontentloaded',timeout=config.BROWSER_NAV_TIMEOUT*1000); return _after_nav(_page())
def browser_refresh(): _page().reload(wait_until='domcontentloaded',timeout=config.BROWSER_NAV_TIMEOUT*1000); return _after_nav(_page())
def browser_wait(seconds=1): _page().wait_for_timeout(max(0,min(float(seconds),30))*1000); return {'waited_seconds':float(seconds),'url':_page().url}
def browser_open_default(url):
    url=str(url).strip()
    if not url.startswith(('http://','https://')): raise BrowserError('URL inválida.')
    return {'url':url,'opened':bool(webbrowser.open(url))}

def browser_dom_find(text=None,role=None,placeholder=None,css=None):
    page=_ensure_started(); matches=[]
    selectors=[]
    if css: selectors.append(page.locator(css))
    if role: selectors.append(page.get_by_role(role))
    if placeholder: selectors.append(page.get_by_placeholder(placeholder,exact=True))
    if text: selectors.append(page.get_by_text(text,exact=True))
    for loc in selectors:
        try:
            n=min(loc.count(),30)
            for i in range(n):
                e=loc.nth(i); box=e.bounding_box(); matches.append({'index':i,'visible':e.is_visible(),'text':(e.inner_text() if e.is_visible() else '')[:150],'box':box})
        except Exception: pass
    return {'matches':matches[:50]}

def youtube_play(query):
    page=_ensure_started(); query=str(query).strip()
    page.goto('https://www.youtube.com/results?search_query='+quote_plus(query),wait_until='domcontentloaded',timeout=config.BROWSER_NAV_TIMEOUT*1000)
    page.wait_for_timeout(1200)
    for label in ['Accept all','Aceptar todo','I agree','Acepto']:
        try:
            btn=page.get_by_role('button',name=label)
            if btn.count() and btn.first.is_visible(): btn.first.click(timeout=2000); page.wait_for_timeout(300); break
        except Exception: pass
    video=page.locator('a#video-title[href*="/watch"]')
    if video.count():
        video.first.click(timeout=config.BROWSER_ACTION_TIMEOUT*1000); page.wait_for_timeout(1200)
        return {'query':query,'mode':'video','url':page.url,'title':page.title()}
    return {'query':query,'mode':'search','url':page.url,'title':page.title()}

register('browser_start','Inicia navegador con perfil persistente.',start_browser,{})
register('browser_stop','Cierra navegador controlado.',stop_browser,{})
register('browser_goto','Navega a una URL.',browser_goto,{'url':'string'})
register('browser_observe','Observa página, DOM, ARIA y controles interactivos.',browser_observe,{'max_elements':'number opcional','include_aria':'boolean opcional'})
register('browser_screenshot','Captura la página.',browser_screenshot,{'filename':'string opcional','full_page':'boolean opcional'})
register('browser_click','Hace clic por ref.',browser_click,{'ref':'string','button':'string opcional','click_count':'number opcional'},risk='medium')
register('browser_click_text','Hace clic por texto/rol sin ref.',browser_click_text,{'text':'string','exact':'boolean opcional'},risk='medium')
register('browser_fill','Rellena un campo por ref.',browser_fill,{'ref':'string','text_value':'string'},risk='medium')
register('browser_fill_by_label','Rellena un campo por etiqueta/placeholder.',browser_fill_by_label,{'label':'string','text_value':'string'},risk='medium')
register('browser_login','Completa login; no devuelve la contraseña.',browser_login,{'username_ref':'string','username':'string','password_ref':'string','password':'sensitive','submit_ref':'string opcional'},risk='high',confirm=True)
register('browser_press','Pulsa tecla en elemento.',browser_press,{'ref':'string','key':'string'},risk='medium')
register('browser_keypress','Pulsa tecla global.',browser_keypress,{'key':'string'},risk='medium')
register('browser_scroll','Hace scroll.',browser_scroll,{'amount':'number opcional','direction':'string opcional'})
register('browser_hover','Hover.',browser_hover,{'ref':'string'})
register('browser_check','Marca/desmarca.',browser_check,{'ref':'string','checked':'boolean'},risk='medium')
register('browser_select','Selecciona opción.',browser_select,{'ref':'string','value':'string opcional','label':'string opcional','index':'number opcional'},risk='medium')
register('browser_upload','Sube archivo.',browser_upload,{'ref':'string','file_path':'string'},risk='medium')
register('browser_tabs','Lista pestañas.',browser_tabs,{})
register('browser_switch_tab','Cambia pestaña.',browser_switch_tab,{'index':'number'})
register('browser_new_tab','Abre pestaña.',browser_new_tab,{'url':'string opcional'})
register('browser_close_tab','Cierra pestaña.',browser_close_tab,{},risk='medium')
register('browser_back','Atrás.',browser_back,{})
register('browser_forward','Avanzar.',browser_forward,{})
register('browser_refresh','Recargar.',browser_refresh,{})
register('browser_wait','Espera.',browser_wait,{'seconds':'number opcional'})
register('browser_open_default','Abre URL en navegador predeterminado.',browser_open_default,{'url':'string'})
register('browser_dom_find','Busca controles por DOM/texto/role.',browser_dom_find,{'text':'string opcional','role':'string opcional','placeholder':'string opcional','css':'string opcional'})
register('youtube_play','Busca y abre un video en YouTube.',youtube_play,{'query':'string'},risk='medium')
