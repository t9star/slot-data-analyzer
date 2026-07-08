@echo off
title Slot Data Analyzer
echo ====================================================
echo   Slot Data Analyzer - Local Server
echo ====================================================
echo.
echo Starting local analysis server...
echo Browser will open automatically in a few seconds.
echo (If not, please visit http://127.0.0.1:5000 in your browser)
echo.
echo Please do not close this window while using the app.
echo.

:: Start browser after 3 seconds asynchronously
start "" cmd /c "timeout /t 3 >nul && start http://127.0.0.1:5000"

:: Launch Flask server
"C:\Users\frog9\.local\bin\uv.exe" run python app.py

pause
