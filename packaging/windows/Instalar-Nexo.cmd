@echo off
rem Instala o actualiza Nexo (version .zip, sin instalador .exe)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-wsl.ps1" -Shortcuts
