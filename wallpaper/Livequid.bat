@echo off
rem Double-click to run. First launch builds a private environment inside this
rem folder (.venv) - nothing is installed system-wide. Remove with Uninstall.bat.
setlocal
cd /d "%~dp0"
if exist ".venv\ready" goto run
if exist ".venv" rmdir /s /q ".venv"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if defined PY goto setup

echo Python 3 was not found.
choice /m "Install the latest Python now with winget (per-user)"
if errorlevel 2 goto fail
winget install -e --id Python.Python.3.13 --scope user
echo.
echo Done. Close this window and double-click Livequid.bat again.
pause
exit /b

:setup
echo First launch: preparing environment (one time, about a minute)...
%PY% -m venv .venv > setup.log 2>&1 || goto fail
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: -r requirements.txt >> setup.log 2>&1 || goto fail
echo ok> ".venv\ready"
del /q setup.log

:run
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b

:fail
echo.
echo Setup failed. Details:
if exist setup.log type setup.log
if exist ".venv" rmdir /s /q ".venv"
echo.
echo Send me this text (also saved in setup.log).
pause
exit /b 1
