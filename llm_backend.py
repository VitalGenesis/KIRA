import json
import requests

import config


class OllamaError(Exception):
    pass


def is_ollama_running():
    try:
        r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except requests.RequestException:
        return False


def chat(messages, model=None):
    model = model or config.OLLAMA_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.2,
        },
    }
    try:
        r = requests.post(
            f"{config.OLLAMA_URL}/api/chat",
            json=payload,
            timeout=config.OLLAMA_TIMEOUT,
        )
    except requests.RequestException as e:
        raise OllamaError(
            f"No pude conectarme a Ollama en {config.OLLAMA_URL}. Detalle: {e}"
        ) from e

    if r.status_code == 404:
        raise OllamaError(
            f"El modelo '{model}' no está disponible. Ejecutá: ollama pull {model}"
        )
    if r.status_code != 200:
        raise OllamaError(
            f"Ollama devolvió error {r.status_code}: {r.text[:500]}"
        )

    try:
        data = r.json()
    except ValueError as e:
        raise OllamaError("Ollama devolvió una respuesta JSON inválida.") from e

    content = data.get("message", {}).get("content", "")
    if not isinstance(content, str):
        raise OllamaError("Ollama no devolvió contenido de texto.")
    return content.strip()
