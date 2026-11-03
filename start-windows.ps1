# Cyno Bot - start everything on Windows. Easiest: double-click start-windows.bat
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$Port = if ($env:PORT) { $env:PORT } else { "7860" }

if (-not (Test-Path ".venv\Scripts\python.exe")) { Write-Host "Run setup-windows.bat first."; exit 1 }

# Ollama powers offline mode; make sure it is running.
try { Invoke-RestMethod "http://localhost:11434/api/version" -TimeoutSec 2 | Out-Null }
catch {
    $exe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (-not (Test-Path $exe)) { $cmd = Get-Command ollama -ErrorAction SilentlyContinue; if ($cmd) { $exe = $cmd.Source } }
    if (Test-Path $exe) { Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden }
    else { Write-Host "[!] Ollama not found: offline mode will not answer." -ForegroundColor Yellow }
}

# Open both displays once the server answers.
Start-Job -ArgumentList $Port -ScriptBlock {
    param($Port)
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-RestMethod "http://localhost:$Port/api/state" -TimeoutSec 1 | Out-Null; break } catch { Start-Sleep 1 }
    }
    foreach ($page in "chest", "face") {
        $url = "http://localhost:$Port/$page/"
        try { Start-Process chrome $url -ErrorAction Stop } catch { Start-Process $url }
    }
} | Out-Null

Write-Host "Starting Cyno on http://localhost:$Port  (close this window to stop)" -ForegroundColor Green
& .\.venv\Scripts\python.exe -m cyno.server
