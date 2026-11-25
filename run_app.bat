@echo off
setlocal
set "PROJECT_DIR=%~dp0"
set "VENV_PYW=%PROJECT_DIR%.venv\Scripts\pythonw.exe"
set "VENV_PY=%PROJECT_DIR%.venv\Scripts\python.exe"
set "APP=%PROJECT_DIR%run_app.py"

rem Prefer the windowed interpreter: the console closes at once, so no black box
rem is left sitting behind the app window.
if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" "%APP%" %*
    goto :end
)

if exist "%VENV_PY%" (
    "%VENV_PY%" "%APP%" %*
    goto :end
)

rem No project venv. Try the launcher's windowed build, then fall back to a
rem console interpreter (a console window may appear, which is why we say so).
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 "%APP%" %*
    goto :end
)

echo [note] pythonw.exe is not available; starting with a console interpreter.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%APP%" %*
) else (
    python "%APP%" %*
)

:end
endlocal
