# remote-deploy.ps1 - Lance /opt/agflow.docker/dev-deploy.sh sur une machine de test
#
# Usage : .\scripts\remote-deploy.ps1 <machine_id>
#   ex  : .\scripts\remote-deploy.ps1 302
#
# Lit la configuration dans scripts\.env.<machine_id>.remote-deploy
# Necessite le client SSH Windows (integre depuis Windows 10 1809).
# Auth par cle SSH ou par mot de passe via plink (PuTTY).

param(
    [Parameter(Mandatory)]
    [string]$MachineId,

    [int]$LogLines = 0
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile   = Join-Path $ScriptDir ".env.${MachineId}.remote-deploy"

if (-not (Test-Path $EnvFile)) {
    Write-Error "Fichier $EnvFile introuvable."
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

$branch = if ($cfg['BRANCH']) { $cfg['BRANCH'] } else { 'dev' }

# Commande passee en argument ssh (pas de pipe = pas de BOM)
$remoteCmd = "/opt/agflow.docker/dev-deploy.sh $branch && " +
             "echo '--- logs ($lines lignes) ---' && " +
             "sleep 3 && " +
             "docker compose -f /opt/agflow.docker/docker-compose.dev.yml logs --tail=$lines"

Write-Host "==> [CT${MachineId}] ${remoteUser}@${remoteHost}"

if ($remoteKey) {
    $keyPath = $remoteKey -replace '^~', $env:USERPROFILE
    if (-not (Test-Path $keyPath)) {
        Write-Error "Cle SSH introuvable : $keyPath"
        exit 1
    }
    ssh -o StrictHostKeyChecking=no -p $remotePort -i $keyPath "${remoteUser}@${remoteHost}" $remoteCmd

} elseif ($remotePwd) {
    if (-not (Get-Command plink -ErrorAction SilentlyContinue)) {
        Write-Error "plink requis pour auth par mot de passe - winget install PuTTY.PuTTY"
        exit 1
    }
    plink -batch -pw $remotePwd -P $remotePort "${remoteUser}@${remoteHost}" $remoteCmd

} else {
    Write-Error "REMOTE_KEY ou REMOTE_PASSWORD requis dans $EnvFile"
    exit 1
}
