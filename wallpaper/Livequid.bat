@echo off
rem Double-click to run. First launch builds a private environment inside this
rem folder (.venv) - nothing is installed system-wide. Remove with Uninstall.bat.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" goto run

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if defined PY goto setup

echo Python 3 was not found.
choice /m "Install Python 3.12 now with winget (per-user, standard installer)"
if errorlevel 2 goto fail
winget install -e --id Python.Python.3.12 --scope user
echo.
echo Python installed. Please double-click Livequid.bat again.
pause
exit /b

:setup
echo First launch: preparing environment (one time, about a minute)...
%PY% -m venv .venv || goto fail
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto fail

:run
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b

:fail
echo.
echo Setup failed. Delete the .venv folder and try again.
pause
exit /b 1
