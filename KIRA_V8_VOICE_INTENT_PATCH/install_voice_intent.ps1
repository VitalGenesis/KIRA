param([Parameter(Mandatory=$true)][string]$ProjectRoot)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $ProjectRoot).Path
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$targets = @(
  @{ Source = (Join-Path $PSScriptRoot 'templates\index.html'); Destination = (Join-Path $root 'templates\index.html') },
  @{ Source = (Join-Path $PSScriptRoot 'static\app.js'); Destination = (Join-Path $root 'static\app.js') }
)
foreach ($item in $targets) {
  if (-not (Test-Path $item.Destination -PathType Leaf)) { throw "No existe el archivo destino: $($item.Destination)" }
  $backup = "$($item.Destination).backup_voice_intent_$stamp"
  Copy-Item -LiteralPath $item.Destination -Destination $backup
  Copy-Item -LiteralPath $item.Source -Destination $item.Destination -Force
  Write-Host "Actualizado: $($item.Destination)" -ForegroundColor Green
  Write-Host "Respaldo:    $backup"
}
Write-Host 'Instalación terminada. Reiniciá KIRA y recargá el navegador con Ctrl+F5.' -ForegroundColor Cyan
