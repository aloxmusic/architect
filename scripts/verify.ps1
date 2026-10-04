$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & .\.venv\Scripts\python.exe -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
    & .\.venv\Scripts\python.exe -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw 'ruff check failed' }
    & .\.venv\Scripts\python.exe -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw 'ruff format failed' }
    & .\.venv\Scripts\python.exe -m mypy
    if ($LASTEXITCODE -ne 0) { throw 'mypy failed' }
} finally {
    Pop-Location
}
