# run-test.ps1 - Orchestre le test d'integration LXC depuis le poste local.
#
# Usage : .\scripts\run-test.ps1
#         .\scripts\run-test.ps1 -Config .env.test.staging
#         .\scripts\run-test.ps1 -Cleanup
#         .\scripts\run-test.ps1 -SshHost pve2
#
# Pousse test-create-lxc.sh + destroy-test.sh + config vers pve:/opt/scripts/
# puis lance test-create-lxc.sh sur pve (cree un LXC dans la plage 400-499).
#
# Necessite l'alias SSH `pve` dans ~/.ssh/config (ou override via -SshHost).

param(
    [string]$Config  = ".env.test.docker",
    [string]$SshHost = "pve",
    [switch]$Cleanup
)

$ErrorActionPreference = "Stop"

$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$TestScript    = Join-Path $ScriptDir "test-create-lxc.sh"
$DestroyScript = Join-Path $ScriptDir "destroy-test.sh"
$LocalConfig   = Join-Path $ScriptDir $Config
$RemoteDir     = "/opt/scripts"
$CleanupVal    = if ($Cleanup) { "1" } else { "0" }

# Verifications locales
if (-not (Test-Path $TestScript))    { Write-Error "Script introuvable : $TestScript";    exit 1 }
if (-not (Test-Path $DestroyScript)) { Write-Error "Script introuvable : $DestroyScript"; exit 1 }
if (-not (Test-Path $LocalConfig)) {
    Write-Error "Fichier de config introuvable : $LocalConfig"
    Write-Host "  Usage : .\run-test.ps1 -Config .env.test.staging"
    exit 1
}

Write-Host "-> Cible SSH         : $SshHost"
Write-Host "-> Scripts a pousser : $TestScript"
Write-Host "                       $DestroyScript"
Write-Host "-> Config a pousser  : $LocalConfig"
Write-Host "-> Destination       : ${SshHost}:${RemoteDir}/"
Write-Host ""

# 1) Push des scripts
Write-Host "[1/3] Push scripts -> ${SshHost}:${RemoteDir}/..."
ssh $SshHost "mkdir -p $RemoteDir"
scp $TestScript    "${SshHost}:${RemoteDir}/test-create-lxc.sh"
scp $DestroyScript "${SshHost}:${RemoteDir}/destroy-test.sh"
ssh $SshHost "chmod +x ${RemoteDir}/test-create-lxc.sh ${RemoteDir}/destroy-test.sh"
Write-Host "      OK test-create-lxc.sh + destroy-test.sh pousses"

# 2) Push du fichier de config (CRLF -> LF pour eviter \r dans les variables bash)
Write-Host "[2/3] Push $Config (LF normalise) -> ${SshHost}:${RemoteDir}/..."
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$content   = [System.IO.File]::ReadAllText($LocalConfig) -replace "`r`n", "`n"
$tmpFile   = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tmpFile, $content, $utf8NoBom)
scp $tmpFile "${SshHost}:${RemoteDir}/${Config}"
Remove-Item $tmpFile -Force
Write-Host "      OK pousse"
Write-Host ""

# 3) Execution sur pve
Write-Host "[3/3] Execution sur ${SshHost} : ${RemoteDir}/test-create-lxc.sh $Config"
Write-Host "--------------------------------------------------------------------------"
ssh -t $SshHost "cd $RemoteDir && CLEANUP=$CleanupVal bash -lc './test-create-lxc.sh $Config'"
