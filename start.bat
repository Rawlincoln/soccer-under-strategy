@echo off
title Pro Punter
echo Starting Pro Punter...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5050" ^| findstr "LISTENING"') do (
    echo Stopping old process on port 5050 (PID %%a)...
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo Open http://localhost:5050 in your browser
echo Press Ctrl+C to stop the server
echo.
py "%~dp0app.py"
pause