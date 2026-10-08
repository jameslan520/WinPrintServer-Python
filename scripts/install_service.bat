@echo off
REM ============================================================
REM WinPrintServer 服务安装脚本
REM 需要以管理员身份运行
REM ============================================================
chcp 65001 >nul
setlocal

echo.
echo ========================================
echo   WinPrintServer 服务安装
echo ========================================
echo.

REM 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本！
    echo        右键点击此文件 -^> 以管理员身份运行
    pause
    exit /b 1
)

set "BASE_DIR=%~dp0.."
set "PYTHON_CMD=python"

REM 查找 Python
where python >nul 2>&1
if %errorLevel% neq 0 (
    where py >nul 2>&1
    if !errorLevel! equ 0 (
        set "PYTHON_CMD=py -3"
    ) else (
        echo [错误] 未找到 Python，请先安装 Python 3.6+
        echo        下载: https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

echo [1/3] 检查 pywin32 模块...
%PYTHON_CMD% -c "import win32serviceutil" >nul 2>&1
if %errorLevel% neq 0 (
    echo      正在安装 pywin32...
    %PYTHON_CMD% -m pip install pywin32
    if !errorLevel! neq 0 (
        echo [错误] pywin32 安装失败
        pause
        exit /b 1
    )
    %PYTHON_CMD% -m pywin32_postinstall -install >nul 2>&1
)

echo [2/3] 安装 Windows 服务...
cd /d "%BASE_DIR%"
%PYTHON_CMD% print_server.py install
if %errorLevel% neq 0 (
    echo [错误] 服务安装失败
    pause
    exit /b 1
)

echo [3/3] 启动服务...
net start WinPrintServer
if %errorLevel% neq 0 (
    echo [警告] 服务启动失败，请查看日志: logs\print_server.log
) else (
    echo.
    echo [成功] WinPrintServer 服务已安装并启动！
)

echo.
echo 服务名称: WinPrintServer
echo 状态页:   http://localhost:8080
echo 日志:     %BASE_DIR%\logs\print_server.log
echo.
pause
