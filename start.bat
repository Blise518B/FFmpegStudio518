@echo off
rem Dev launcher - creates the venv on first run, then starts the app.
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    py -3.13 -m venv .venv 2>nul || python -m venv .venv || goto :error
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
)

.venv\Scripts\python.exe -m ffmpeg_studio %*
goto :eof

:error
echo.
echo Setup failed. Is Python 3.10+ installed and on PATH?
pause
