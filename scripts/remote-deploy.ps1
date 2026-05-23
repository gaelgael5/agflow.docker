# remote-deploy.ps1 — Lance /opt/agflow.docker/dev-deploy.sh sur la machine de test
#
# Nécessite le client SSH Windows (intégré depuis Windows 10 1809).
# Auth par clé SSH ou par mot de passe via plink (PuTTY).
#
# Configuration : remplir scripts\.env.remote-deploy

param(
    [int]$LogLines = 0   # 0 = utilise la valeur du .env (défaut 80)
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile   = Join-Path $ScriptDir ".env.remote-deploy"

if (-not (Test-Path $EnvFile)) {
    Write-Error "Fichier $EnvFile introuvable. Copier .env.remote-deploy.example -> .env.remote-deploy"
    exit 1
}

# Charger le fichier .env (ignorer lignes vides et commentaires)
$cfg = @{}
foreach ($line in Get-Content $EnvFile) {
    $line = $line.Trim()
    if ($line -match '^#' -or $line -eq '') { continue }
    $parts = $line -split '=', 2
    if ($parts.Count -eq 2) { $cfg[$parts[0].Trim()] = $parts[1].Trim() }
}

$remoteHost = $cfg['REMOTE_HOST']
$remoteUser = $cfg['REMOTE_USER']
$remotePort = if ($cfg['REMOTE_PORT']) { $cfg['REMOTE_PORT'] } else { '22' }
$remoteKey  = $cfg['REMOTE_KEY']
$remotePwd  = $cfg['REMOTE_PASSWORD']
$lines      = if ($LogLines -gt 0) { $LogLines } `
              elseif ($cfg['LOG_LINES']) { $cfg['LOG_LINES'] } `
              else { '80' }

if (-not $remoteHost) { Write-Error 'REMOTE_HOST requis'; exit 1 }
if (-not $remoteUser) { Write-Error 'REMOTE_USER requis'; exit 1 }

# Commande à exécuter sur la machine distante
$remoteCmd = @"
set -euo pipefail
/opt/agflow.docker/dev-deploy.sh
echo ''
echo '--- logs initiaux ($lines lignes) ---'
sleep 3
docker compose -f /opt/agflow.docker/docker-compose.dev.yml logs --tail=$lines --no-color
"@

Write-Host "==> ${remoteUser}@${remoteHost}"

if ($remoteKey) {
    # Remplacer ~ par le répertoire home Windows
    $keyPath = $remoteKey -replace '^~', $env:USERPROFILE
    if (-not (Test-Path $keyPath)) {
        Write-Error "Cle SSH introuvable : $keyPath"
        exit 1
    }
    $remoteCmd | ssh -o StrictHostKeyChecking=no -p $remotePort -i $keyPath "${remoteUser}@${remoteHost}" "bash -s"

} elseif ($remotePwd) {
    if (-not (Get-Command plink -ErrorAction SilentlyContinue)) {
        Write-Error "plink requis pour l'auth par mot de passe — installer PuTTY : winget install PuTTY.PuTTY"
        exit 1
    }
    $remoteCmd | plink -batch -pw $remotePwd -P $remotePort "${remoteUser}@${remoteHost}" "bash -s"

} else {
    Write-Error "REMOTE_KEY ou REMOTE_PASSWORD doit etre defini dans $EnvFile"
    exit 1
}
