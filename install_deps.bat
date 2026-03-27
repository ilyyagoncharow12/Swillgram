@echo off
echo Установка зависимостей для Communication App...
echo.

echo Удаление старых версий PyQt5...
pip uninstall PyQt5 PyQt5-Qt5 PyQt5-sip -y

echo Установка PyQt5...
pip install PyQt5==5.15.9

echo Установка остальных зависимостей...
pip install opencv-python
pip install numpy
pip install pyaudio
pip install pygetwindow

echo.
echo Установка завершена!
echo Запустите приложение командой: python main.py
pause