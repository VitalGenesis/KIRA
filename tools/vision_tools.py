from .registry import register
from vision import analyze_image
from .desktop import screenshot as desktop_screenshot


def vision_analyze(path, prompt=None):
    return analyze_image(path, prompt or 'Analizá esta captura de pantalla para ayudar a un agente a interactuar con ella. Identificá ventanas, botones, campos, textos, menús, coordenadas aproximadas si son evidentes y la acción más probable solicitada por el usuario.')


def vision_analyze_desktop(prompt=None):
    shot = desktop_screenshot()
    result = analyze_image(shot['path'], prompt or 'Analizá esta pantalla de Windows. Identificá la aplicación activa, controles visibles, campos, botones, menús, mensajes de error y cómo completar la acción pedida.')
    result['screenshot'] = shot['path']
    return result


register('vision_analyze', 'Analiza una imagen con un modelo multimodal local.', vision_analyze, {'path': 'string', 'prompt': 'string opcional'}, risk='low')
register('vision_analyze_desktop', 'Captura y analiza visualmente el escritorio con un modelo multimodal local.', vision_analyze_desktop, {'prompt': 'string opcional'}, risk='low')
