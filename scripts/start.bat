@echo off
REM ============================================================
REM WinPrintServer 前台启动脚本（调试用）
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0.."

set "PYTHON_CMD=python"
where python >nul 2>&1
if %errorLevel% neq 0 (
    where py >nul 2>&1
    if !errorLevel! equ 0 (
        set "PYTHON_CMD=py -3"
    ) else (
        echo [错误] 未找到 Python
        pause
        exit /b 1
    )
)

echo 启动 WinPrintServer（前台模式，Ctrl+C 停止）...
echo.
%PYTHON_CMD% print_server.py %*
pause
