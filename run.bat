@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Rebuild the Windows PowerShell module path after intermediary shells.
set "PSModulePath="
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
exit /b %ERRORLEVEL%
