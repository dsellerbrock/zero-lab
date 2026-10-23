@echo off
rem Zero Lab for Windows: starts the app and opens it in your web browser. Closing this window stops the Pi.
title Zero Lab - close this window to stop the Pi
if not exist "%~dp0zero-lab\python\python.exe" (
  echo Zero Lab is still inside the zip file.
  echo Right-click the zip, choose "Extract All...", then double-click "Zero Lab" in the extracted folder.
  pause
  exit /b 1
)
set PYTHONUTF8=1
"%~dp0zero-lab\python\python.exe" "%~dp0zero-lab\app\server.py" --open %*
if errorlevel 1 pause
