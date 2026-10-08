@echo off
if not exist "%~dp0desktop\dist\v0.9\MacropadConfigurator\MacropadConfigurator.exe" (
    echo Chua co ban exe. Hay build ung dung trong thu muc desktop truoc.
    pause
    exit /b 1
)
start "" "%~dp0desktop\dist\v0.9\MacropadConfigurator\MacropadConfigurator.exe"
