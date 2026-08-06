@echo off
rem Builds dist\FFmpegStudio518-<version>.exe with PyInstaller.
cd /d "%~dp0"

rem Always go through "python -m": the .venv\Scripts\*.exe launchers hardcode
rem the venv's original absolute path and break if the folder is ever renamed.
.venv\Scripts\python.exe -c "import PyInstaller" 2>nul || (
    .venv\Scripts\python.exe -m pip install pyinstaller || goto :error
)

.venv\Scripts\python.exe -m PyInstaller --noconfirm FFmpegStudio518.spec || goto :error
echo.
echo Done: see dist\FFmpegStudio518-*.exe  (single file, share this)
goto :eof

:error
echo Build failed.
pause
