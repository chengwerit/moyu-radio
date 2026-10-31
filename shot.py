"""启动真实 GUI 并截图，用于视觉确认。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from main import MainWindow

app = QApplication(sys.argv)
w = MainWindow()
w.resize(1080, 700)
w.show()


def shoot():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshot.png")
    w.grab().save(out)
    print("saved:", out, os.path.getsize(out), "bytes")
    app.quit()


def wait_and_shoot():
    if w.tracks:
        QTimer.singleShot(2500, shoot)
    else:
        QTimer.singleShot(1500, wait_and_shoot)


QTimer.singleShot(400, wait_and_shoot)
QTimer.singleShot(90000, app.quit)
app.exec()
