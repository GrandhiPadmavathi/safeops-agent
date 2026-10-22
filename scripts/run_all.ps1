# Start the API (port 8080) and the UI (port 5173) in two windows.
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$root'; & '$python' -m uvicorn api.main:app --port 8080"
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$root\ui'; if (-not (Test-Path node_modules)) { npm install }; npm run dev"

Write-Host "API: http://127.0.0.1:8080/docs   UI: http://localhost:5173"
