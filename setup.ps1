# setup.ps1 - prepare the build environment on Windows
# Run in an elevated PowerShell prompt:  Set-ExecutionPolicy Bypass -Scope Process -Force; .\setup.ps1

Write-Host "=== NetLab Windows Setup ===" -ForegroundColor Cyan

# 1. Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Please install Python 3.11 or 3.12 from https://python.org" -ForegroundColor Red
    exit 1
}
$pyVersion = python --version 2>&1
Write-Host "Python: $pyVersion"

# 2. Docker Desktop
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker not found. Downloading Docker Desktop installer..." -ForegroundColor Yellow
    $url = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
    $dest = "$env:USERPROFILE\Downloads\DockerDesktopInstaller.exe"
    Invoke-WebRequest -Uri $url -OutFile $dest
    Write-Host "Downloaded to $dest" -ForegroundColor Green
    Write-Host "Please run the installer and restart this script." -ForegroundColor Yellow
    Start-Process -FilePath $dest
    exit 0
}

$dockerVersion = docker version --format '{{.Server.Version}}' 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is installed but not running." -ForegroundColor Yellow
    Write-Host "Start Docker Desktop, then re-run this script." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    exit 1
}
Write-Host "Docker: $dockerVersion"

# 3. Create venv
Write-Host "Creating virtual environment..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1

# 4. Install deps
Write-Host "Installing dependencies..." -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install pyinstaller pytest httpx
python -m pip install -e ".[dev,web,desktop]"

# 5. Sanity check
Write-Host "Running sanity check..." -ForegroundColor Cyan
python -c "import webview, fastapi, docker; print('Imports OK')"

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "To build the executable, run:" -ForegroundColor Cyan
Write-Host "  python scripts/build.py" -ForegroundColor White
Write-Host ""
Write-Host "The .exe will be in: dist\NetLab.exe" -ForegroundColor Cyan