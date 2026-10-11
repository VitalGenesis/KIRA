# KIRA V8 — hotfix de fiabilidad

Corrige dos problemas observados:

1. El protocolo JSON de Ollama: tolera escapes inválidos típicos de rutas de Windows y saltos de línea, y si una respuesta no se puede interpretar la muestra como texto en vez de lanzar error. Nunca ejecuta una llamada a herramienta si el objeto está precedido por prosa ambigua.
2. La consulta sobre el código fuente: lista archivos Python que existen realmente en la carpeta del proyecto. No inventa `kira.py`; si se solicita un archivo inexistente lo informa. Los pedidos de resumen leen código real del disco y marcan explícitamente los archivos recortados/omitidos por límites de contexto.
3. Auto-mejora: el parser de propuestas tolera wrappers, JSON adicional, escapes de rutas y saltos de línea; si falla, pide una segunda respuesta de reparación de formato sin proponer contenido nuevo. Los errores ahora indican en qué etapa falló el proceso.

## Instalar

1. Detené KIRA con Ctrl+C.
2. Extraé este ZIP en una carpeta separada, por ejemplo `C:\KIRA_V8_Hotfix`. No lo extraigas encima de KIRA.
3. En PowerShell: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
4. Ejecutá: `.\install_hotfix.ps1 -ProjectRoot "C:\KIRA_v8"` desde el directorio del parche.
5. Reiniciá KIRA: `cd C:\KIRA_v8; .\run_kira.ps1`.

El instalador hace copias de seguridad fechadas y restaura ambos archivos si falla la compilación. `py_compile` solo verifica sintaxis; no ejecuta el programa.

Nota: el resumen global está sujeto a un límite de contexto; KIRA indica si algunos archivos se truncaron o quedaron fuera.
