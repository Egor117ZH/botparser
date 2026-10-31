@echo off
chcp 65001 >nul
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
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
set FIRST=0
if not exist venv\Scripts\python.exe (
  echo === Создаю окружение python...
  python -m venv venv
  set FIRST=1
)
if not exist venv\Scripts\python.exe (
  echo [!] Не получилось создать окружение. Проверь, что python установлен и есть в PATH.
  pause
  exit /b
)
call venv\Scripts\activate.bat
echo === Проверяю библиотеки...
if "%FIRST%"=="1" (
  echo     первый раз ставлю всё, это займёт пару минут
  python -m pip install --disable-pip-version-check -r requirements.txt
) else (
  python -m pip install --disable-pip-version-check -q -r requirements.txt
)
if errorlevel 1 (
  echo [!] Не поставились библиотеки - скрин ошибки выше пришли мне.
  pause
  exit /b
)
if not exist .env (
  copy .env.example .env >nul
  echo === Создал .env - впиши туда ключи, сохрани, закрой блокнот и запусти run.bat ещё раз
  notepad .env
  pause
  exit /b
)
echo === Запускаю бота...
echo.
python main.py
echo.
echo === Бот остановлен.
pause
