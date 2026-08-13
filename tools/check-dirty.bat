@echo off
REM Interactive session only -- session 0 cannot post WM_CLOSE to Live's windows.
setlocal
set /p TARGET=<C:\LiveRig\Logs\measure-target.txt
cd /d C:\LiveRig\Controller
.venv\Scripts\python.exe tools\check_dirty.py "%TARGET%" > C:\LiveRig\Logs\check-dirty.log 2>&1
