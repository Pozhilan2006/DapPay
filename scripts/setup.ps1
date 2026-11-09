$root = Split-Path -Parent $PSScriptRoot

python -m venv "$root/backend/.venv"
& "$root/backend/.venv/Scripts/Activate.ps1"
pip install --upgrade pip
pip install -r "$root/backend/requirements.txt" -r "$root/backend/requirements-dev.txt"

if (-not (Test-Path "$root/backend/.env")) {
  Copy-Item "$root/backend/.env.example" "$root/backend/.env"
}

if (-not (Test-Path "$root/frontend/.env.local")) {
  Copy-Item "$root/frontend/.env.example" "$root/frontend/.env.local"
}

Write-Host "`nSetup complete. Activate the backend venv and run the app with:`n"
Write-Host "cd $root/backend; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload"
Write-Host "`nOr start the frontend with:`n"
Write-Host "cd $root/frontend; npm install; npm run dev"
