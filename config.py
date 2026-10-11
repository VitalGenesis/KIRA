import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
VISION_MODEL = os.getenv("KIRA_VISION_MODEL", os.getenv("OLLAMA_VISION_MODEL", ""))
EMBED_MODEL = os.getenv("KIRA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))

FULL_PC_ACCESS = os.getenv("KIRA_FULL_PC_ACCESS", "1") == "1"
MEMORY_DIR = BASE_DIR / "memory"
MEMORY_PATH = Path(os.getenv("KIRA_MEMORY_PATH", str(MEMORY_DIR / "conversation.json"))).expanduser().resolve()
SEMANTIC_DB = Path(os.getenv("KIRA_SEMANTIC_DB", str(MEMORY_DIR / "semantic.sqlite3"))).expanduser().resolve()

RUNTIME_DIR = BASE_DIR / "runtime"
APPROVALS_PATH = RUNTIME_DIR / "approvals.json"
SCHEDULES_PATH = RUNTIME_DIR / "schedules.json"  # legacy JSON migration source
PLANS_PATH = RUNTIME_DIR / "plans.json"  # legacy JSON migration source
SCHEDULES_DB = Path(os.getenv("KIRA_SCHEDULES_DB", str(RUNTIME_DIR / "schedules.sqlite3"))).expanduser().resolve()
PLANS_DB = Path(os.getenv("KIRA_PLANS_DB", str(RUNTIME_DIR / "plans.sqlite3"))).expanduser().resolve()

TOOLS_DIR = BASE_DIR / "tools" / "custom"

MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "40"))
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "40"))
MAX_PLAN_STEPS = int(os.getenv("KIRA_MAX_PLAN_STEPS", "50"))
COMMAND_TIMEOUT = int(os.getenv("KIRA_COMMAND_TIMEOUT", "120"))
MAX_COMMAND_OUTPUT = int(os.getenv("KIRA_MAX_COMMAND_OUTPUT", "30000"))

BROWSER_NAV_TIMEOUT = int(os.getenv("KIRA_BROWSER_NAV_TIMEOUT", "45"))
BROWSER_ACTION_TIMEOUT = int(os.getenv("KIRA_BROWSER_ACTION_TIMEOUT", "20"))

DESKTOP_SCREENSHOT_DIR = BASE_DIR / "desktop_data" / "screenshots"
VOICE_DIR = BASE_DIR / "voice_data"

# 0 = ask for approval on medium/high-risk actions; 1 = auto-approve medium risk.
AUTO_APPROVE_MEDIUM = os.getenv("KIRA_AUTO_APPROVE_MEDIUM", "1") == "1"
AUTO_APPROVE_HIGH = os.getenv("KIRA_AUTO_APPROVE_HIGH", "0") == "1"

SYSTEM_PROMPT = """Sos KIRA, un agente local avanzado para Windows.
Respondé en español salvo que te pidan otro idioma.

CAPACIDADES:
- conversación y memoria persistente/semántica;
- archivos y carpetas del PC;
- PowerShell y programas/procesos;
- navegador web controlado;
- visión mediante capturas y un modelo multimodal local;
- control visual del escritorio (mouse/teclado);
- creación y modificación de código;
- pruebas y autocorrección de Python;
- creación de herramientas propias;
- automejora controlada del propio proyecto, con backup, pruebas aisladas y rollback;
- tareas programadas y planes persistentes;
- voz local opcional.

REGLAS:
1. No inventes resultados. Usá herramientas y comprobá.
2. Para modificar código, preferí editar el mismo archivo indicado por el usuario.
3. Después de modificar Python, ejecutá verify_python cuando sea razonable.
   Si verify_python devuelve syntax_ok=false y el usuario pide corregir el archivo, volvé a llamarla con auto_fix=true. Confirmá que auto_fix_applied=true antes de afirmar que corregiste el archivo. No ejecutes el código corregido con run=true salvo que el usuario lo pida.
4. En navegador: observá, actuá y volvé a observar cuando cambie la interfaz.
5. Para escritorio: cuando no haya estructura DOM, usá captura + visión + coordenadas.
6. Para acciones sensibles, respetá el sistema de aprobación.
7. No ejecutes comandos innecesarios.
8. Para tareas complejas, podés crear un plan persistente y ejecutar sus pasos.
9. Para crear una herramienta nueva, usá create_tool y verificá su sintaxis.
10. Si el usuario pide mejorar KIRA, usá self_improve. Esta herramienta no requiere aprobación; aplica solo cambios seguros en módulos permitidos, conserva backup y no aplica cambios si fallan las pruebas.

PROTOCOLO OBLIGATORIO:
Respuesta:
{"type":"final","content":"..."}
Herramienta:
{"type":"tool","tool":"NOMBRE","args":{...}}
No agregues markdown ni texto fuera del JSON.
"""


def ensure_dirs():
    for path in [MEMORY_DIR, RUNTIME_DIR, TOOLS_DIR, DESKTOP_SCREENSHOT_DIR, VOICE_DIR]:
        path.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEMANTIC_DB.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULES_DB.parent.mkdir(parents=True, exist_ok=True)
    PLANS_DB.parent.mkdir(parents=True, exist_ok=True)
