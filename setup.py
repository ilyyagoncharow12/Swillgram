# setup.py - скрипт для сборки приложения

import sys
from cx_Freeze import setup, Executable

# Зависимости
build_exe_options = {
    "packages": ["os", "sys", "socket", "threading", "json", "pickle", "struct",
                 "time", "uuid", "hashlib", "queue", "datetime", "pathlib",
                 "cv2", "numpy", "pyaudio", "PyQt5", "qtawesome", "zeroconf",
                 "netifaces", "requests"],
    "excludes": ["tkinter"],
    "include_files": ["README.md"],
    "optimize": 2
}

# Настройки
base = None
if sys.platform == "win32":
    base = "Win32GUI"

setup(
    name="CommunicationApp",
    version="1.0.0",
    description="Коммуникационное приложение с аудио/видео связью",
    options={"build_exe": build_exe_options},
    executables=[Executable("main.py", base=base, icon="app.ico")]
)