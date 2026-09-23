@echo off
REM One-command Windows build for SurveySuite.
REM Run this on a Windows PC: it installs dependencies, then builds
REM dist\SurveySuite\SurveySuite.exe via PyInstaller.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python build.py
echo.
echo Build finished. See dist\SurveySuite\SurveySuite.exe
pause
