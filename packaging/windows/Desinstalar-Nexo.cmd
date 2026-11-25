@echo off
rem Desinstala Nexo (version .zip). Respalda la boveda en Documentos antes de borrar.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall-wsl.ps1"
