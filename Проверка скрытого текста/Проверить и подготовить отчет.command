#!/bin/bash
# Проверка рабочей папки на скрытый текст. Запуск двойным щелчком.
cd "$(dirname "$0")" || exit 1
pause() { echo; read -r -p "Нажмите Enter, чтобы закрыть окно" _; }
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python не найден. Установите Python с сайта python.org и запустите файл снова."
  pause; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Первый запуск. Устанавливается библиотека для чтения PDF, это займет около минуты."
  python3 -m venv .venv || { echo "Python не удалось подготовить к работе."; pause; exit 1; }
fi
if ! .venv/bin/python -c "import pymupdf, numpy" 2>/dev/null; then
  .venv/bin/python -m pip install --disable-pip-version-check -q pymupdf numpy || {
    echo "Библиотеку установить не удалось. При первом запуске нужно подключение к интернету."; pause; exit 1; }
fi
.venv/bin/python skrytyj_tekst.py "$@"
pause
