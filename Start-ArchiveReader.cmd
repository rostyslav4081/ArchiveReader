@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-ArchiveReader.ps1"
if errorlevel 1 (
    echo ArchiveReader could not start. Please keep this error window open.
    pause
    exit /b 1
)
