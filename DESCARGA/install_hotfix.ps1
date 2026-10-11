param(
  [Parameter(Mandatory=$false)][string]$ProjectRoot = "C:\KIRA_v8"
)
$ErrorActionPreference = "Stop"
$PatchRoot = $PSScriptRoot
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
foreach ($name in @("agent.py", "self_improvement.py")) {
  $source = Join-Path $PatchRoot $name
  $target = Join-Path $ProjectRoot $name
  if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Falta el parche: $source" }
  if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "No encuentro el archivo existente: $target" }
}
$agentCurrent = Get-Content -LiteralPath (Join-Path $ProjectRoot "agent.py") -Raw
if ($agentCurrent -notmatch "def run\(user_text") { throw "agent.py no coincide con una estructura reconocida; no se modificó nada." }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backups = @{}
try {
  foreach ($name in @("agent.py", "self_improvement.py")) {
    $target = Join-Path $ProjectRoot $name
    $backup = "$target.backup_reliability_$stamp.bak"
    Copy-Item -LiteralPath $target -Destination $backup
    $backups[$name] = $backup
  }
  foreach ($name in @("agent.py", "self_improvement.py")) {
    Copy-Item -LiteralPath (Join-Path $PatchRoot $name) -Destination (Join-Path $ProjectRoot $name) -Force
  }
  $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $python)) { throw "No encuentro el Python del entorno virtual: $python" }
  & $python -m py_compile (Join-Path $ProjectRoot "agent.py") (Join-Path $ProjectRoot "self_improvement.py")
  if ($LASTEXITCODE -ne 0) { throw "La comprobación de sintaxis falló." }
  Write-Host "Hotfix instalado y sintaxis verificada. No se ejecutó el código de KIRA ni los programas que analiza." -ForegroundColor Green
  foreach ($name in $backups.Keys) { Write-Host "Backup $name : $($backups[$name])" }
  Write-Host "Reiniciá KIRA con .\run_kira.ps1"
} catch {
  foreach ($name in $backups.Keys) {
    Copy-Item -LiteralPath $backups[$name] -Destination (Join-Path $ProjectRoot $name) -Force
  }
  throw "Se revirtió el parche. Motivo: $_"
}
