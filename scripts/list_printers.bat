@echo off
REM ============================================================
REM 列出本机打印机
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0.."

set "PYTHON_CMD=python"
where python >nul 2>&1
if %errorLevel% neq 0 (
    where py >nul 2>&1
    if !errorLevel! equ 0 (
        set "PYTHON_CMD=py -3"
    )
)

%PYTHON_CMD% print_server.py --list-printers
pause
