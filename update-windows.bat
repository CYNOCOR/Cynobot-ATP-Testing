@echo off
rem Cyno Bot - after pulling new code, install any new Python packages. Quick, safe to run any time.
cd /d "%~dp0"
where uv >nul 2>nul || set "PATH=%USERPROFILE%\.local\bin;%PATH%"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup-windows.bat first.
  pause
  exit /b 1
)
uv pip install --python .venv -r requirements.txt
echo.
echo Done. Now open Cyno Control.
pause
