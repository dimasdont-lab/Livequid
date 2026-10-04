@echo off
rem Stops Livequid only (not other Python programs).
powershell -NoProfile -Command "$d='%~dp0'; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like ('*' + $d + '*') -and $_.Name -like 'pythonw*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
