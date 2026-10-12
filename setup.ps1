#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
    Write-Host "==> Created .env from .env.example"
}

Write-Host "==> Backend"
Set-Location (Join-Path $Root "backend")
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
# Same as setup.sh: OpenCV's headless build (no GUI dependencies).
& .\.venv\Scripts\python.exe -m pip uninstall --quiet --yes opencv-python
& .\.venv\Scripts\python.exe -m pip install --quiet opencv-python-headless==5.0.0.93
& .\.venv\Scripts\python.exe manage.py migrate --noinput
& .\.venv\Scripts\python.exe manage.py seed

Write-Host ""
Write-Host "==> Frontend"
Set-Location (Join-Path $Root "frontend")
npm install

Write-Host ""
Write-Host "Setup complete."
Write-Host ""
Write-Host "Start the backend:"
Write-Host "  cd backend; .\.venv\Scripts\Activate.ps1; python manage.py runserver"
Write-Host ""
Write-Host "Start the frontend (in another terminal):"
Write-Host "  cd frontend; npm run dev"
Write-Host ""
Write-Host "Then open http://localhost:5173"
