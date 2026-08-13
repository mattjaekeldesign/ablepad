@echo off
REM Start the rig controller IN THE LOGGED-ON USER'S DESKTOP SESSION.
REM
REM Not a convenience wrapper. Windows Session 0 Isolation means a controller
REM started over SSH runs in the services session, and every process it spawns
REM inherits that -- so Ableton launches with no desktop and cannot open the
REM EVO's ASIO driver. It runs, it responds, and it makes no sound. Scheduled
REM task 'ablepad-rig' is registered /IT (interactive only) so this lands in
REM session 1 instead.
cd /d C:\LiveRig\Controller
.venv\Scripts\python.exe main.py >> C:\LiveRig\Logs\rig.log 2>&1
