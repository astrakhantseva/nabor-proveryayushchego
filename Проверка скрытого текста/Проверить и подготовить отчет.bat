@echo off
chcp 65001 >nul
rem Проверка рабочей папки на скрытый текст. Запуск двойным щелчком.
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
if not exist ".venv\Scripts\python.exe" (
  echo Первый запуск. Устанавливается библиотека для чтения PDF, это займет около минуты.
  %PY% -m venv .venv || goto nopython
)
".venv\Scripts\python.exe" -c "import pymupdf, numpy" 2>nul || (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pymupdf numpy || goto nolib
)
".venv\Scripts\python.exe" skrytyj_tekst.py %*
echo.
pause
exit /b

:nopython
echo Python не найден. Установите Python с сайта python.org и запустите файл снова.
pause
exit /b 1

:nolib
echo Библиотеку установить не удалось. При первом запуске нужно подключение к интернету.
pause
exit /b 1
