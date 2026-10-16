@echo off
set "PYTHONPATH=%~dp0apps\edge_api"
"%~dp0runtime\python\python.exe" "%~dp0scripts\prepare_render_account.py"
pause
