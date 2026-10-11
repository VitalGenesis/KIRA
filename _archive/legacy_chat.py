"""
ChatGPT local — versión de terminal. Para la interfaz web, correr
app.py en su lugar.

    python chat.py

Ver README.md para instalación paso a paso.
"""

import sys

import config
from web_search import search_available
from engine import (
    load_memory,
    save_memory,
    handle_message,
    extract_image_prompt,
    extract_search_query,
)


def print_banner():
    print("==============================================")
    print("   CHATGPT LOCAL (100% en tu PC) — terminal")
    print("==============================================")
    print(f"Modelo de chat: {config.OLLAMA_MODEL} (Ollama)")
    print(f"Modelo de imágenes: {config.IMAGE_MODEL} (diffusers)")
    print(f"Búsqueda web: {'disponible' if search_available() else 'NO instalada (pip install duckduckgo-search)'}")
    print()
    print("Tip: 'python app.py' te da la versión con interfaz web.")
    print("Hablá normal. Para forzar una imagen: 'imagen: <descripción>'.")
    print("Para forzar una búsqueda: 'busca: <consulta>'.")
    print("Escribí 'salir' para terminar.\n")


def main():
    memory = load_memory()
    print_banner()

    while True:
        try:
            user_text = input("Vos: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nChau.")
            break

        if not user_text:
            continue
        if user_text.lower() in ("salir", "exit", "quit"):
            print("Bot: Chau!")
            break

        if extract_image_prompt(user_text):
            print("Bot: Generando imagen localmente, un momento...")
        elif extract_search_query(user_text):
            print("Bot: Buscando en internet...")

        result = handle_message(user_text, memory)
        reply = result["reply"]

        print(f"Bot: {reply}")
        if result.get("image_path"):
            print(f"     (imagen guardada en: {result['image_path']})")
        print()

        memory["history"].append({"role": "user", "content": user_text})
        memory["history"].append({"role": "assistant", "content": reply})
        save_memory(memory)


if __name__ == "__main__":
    sys.exit(main() or 0)
