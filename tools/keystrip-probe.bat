@echo off
REM Interactive session only -- session 0 cannot see the desktop's keyboard input.
cd /d C:\LiveRig\Controller
.venv\Scripts\python.exe tools\keystrip_probe.py > C:\LiveRig\Logs\keystrip.log 2>&1
