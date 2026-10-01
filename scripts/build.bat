@echo off
REM Build the standalone client with PyInstaller.
REM Usage: scripts\build.bat
cd /d "%~dp0\.."
python -m pip install -r requirements.txt
python -m PyInstaller --clean --noconfirm find_the_needle_saves.spec
echo.
echo Build finished: dist\find-the-needle-saves.exe
