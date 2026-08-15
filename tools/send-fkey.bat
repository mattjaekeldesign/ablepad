@echo off
REM Interactive session only -- synthesised input goes to the calling session.
REM Key is read from a file to avoid quoting it through schtasks.
setlocal
set /p FKEY=<C:\LiveRig\Logs\fkey.txt
powershell -NoProfile -ExecutionPolicy Bypass -File C:\LiveRig\Controller\tools\send-fkey.ps1 -Key %FKEY% -DelaySeconds 6 > C:\LiveRig\Logs\fkey.log 2>&1
