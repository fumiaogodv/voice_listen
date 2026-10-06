@echo off
REM N2S 本地启动脚本（Windows）
cd /d "%~dp0"

set PY="C:\Users\godv\.workbuddy\binaries\python\envs\n2s\Scripts\python.exe"

echo [1/2] 确保示例笔记已就位...
if not exist "data\notes\设备管理.md" copy "sample\*.md" "data\notes\" >nul

echo [2/2] 启动服务...
%PY% -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

pause
