# Cyno Bot - one-time setup for Windows. Safe to re-run.
# Easiest: double-click setup-windows.bat (it runs this file).
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$OllamaModel = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "llama3.2:3b" }
function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Test-Ollama { try { Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 2 | Out-Null; $true } catch { $false } }

Step "1/6  uv (Python manager)"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
uv --version

Step "2/6  Python 3.12 environment (.venv)"
if (-not (Test-Path ".venv")) { uv venv --python 3.12 .venv }

Step "3/6  Python packages (first run downloads ~2 GB, be patient)"
uv pip install --python .venv -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Package install failed" }

Step "4/6  Ollama (offline brain)"
$OllamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
if (-not (Test-Path $OllamaExe) -and -not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    } else {
        Warn "Install Ollama from https://ollama.com/download, open it once, then re-run this script."
        exit 1
    }
}
if (-not (Test-Path $OllamaExe)) { $OllamaExe = (Get-Command ollama).Source }
if (-not (Test-Ollama)) {
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 30 -and -not (Test-Ollama); $i++) { Start-Sleep -Seconds 1 }
}
& $OllamaExe pull $OllamaModel
if ($LASTEXITCODE -ne 0) { throw "ollama pull failed" }

Step "5/6  Gemini API key (.env)"
.\.venv\Scripts\python.exe -m cyno.setup_env

Step "6/6  Download, warm up and benchmark offline models"
.\.venv\Scripts\python.exe -m cyno.prepare_offline

.\.venv\Scripts\python.exe -m cyno.control.install_icons

Write-Host "`nSetup complete. Open 'Cyno Control' from your Desktop (or double-click 'Cyno Control.bat')" -ForegroundColor Green
