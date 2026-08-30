param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$installDir = Join-Path $env:RUNNER_TEMP "KajovoKarty Installed $Version"
$smokeData = Join-Path $env:RUNNER_TEMP "kajovokarty-installed-smoke"
$userData = Join-Path $env:LOCALAPPDATA "KajovoKarty"
$sentinel = Join-Path $userData "installer-smoke-sentinel.txt"
$logDir = Join-Path (Resolve-Path ".") "build\audit_logs"
New-Item -ItemType Directory -Force -Path $logDir, $userData | Out-Null
"preserve-user-data" | Set-Content -Encoding UTF8 $sentinel

& $Installer /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER "/DIR=$installDir" "/LOG=$logDir\installer-install.log"
if ($LASTEXITCODE -ne 0) { throw "Instalátor skončil s kódem $LASTEXITCODE" }

$exe = Join-Path $installDir "KajovoKarty.exe"
if (-not (Test-Path $exe)) { throw "Po instalaci chybí KajovoKarty.exe" }
$env:QT_QPA_PLATFORM = "offscreen"
$env:KAJOVOKARTY_TEST_DATA_DIR = $smokeData
& $exe --smoke-test
if ($LASTEXITCODE -ne 0) { throw "Nainstalovaný EXE smoke test skončil s kódem $LASTEXITCODE" }

$uninstaller = Join-Path $installDir "unins000.exe"
if (-not (Test-Path $uninstaller)) { throw "Po instalaci chybí odinstalátor" }
& $uninstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART "/LOG=$logDir\installer-uninstall.log"
if ($LASTEXITCODE -ne 0) { throw "Odinstalátor skončil s kódem $LASTEXITCODE" }
if (Test-Path $exe) { throw "Odinstalace ponechala programový EXE" }
if (-not (Test-Path $sentinel)) { throw "Odinstalace poškodila uživatelskou datovou složku" }

Remove-Item -Force $sentinel
Write-Host "PASS: instalace, nainstalovaný EXE a odinstalace se zachováním uživatelských dat"
