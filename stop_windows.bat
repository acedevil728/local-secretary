@echo off
rem Force-kill the backend/frontend started by start_windows.bat (process trees).
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_windows.ps1" %*
set RC=%ERRORLEVEL%
echo %CMDCMDLINE% | find /i "%~nx0" >nul && timeout /t 3 >nul 2>&1
exit /b %RC%
