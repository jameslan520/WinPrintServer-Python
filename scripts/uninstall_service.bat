@echo off
REM ============================================================
REM WinPrintServer 服务卸载脚本
REM 需要以管理员身份运行
REM ============================================================
chcp 65001 >nul
setlocal

echo.
echo ========================================
echo   WinPrintServer 服务卸载
echo ========================================
echo.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本！
    pause
    exit /b 1
)

echo [1/2] 停止服务...
net stop WinPrintServer >nul 2>&1

echo [2/2] 卸载服务...
set "PYTHON_CMD=python"
where python >nul 2>&1
if %errorLevel% neq 0 (
    where py >nul 2>&1
    if !errorLevel! equ 0 (
        set "PYTHON_CMD=py -3"
    )
)

cd /d "%~dp0.."
%PYTHON_CMD% print_server.py uninstall

echo.
echo [完成] 服务已卸载
pause
