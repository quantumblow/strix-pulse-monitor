@echo off
REM Build Strix Pulse Monitor as a single .exe with PyInstaller.
REM Requires: Python 3.10+ on PATH.
setlocal
cd /d "%~dp0"
rem Version: first argument, else PULSE_VERSION from the environment, else 1.0.0.
set "VER=%~1"
if "%VER%"=="" set "VER=%PULSE_VERSION%"
if "%VER%"=="" set "VER=1.0.0"

python -m pip install --upgrade pip || goto :err
python -m pip install -r ..\requirements.txt pyinstaller || goto :err
python -m PyInstaller --noconfirm PulseMonitor.spec || goto :err

echo.
echo Built: %~dp0dist\Strix Pulse Monitor.exe

where makensis >nul 2>&1
if errorlevel 1 (
  echo [!] NSIS ^(makensis^) not found on PATH. Install from https://nsis.sourceforge.io
  echo     to build the wizard. The app exe is ready at: %~dp0dist\Strix Pulse Monitor.exe
  goto :eof
)
echo [i] Installer version: %VER%
makensis /DVER=%VER% "%~dp0PulseMonitor.nsi" || goto :err
echo.
echo Success. Setup wizard created: %~dp0Strix-Pulse-Monitor-Setup.exe
goto :eof

:err
echo Build failed.
exit /b 1
