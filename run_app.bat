@echo off
setlocal
set "PROJECT_DIR=%~dp0"

rem 优先用 Python 启动器（py -3），没有就退回 PATH 里的 python。
rem 想指定解释器就先激活自己的虚拟环境，再运行本脚本。
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%PROJECT_DIR%run_app.py" %*
) else (
    python "%PROJECT_DIR%run_app.py" %*
)
endlocal
