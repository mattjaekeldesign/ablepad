@echo off
REM Runs measure_load.py in the INTERACTIVE session. Session 0 cannot read Live's
REM window titles, and Live launched from there gets no desktop and no audio.
REM
REM The target set is read from a file rather than passed as an argument: nesting
REM quotes through schtasks /tr for a path containing spaces is not worth the fight.
setlocal
set /p TARGET=<C:\LiveRig\Logs\measure-target.txt
cd /d C:\LiveRig\Controller
.venv\Scripts\python.exe tools\measure_load.py "%TARGET%" > C:\LiveRig\Logs\measure-load.log 2>&1
