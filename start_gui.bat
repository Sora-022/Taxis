@echo off
cd /d "%~dp0"
where python >nul 2>nul && (python taxis_gui.py & goto :done)
where py >nul 2>nul && (py taxis_gui.py & goto :done)
echo Could not start. Install Python from python.org (tick "Add python.exe to PATH") and try again.
pause
:done
