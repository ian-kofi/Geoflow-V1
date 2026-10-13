@echo off
rem Starts the GeoFlow backend and frontend in their own windows, then opens the app.
rem Uses .exe/.cmd entry points directly, so PowerShell's script execution policy doesn't apply.
setlocal
set "ROOT=%~dp0"
set "PATH=%LOCALAPPDATA%\Programs\nodejs;%PATH%"

start "GeoFlow backend" /D "%ROOT%geoflow-backend" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --reload"
start "GeoFlow frontend" /D "%ROOT%geoflow-project" cmd /k "npm.cmd run dev"

rem Give Vite a few seconds to start before opening the browser.
timeout /t 5 /nobreak >nul
start "" http://localhost:5173
