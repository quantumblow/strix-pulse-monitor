@echo off
REM PULSE Monitor launcher — runs the widget without a console window.
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw pulse_monitor.py
) else (
    start "" python pulse_monitor.py
)
