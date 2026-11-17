@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   空间显式批量评估工作台 V1.0  (SEBA)
echo ============================================================
echo.

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo [环境] 使用项目内置 Python 3.12（.venv）
) else (
    echo [环境] 未找到 .venv，尝试使用系统 python
    set "PY=python"
)

echo [启动] 正在加载数据包并启动服务...
echo.

"%PY%" run_web.py --no-open --bundle data/demo_xuhui.bundle --port 8765
if errorlevel 1 (
    echo.
    echo [失败] 启动出错，请把上面的错误信息发给开发者。
    pause
    exit /b 1
)
