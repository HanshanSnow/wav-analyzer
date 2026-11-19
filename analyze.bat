@echo off
cd /d "%~dp0"

rem 优先用 Python 启动器（py -3），没有就退回 PATH 里的 python。
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 analyze.py %*
) else (
    python analyze.py %*
)
if "%~1"=="" pause
