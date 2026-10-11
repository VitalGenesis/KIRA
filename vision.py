from __future__ import annotations
import base64
from pathlib import Path

import requests

import config


class VisionError(RuntimeError):
    pass


def analyze_image(path: str, prompt='Describí detalladamente lo que aparece en la imagen, identificando texto, botones, campos, menús y elementos relevantes.'):
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_file():
        raise VisionError(f'No existe la imagen: {target}')
    model = config.VISION_MODEL or config.OLLAMA_MODEL
    image_b64 = base64.b64encode(target.read_bytes()).decode('ascii')
    payload = {
        'model': model,
        'messages': [{
            'role': 'user',
            'content': str(prompt),
            'images': [image_b64],
        }],
        'stream': False,
        'options': {'temperature': 0.1},
    }
    try:
        response = requests.post(f'{config.OLLAMA_URL}/api/chat', json=payload, timeout=config.OLLAMA_TIMEOUT)
    except requests.RequestException as e:
        raise VisionError(f'No pude conectar con Ollama: {e}') from e
    if response.status_code != 200:
        raise VisionError(f'El modelo de visión respondió {response.status_code}: {response.text[:500]}')
    data = response.json()
    text = data.get('message', {}).get('content', '').strip()
    if not text:
        raise VisionError('El modelo no devolvió descripción visual.')
    return {'model': model, 'image': str(target), 'analysis': text}
