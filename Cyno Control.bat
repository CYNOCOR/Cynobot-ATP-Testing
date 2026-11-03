@echo off
rem Cyno Control for Windows: double-click to open the control app (no console window).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run setup-windows.bat first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m cyno.control
