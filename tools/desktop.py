from __future__ import annotations
import os
import subprocess
import time
from pathlib import Path

import config
from .registry import register

try:
    import pyautogui
except Exception:
    pyautogui = None


class DesktopError(RuntimeError):
    pass


def _require():
    if pyautogui is None:
        raise DesktopError('Falta pyautogui. Ejecutá setup_windows.ps1.')
    pyautogui.PAUSE = 0.08
    pyautogui.FAILSAFE = True


def screenshot(filename=None):
    _require()
    target = Path(filename) if filename else config.DESKTOP_SCREENSHOT_DIR / f'desktop_{int(time.time())}.png'
    if not target.is_absolute():
        target = config.BASE_DIR / target
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    pyautogui.screenshot(str(target))
    return {'path': str(target), 'size': pyautogui.size()}


def click(x, y, clicks=1, button='left'):
    _require()
    pyautogui.click(int(x), int(y), clicks=int(clicks), button=str(button))
    return {'x': int(x), 'y': int(y), 'clicks': int(clicks), 'button': button}


def move(x, y, duration=0.15):
    _require()
    pyautogui.moveTo(int(x), int(y), duration=max(0.0, float(duration)))
    return {'x': int(x), 'y': int(y)}


def scroll(clicks=5):
    _require()
    pyautogui.scroll(int(clicks))
    return {'scroll': int(clicks)}


def type_text(text, interval=0.01):
    _require()
    pyautogui.write(str(text), interval=max(0.0, float(interval)))
    return {'typed_chars': len(str(text))}


def hotkey(keys):
    _require()
    if not keys:
        raise DesktopError('Faltan teclas.')
    keys=[str(k) for k in keys]
    pyautogui.hotkey(*keys)
    return {'keys': keys}


def press(key, presses=1):
    _require()
    pyautogui.press(str(key), presses=max(1, int(presses)), interval=0.03)
    return {'key': key, 'presses': int(presses)}


def open_path(path):
    target = str(Path(path).expanduser())
    if os.name == 'nt':
        os.startfile(target)
    else:
        subprocess.Popen(['xdg-open', target])
    return {'opened': target}


def active_window():
    _require()
    try:
        title = pyautogui.getActiveWindowTitle()
    except Exception:
        title = None
    return {'title': title, 'position': pyautogui.position(), 'screen': pyautogui.size()}


register('desktop_screenshot', 'Captura la pantalla completa del escritorio.', screenshot, {'filename': 'string opcional'}, risk='low')
register('desktop_click', 'Hace clic con el mouse en coordenadas del escritorio.', click, {'x': 'number', 'y': 'number', 'clicks': 'number opcional', 'button': 'string opcional'}, risk='medium')
register('desktop_move', 'Mueve el mouse a coordenadas del escritorio.', move, {'x': 'number', 'y': 'number', 'duration': 'number opcional'}, risk='low')
register('desktop_scroll', 'Desplaza el escritorio/página con la rueda del mouse.', scroll, {'clicks': 'number opcional'}, risk='low')
register('desktop_type', 'Escribe texto en el control que tenga el foco.', type_text, {'text': 'string', 'interval': 'number opcional'}, risk='medium')
register('desktop_hotkey', 'Pulsa una combinación de teclas.', hotkey, {'keys': 'array'}, risk='medium')
register('desktop_press', 'Pulsa una tecla.', press, {'key': 'string', 'presses': 'number opcional'}, risk='low')
register('desktop_open_path', 'Abre un archivo o carpeta con la aplicación predeterminada.', open_path, {'path': 'string'}, risk='low')
register('desktop_active_window', 'Informa qué ventana está activa y posición del cursor.', active_window, {}, risk='low')
