@echo off
chcp 65001 >nul
title 方言采集平台 - 启动
echo 启动方言采集平台管理后台...
echo.
echo 后端   http://127.0.0.1:8000     前端   http://localhost:5173
echo 管理后台账号 admin / admin123
echo 正在打开两个服务窗口，请保留它们运行...
echo.

start "backend :8000" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
timeout /t 2 /nobreak >nul
start "frontend :5173" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo 服务已启动。按任意键关闭本窗口（两个服务窗口请保留）。
pause >nul
