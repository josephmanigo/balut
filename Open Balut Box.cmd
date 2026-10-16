@echo off
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-BalutBox.ps1"
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "https://192.168.2.2:8765/"
