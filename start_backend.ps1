$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$graphPath = Join-Path $projectRoot "data\macau_network.graphml"
$backendEntry = Join-Path $projectRoot "backend\main.py"
$requirementsPath = Join-Path $projectRoot "requirements-launcher.txt"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $backendEntry)) {
    throw "Backend source is missing. Download and extract the complete smart-navigation-backend-launcher-windows.zip from the release; do not run the BAT file by itself."
}

if (-not (Test-Path $graphPath)) {
    throw "Road network data is missing. Extract the complete backend launcher ZIP again."
}

if (-not (Test-Path $requirementsPath)) {
    throw "Backend dependency list is missing. Extract the complete backend launcher ZIP again."
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating a private Python environment..."
    python -m venv (Join-Path $projectRoot ".venv")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create a Python environment. Install Python 3 and try again."
    }
}

& $venvPython -c "import fastapi, httpx, networkx, pydantic, shapely, uvicorn"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing backend dependencies (first run only)..."
    & $venvPython -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install backend dependencies. Check your internet connection and Python installation."
    }
}

Set-Location -LiteralPath $projectRoot
Write-Host "Starting Smart Navigation backend at http://localhost:8000"
Write-Host "Press Ctrl+C to stop the backend."
& $venvPython -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
if ($LASTEXITCODE -ne 0) {
    throw "Backend stopped with an error. If port 8000 is already in use, close the existing backend and retry."
}
