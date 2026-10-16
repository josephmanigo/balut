@echo off
if exist "%~dp0runtime\python\python.exe" (
  "%~dp0runtime\python\python.exe" "%~dp0scripts\upload_box_frames.py"
) else (
  "%~dp0.venv-serving\Scripts\python.exe" "%~dp0scripts\upload_box_frames.py"
)
pause
