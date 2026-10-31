@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist main.py (
  echo.
  echo [!] Не вижу файлов бота рядом с run.bat.
  echo [!] Похоже, ты запустил его прямо из zip-архива.
  echo [!] Распакуй архив: правой кнопкой - "Извлечь все", и запусти run.bat из распакованной папки.
  echo.
  pause
  exit /b
)
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
