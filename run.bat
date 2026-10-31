@echo off
chcp 65001 >nul
setlocal
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

rem --- ищем подходящий python: 3.10-3.14, 64-bit ---
set "PY="
for %%v in (3.12 3.13 3.11 3.14 3.10) do (
  if not defined PY (
    py -%%v-64 -c "import sys" >nul 2>&1 && set "PY=py -%%v-64"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,14) and sys.maxsize>2**32 else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY goto badpython

rem --- если окружение создано на неподходящем питоне - пересоздаём ---
if exist venv\Scripts\python.exe (
  venv\Scripts\python.exe -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,14) and sys.maxsize>2**32 else 1)" >nul 2>&1
  if errorlevel 1 (
    echo === Старое окружение на неподходящем питоне, пересоздаю...
    rmdir /s /q venv
  )
)
if not exist venv\Scripts\python.exe (
  echo === Создаю окружение на %PY%...
  %PY% -m venv venv
)
if not exist venv\Scripts\python.exe (
  echo [!] Не получилось создать окружение.
  pause
  exit /b
)
venv\Scripts\python.exe --version

if not exist venv\.installed (
  echo === Ставлю библиотеки, первый раз займёт пару минут...
  venv\Scripts\python.exe -m pip install --disable-pip-version-check --prefer-binary -r requirements.txt
) else (
  echo === Проверяю библиотеки...
  venv\Scripts\python.exe -m pip install --disable-pip-version-check --prefer-binary -q -r requirements.txt
)
if errorlevel 1 (
  echo [!] Не поставились библиотеки - скрин ошибки выше пришли мне.
  pause
  exit /b
)
echo ok> venv\.installed

if not exist .env (
  copy .env.example .env >nul
  echo === Создал .env - впиши туда ключи, сохрани, закрой блокнот и запусти run.bat ещё раз
  notepad .env
  pause
  exit /b
)

echo === Запускаю бота...
echo.
venv\Scripts\python.exe main.py
echo.
echo === Бот остановлен.
pause
exit /b

:badpython
echo.
echo [!] Не нашёл подходящий Python. Сейчас у тебя:
python -c "import sys, platform; print(sys.version.split()[0], platform.architecture()[0])"
echo.
echo [!] Нужен Python 3.12, 64-bit. На слишком новом или 32-битном питоне библиотеки не ставятся.
echo [!] Скачай: https://www.python.org/downloads/windows/
echo [!] ищи "Python 3.12.x" - "Windows installer (64-bit)", ставь с настройками по умолчанию.
echo [!] Старый питон удалять не надо. Потом просто снова запусти run.bat.
echo.
pause
