@echo off
REM Smoke test for FilesystemBackend. Run with double-click or right-click -> Run.
REM Uses venv if present, otherwise falls back to system python.

setlocal
cd /d "%~dp0"

set "SCRIPT=%~dp0smoke_fs.py"
set "VENV_PY=%~dp0..\..\.venv\Scripts\python.exe"
set "VENV_PY2=%~dp0..\..\venv\Scripts\python.exe"

if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
) else if exist "%VENV_PY2%" (
    set "PY=%VENV_PY2%"
) else (
    set "PY=python"
)

echo Running: %PY% %SCRIPT%
echo.
"%PY%" "%SCRIPT%"
set "RC=%ERRORLEVEL%"
echo.
echo Exit code: %RC%
pause
exit /b %RC%
