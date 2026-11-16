param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonCommand = Get-Command $Python -ErrorAction Stop
$adbCommand = Get-Command "adb.exe" -ErrorAction Stop
$adbDirectory = Split-Path -Parent $adbCommand.Source
$requiredAdbFiles = "adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt"

foreach ($fileName in $requiredAdbFiles) {
    $filePath = Join-Path $adbDirectory $fileName
    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
        throw "Google Platform Tools is incomplete. Missing: $filePath"
    }
}

$buildPython = Join-Path $projectRoot ".venv-build\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf)) {
    & $pythonCommand.Source -m venv (Join-Path $projectRoot ".venv-build")
}

& $buildPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot "requirements-build.txt")
$env:TAXIS_ADB_DIR = $adbDirectory
& $buildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath (Join-Path $projectRoot "outputs") `
    --workpath (Join-Path $projectRoot "build") `
    (Join-Path $projectRoot "taxis.spec")

if ($LASTEXITCODE -ne 0) {
    throw "Taxis.exe could not be built."
}

Write-Host "Built: $(Join-Path $projectRoot 'outputs\Taxis.exe')"
