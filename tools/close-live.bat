@echo off
REM Wrapper so Task Scheduler can run close-live.ps1 in the interactive session.
powershell -NoProfile -ExecutionPolicy Bypass -File C:\LiveRig\Controller\tools\close-live.ps1 > C:\LiveRig\Logs\close-live.log 2>&1
