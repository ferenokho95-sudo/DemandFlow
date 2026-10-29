@echo off
cd /d "%~dp0"
docker compose up --build -d
if errorlevel 1 goto fail
docker compose run --rm pipeline
if errorlevel 1 goto fail
start "" http://127.0.0.1:8000
echo DemandFlow is running. Use docker compose down to stop.
pause
exit /b 0
:fail
echo Startup failed. Read the error above.
pause
exit /b 1
