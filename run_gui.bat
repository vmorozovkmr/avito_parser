@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo Запуск GUI Avito парсера...
venv\Scripts\python.exe avito_gui.py
pause