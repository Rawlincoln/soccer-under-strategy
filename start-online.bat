@echo off
title Under Goals — Online (Cloudflare Tunnel)
cd /d "%~dp0"

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5050" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

set CF=%~dp0cloudflared.exe
if not exist "%CF%" (
    echo Downloading cloudflared tunnel...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CF%'"
)

echo Starting app on port 5050...
start "UnderGoals App" /MIN py "%~dp0app.py"

echo Waiting for server...
timeout /t 5 /nobreak >nul

echo.
echo ============================================
echo   PUBLIC URL will appear below (trycloudflare.com)
echo   Keep this window OPEN while sharing the link
echo ============================================
echo.

"%CF%" tunnel --url http://localhost:5050

pause