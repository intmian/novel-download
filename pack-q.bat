@echo off
nuitka main.py --standalone --onefile --enable-plugin=pyqt6 --windows-console-mode=disable --remove-output
pause
