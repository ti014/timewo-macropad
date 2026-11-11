@echo off
if not exist "%~dp0desktop\dist\v0.11.1-single\timewo-macropad-v0.11.1-windows-x64.exe" (
    echo Chua co ban exe. Hay build ung dung trong thu muc desktop truoc.
    pause
    exit /b 1
)
start "" "%~dp0desktop\dist\v0.11.1-single\timewo-macropad-v0.11.1-windows-x64.exe"
