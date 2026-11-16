@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "src\面试演示.py"
if errorlevel 1 pause
