param(
    [Parameter(Mandatory=$true)]
    [string]$ProjectRoot
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$target = Join-Path $ProjectRoot 'static\style.css'
$source = Join-Path $PSScriptRoot 'static\style.css'
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "No encuentro $target. No se modificó nada." }
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "No encuentro el CSS del parche. No se modificó nada." }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupDir = Join-Path $ProjectRoot "backups\chat_focus_$stamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Copy-Item -LiteralPath $target -Destination (Join-Path $backupDir 'style.css')
try {
    Copy-Item -LiteralPath $source -Destination $target -Force
    Write-Host "Interfaz enfocada en el chat instalada." -ForegroundColor Green
    Write-Host "Backup: $backupDir\style.css" -ForegroundColor Cyan
    Write-Host "Reiniciá KIRA y recargá con Ctrl+F5."
} catch {
    Copy-Item -LiteralPath (Join-Path $backupDir 'style.css') -Destination $target -Force
    throw
}
