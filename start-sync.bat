@echo off
title Pro Punter — GitHub Auto-Sync
cd /d "%~dp0"
echo Starting GitHub auto-sync for Pro Punter...
echo Changes are pushed ~8 seconds after you save a file.
echo Keep this window open while working.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0watch-github.ps1"
pause