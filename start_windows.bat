@echo off
rem Start backend and frontend in the background. Ports/hosts: .env.local  Logs: logs\*.log
rem Usage: start_windows.bat [-NoBrowser] [-AppEnv dev]
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1" %*
set RC=%ERRORLEVEL%
rem Keep the window open on failure when double-clicked
if not "%RC%"=="0" echo %CMDCMDLINE% | find /i "%~nx0" >nul && pause
exit /b %RC%
