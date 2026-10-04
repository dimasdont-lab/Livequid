@echo off
rem Removes everything Livequid added: running process, autostart entry, .venv.
rem Afterwards you can simply delete this folder.
cd /d "%~dp0"
call Stop.bat
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Livequid /f >nul 2>nul
timeout /t 2 /nobreak >nul
if exist ".venv" rmdir /s /q ".venv"
if exist "__pycache__" rmdir /s /q "__pycache__"
if exist "livequid.log" del /q "livequid.log"
echo.
echo Done. Livequid is stopped, autostart removed, environment deleted.
echo You can now delete this folder.
pause
