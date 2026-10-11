# KIRA V8 — Chat Focus

Interfaz minimalista centrada en la conversación: fondo casi negro, texto blanco, tonos grises discretos y sin efectos visuales innecesarios. Conserva los IDs, endpoints y JavaScript actuales; solo reemplaza `static/style.css`.

## Instalar
1. Detené KIRA con `Ctrl+C`.
2. Extraé el ZIP fuera de `C:\KIRA_v8`, por ejemplo en `C:\KIRA_CHAT_FOCUS`.
3. En PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
cd C:\KIRA_v8\KIRA_V8_CHAT_FOCUS
.\install_chat_focus.ps1 -ProjectRoot "C:\KIRA_v8"
```

4. Volvé a iniciar `KIRA` con `cd C:\KIRA_v8; .\run_kira.ps1` y presioná `Ctrl+F5` en el navegador.

El instalador guarda el CSS previo en `C:\KIRA_v8\backups\chat_focus_FECHA\style.css`. No modifica el agente, herramientas, memoria ni backend. Para revertir, copiá ese backup de vuelta a `C:\KIRA_v8\static\style.css`.
