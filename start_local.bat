@echo off
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
if not exist data\sales.csv .venv\Scripts\python.exe -m demandflow.cli sample
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m demandflow.cli run
if errorlevel 1 goto fail
start "" http://127.0.0.1:8000
.venv\Scripts\python.exe -m uvicorn demandflow.api:app --host 127.0.0.1 --port 8000
:fail
echo See the messages above. Keep this window open while using the app.
pause
