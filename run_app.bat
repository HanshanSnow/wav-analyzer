@echo off
setlocal
set "PROJECT_DIR=%~dp0"
set "VENV_PY=%PROJECT_DIR%.venv\Scripts\python.exe"

rem Prefer the project-local virtual environment (.venv) when present.
rem To use another interpreter, activate it first, then run this script.
if exist "%VENV_PY%" (
    "%VENV_PY%" "%PROJECT_DIR%run_app.py" %*
    goto :end
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%PROJECT_DIR%run_app.py" %*
) else (
    python "%PROJECT_DIR%run_app.py" %*
)

:end
endlocal
