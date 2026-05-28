$ErrorActionPreference = "Stop"

$composeDir = Split-Path -Parent $PSScriptRoot
$backupDir = Join-Path $composeDir "backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = Join-Path $backupDir "deposito_$timestamp.sql"

Set-Location $composeDir
docker compose exec -T postgres pg_dump -U deposito_user -d deposito --clean --if-exists | Set-Content -Encoding UTF8 $backupFile

Write-Host "Backup creado: $backupFile"

