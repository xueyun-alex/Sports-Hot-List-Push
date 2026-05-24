$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$PipExe = Join-Path $VenvPath "Scripts\pip.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "Creating virtual environment..."
    python -m venv $VenvPath
}

Write-Host "Installing dependencies..."
& $PipExe install -r (Join-Path $ProjectRoot "requirements.txt")
& $PipExe install pyinstaller

Write-Host "Building SportsHotList.exe..."
Push-Location $ProjectRoot
try {
    & (Join-Path $VenvPath "Scripts\pyinstaller.exe") --noconfirm SportsHotList.spec
} finally {
    Pop-Location
}

$OutputExe = Join-Path $ProjectRoot "dist\SportsHotList.exe"
if (Test-Path $OutputExe) {
    Write-Host "Build complete: $OutputExe"
} else {
    Write-Error "Build failed: $OutputExe not found"
}
