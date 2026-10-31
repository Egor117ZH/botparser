@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv (
  echo Создаю окружение...
  python -m venv venv
)
call venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env (
  copy .env.example .env >nul
  echo Создал .env - впиши туда ключи и запусти ещё раз
  notepad .env
  pause
  exit /b
)
python main.py
pause
