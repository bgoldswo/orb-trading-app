@echo off
REM ===========================================================================
REM  Launch the ORB Backtester dashboard.
REM  Double-click this file (or the Desktop shortcut) to start the app.
REM  A browser tab opens automatically. Close this window to stop the app.
REM ===========================================================================
title ORB Backtester
cd /d "%~dp0"

if not exist ".venv\Scripts\streamlit.exe" (
  echo.
  echo   Could not find the virtual environment ^(.venv^).
  echo   Set it up once with:
  echo       python -m venv .venv
  echo       .venv\Scripts\python -m pip install -e ".[ui]"
  echo.
  pause
  exit /b 1
)

echo.
echo   Starting ORB Backtester...
echo   Your browser will open at http://localhost:8501
echo   Keep this window open while you use the app; close it to stop.
echo.
".venv\Scripts\streamlit.exe" run streamlit_app.py
pause
