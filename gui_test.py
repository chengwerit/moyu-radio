"""GUI 无头自测：实例化主窗口，验证加载/播放/点喜欢全流程。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from main import MainWindow

app = QApplication(sys.argv)
w = MainWindow()
w.show()

steps = []
results = {}


def step1():
    """等歌单加载完"""
    if not w.tracks:
        if len(steps) < 40:
            steps.append(0)
            QTimer.singleShot(700, step1)
        else:
            results["tracks"] = "超时无歌单"
            QTimer.singleShot(100, step3)
        return
    results["tracks"] = f"{len(w.tracks)} 首"
    results["first"] = w.tracks[0].display
    print("1) 歌单加载:", results["tracks"], "|", results["first"], flush=True)
    QTimer.singleShot(500, step2)


def step2():
    """等播放解析完"""
    if not w.current_url:
        if len(steps) < 40:
            steps.append(0)
            QTimer.singleShot(700, step2)
        else:
            results["play"] = "超时未解析"
            QTimer.singleShot(100, step3)
        return
    results["play"] = w.current_url[:70]
    print("2) 播放直链:", results["play"], flush=True)
    print("   状态栏:", w.status.text(), flush=True)
    QTimer.singleShot(500, step2b)


def step2b():
    """点喜欢，触发 FLAC 下载"""
    print("3) 点击 ♥ 喜欢并存 FLAC …", flush=True)
    w.on_like()
    QTimer.singleShot(200, step2c)


def step2c():
    # 下载中（按钮禁用），继续等
    if not w.like_btn.isEnabled():
        if len(steps) < 200:
            steps.append(0)
            QTimer.singleShot(1000, step2c)
        else:
            results["like"] = "超时（仍在下载）"
            QTimer.singleShot(100, step3)
        return
    results["like"] = w.dl_status.text()
    print("4) 收藏结果:", results["like"][:220], flush=True)
    QTimer.singleShot(300, step3)


def step3():
    print("\n===== GUI 自测汇总 =====")
    for k, v in results.items():
        print(f"  {k}: {v}")
    app.quit()


QTimer.singleShot(500, step1)
QTimer.singleShot(240000, app.quit)
app.exec()
