"""墨语电台 —— 主窗口。

流程：选平台 → 随机取歌 → 播放 → 点 ♥ → 自动抓 FLAC 落盘。
"""
from __future__ import annotations

import os
import random
import sys
import threading
import traceback

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSlider,
    QSplitter, QVBoxLayout, QWidget,
)

# 让 `python app\main.py` 也能找到同级的 core 包。
# 普通 Python 会自动把脚本所在目录放进 sys.path，
# 但 embeddable 运行时（python312._pth）不会，必须显式补上。
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from core.quiet import is_verbose, silence_native_stderr

# 必须在 Qt 多媒体加载之前静音，否则 ffmpeg 的探测日志已经打出来了。
# MOYU_VERBOSE=1 可保留全部底层日志用于排查。
if not is_verbose():
    silence_native_stderr()

from core.downloader import download_flac, load_index, save_index
from core.player import Player
from core.sources import Track, random_tracks, resolve_flac, resolve_play

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY = os.path.join(APP_DIR, "music")
SETTINGS = os.path.join(APP_DIR, "data", "settings.json")

PLATFORMS = [
    ("netease", "网易云", "网易云音乐 · 歌单/榜单随机"),
    ("tencent", "QQ 音乐", "QQ 音乐 · 热歌榜"),
    ("kugou", "酷狗", "酷狗音乐 · 随机检索"),
    ("migu", "咪咕", "咪咕音乐 · 随机检索"),
    ("radio", "全球电台", "radio-browser · 全球电台流"),
]


# ------------------------------------------------------------------ 后台任务
class Worker(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)

    def _run(self):
        try:
            result = self._fn(self.progress.emit)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(str(e))
        else:
            self.done.emit(result)
        self._thread.quit()

    def start(self):
        self._thread.start()

    def wait(self, ms: int = 20000):
        self._thread.wait(ms)


class LoadWorker(Worker):
    pass


# ------------------------------------------------------------------ 主题
DARK = {
    "bg": "#16181d", "panel": "#1e2128", "card": "#242830",
    "text": "#e6e8ec", "sub": "#9aa0aa", "line": "#333844",
    "accent": "#6c8cff", "accent2": "#3d5bd9", "pink": "#ff6b8a",
    "green": "#4ec98a",
}


class CoverLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(188, 188)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background:{DARK['card']};border-radius:10px;color:{DARK['sub']};font-size:12px;")
        self.setText("无封面")

    def set_url(self, url: str):
        self.setText("载入中…")
        def work():
            try:
                from core.downloader import fetch_cover
                data = fetch_cover(url)
                if not data:
                    self.setText("无封面")
                    return
                from PySide6.QtGui import QPixmap
                import io
                pm = QPixmap()
                pm.loadFromData(data)
                self.setPixmap(pm.scaled(188, 188, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.SmoothTransformation))
            except Exception:
                self.setText("无封面")
        threading.Thread(target=work, daemon=True).start()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("墨语电台 · 随机听歌自动收藏 FLAC")
        self.resize(1080, 700)
        self.setStyleSheet(self._style())

        self.player = Player(self)
        self.player.finished.connect(self.on_track_finished)

        self.tracks: list[Track] = []
        self.index: dict = load_index(LIBRARY)
        self.current: Track | None = None
        self.current_url: str | None = None
        self.queue_pos = -1
        self.liked: list[str] = []
        self.downloaded_count = 0
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self.update_position)
        self._pos_timer.start(500)

        self._build_ui()
        self.load_settings()
        self.refresh_fav_list()
        QTimer.singleShot(300, self.load_tracks)

    # ------------------------------------------------------------ UI
    def _style(self) -> str:
        return f"""
        QWidget {{ background:{DARK['bg']}; color:{DARK['text']}; font-size:13px; }}
        QFrame#panel {{ background:{DARK['panel']}; border:1px solid {DARK['line']}; border-radius:12px; }}
        QFrame#card {{ background:{DARK['card']}; border:1px solid {DARK['line']}; border-radius:10px; }}
        QLabel#title {{ font-size:22px; font-weight:600; }}
        QLabel#sub {{ color:{DARK['sub']}; font-size:12px; }}
        QLabel#big {{ font-size:15px; font-weight:600; }}
        QListWidget {{ background:{DARK['panel']}; border:1px solid {DARK['line']};
                       border-radius:10px; padding:6px; outline:0; }}
        QListWidget::item {{ padding:8px 10px; border-radius:6px; }}
        QListWidget::item:selected {{ background:{DARK['accent2']}; }}
        QListWidget::item:hover {{ background:{DARK['card']}; }}
        QPushButton {{ background:{DARK['card']}; border:1px solid {DARK['line']};
                       border-radius:8px; padding:8px 14px; }}
        QPushButton:hover {{ border-color:{DARK['accent']}; }}
        QPushButton#primary {{ background:{DARK['accent']}; color:#fff; border:none; font-weight:600; }}
        QPushButton#primary:hover {{ background:{DARK['accent2']}; }}
        QPushButton#like {{ background:{DARK['pink']}; color:#fff; border:none; font-weight:600; padding:9px 22px; }}
        QPushButton#like:hover {{ background:#e0567a; }}
        QPushButton#like:disabled {{ background:#4a4046; color:#8a8085; }}
        QSlider::groove:horizontal {{ height:4px; background:{DARK['line']}; border-radius:2px; }}
        QSlider::handle:horizontal {{ background:{DARK['accent']}; width:13px; height:13px;
                                     margin:-5px 0; border-radius:6px; }}
        QProgressBar {{ background:{DARK['card']}; border:none; border-radius:4px; height:6px; text-align:center; }}
        QProgressBar::chunk {{ background:{DARK['green']}; border-radius:4px; }}
        QSpinBox {{ background:{DARK['card']}; border:1px solid {DARK['line']}; border-radius:6px; padding:3px 6px; }}
        """

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)

        # 顶部栏
        top = QHBoxLayout()
        logo = QLabel("墨语电台")
        logo.setObjectName("title")
        top.addWidget(logo)
        top.addWidget(QLabel("随机听 · 点喜欢自动存 FLAC 到本地"))
        top.addStretch()
        top.addWidget(QLabel("平台"))
        self.source_box = QComboBox()
        for key, name, desc in PLATFORMS:
            self.source_box.addItem(name, userData=key)
        self.source_box.setFixedWidth(130)
        top.addWidget(self.source_box)
        self.platform_label = QLabel(PLATFORMS[0][2])
        self.platform_label.setObjectName("sub")
        top.addWidget(self.platform_label)
        self.reload_btn = QPushButton("换一批")
        self.reload_btn.clicked.connect(self.load_tracks)
        top.addWidget(self.reload_btn)
        outer.addLayout(top)

        # 主体
        split = QSplitter(Qt.Orientation.Horizontal)

        left = QFrame()
        left.setObjectName("panel")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.play_selected)
        lv.addWidget(self.list)

        self.count_label = QLabel("准备中…")
        self.count_label.setObjectName("sub")
        lv.addWidget(self.count_label)
        split.addWidget(left)

        right = QFrame()
        right.setObjectName("panel")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(16, 16, 16, 16)
        rv.setSpacing(12)

        self.cover = CoverLabel()
        rv.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)

        self.now_title = QLabel("未在播放")
        self.now_title.setObjectName("big")
        self.now_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.now_title.setWordWrap(True)
        rv.addWidget(self.now_title)

        self.now_sub = QLabel("")
        self.now_sub.setObjectName("sub")
        self.now_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.now_sub.setWordWrap(True)
        rv.addWidget(self.now_sub)

        # 进度条
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderReleased.connect(self.on_seek)
        rv.addWidget(self.slider)
        time_row = QHBoxLayout()
        self.time_cur = QLabel("0:00")
        self.time_cur.setObjectName("sub")
        self.time_total = QLabel("0:00")
        self.time_total.setObjectName("sub")
        time_row.addWidget(self.time_cur)
        time_row.addStretch()
        time_row.addWidget(self.time_total)
        rv.addLayout(time_row)

        # 控制
        ctrl = QHBoxLayout()
        self.prev_btn = QPushButton("上一首")
        self.prev_btn.clicked.connect(self.play_prev)
        self.play_btn = QPushButton("播放")
        self.play_btn.setObjectName("primary")
        self.play_btn.clicked.connect(self.toggle_play)
        self.next_btn = QPushButton("下一首")
        self.next_btn.clicked.connect(self.play_next)
        ctrl.addWidget(self.prev_btn)
        ctrl.addWidget(self.play_btn)
        ctrl.addWidget(self.next_btn)
        rv.addLayout(ctrl)

        # 喜欢 + 下载
        like_row = QHBoxLayout()
        self.like_btn = QPushButton("♥ 喜欢并存 FLAC")
        self.like_btn.setObjectName("like")
        self.like_btn.clicked.connect(self.on_like)
        like_row.addStretch()
        like_row.addWidget(self.like_btn)
        rv.addLayout(like_row)

        self.dl_progress = QProgressBar()
        self.dl_progress.setRange(0, 100)
        self.dl_progress.setVisible(False)
        rv.addWidget(self.dl_progress)

        self.dl_status = QLabel("")
        self.dl_status.setObjectName("sub")
        self.dl_status.setWordWrap(True)
        rv.addWidget(self.dl_status)

        self.status = QLabel("")
        self.status.setObjectName("sub")
        self.status.setWordWrap(True)
        rv.addWidget(self.status)

        self.stat_label = QLabel("")
        self.stat_label.setObjectName("sub")
        rv.addWidget(self.stat_label)

        # 已收藏列表
        fav_title = QLabel("已收藏")
        fav_title.setObjectName("big")
        rv.addWidget(fav_title)
        self.fav_list = QListWidget()
        self.fav_list.setMinimumHeight(120)
        self.fav_list.itemDoubleClicked.connect(self.play_fav)
        rv.addWidget(self.fav_list, 1)
        rv.addStretch(0)

        split.addWidget(right)
        split.setSizes([620, 400])
        outer.addWidget(split, 1)

        self.source_box.currentIndexChanged.connect(self.on_source_changed)

    # ------------------------------------------------------------ 设置
    def load_settings(self):
        import json
        try:
            with open(SETTINGS, "r", encoding="utf-8") as f:
                s = json.load(f)
            idx = int(s.get("platform_index", 0))
            if 0 <= idx < len(PLATFORMS):
                self.source_box.setCurrentIndex(idx)
            self.library_dir = s.get("library", LIBRARY)
        except Exception:
            self.library_dir = LIBRARY
        self.update_stat()

    def save_settings(self):
        import json
        try:
            os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
            with open(SETTINGS, "w", encoding="utf-8") as f:
                json.dump({"platform_index": self.source_box.currentIndex(),
                           "library": self.library_dir}, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def update_stat(self):
        self.stat_label.setText(f"音乐库：{self.library_dir}\n已收藏 {len(self.index)} 首")

    def on_source_changed(self, idx: int):
        self.platform_label.setText(PLATFORMS[idx][2])
        self.load_tracks()

    # ------------------------------------------------------------ 取歌
    def load_tracks(self):
        idx = self.source_box.currentIndex()
        src = PLATFORMS[idx][0]
        self.list.clear()
        self.count_label.setText("正在取歌…")
        self.status.setText("")

        def work(progress):
            return random_tracks(src, limit=80)

        w = LoadWorker(work)
        w.done.connect(self.on_tracks_loaded)
        w.failed.connect(lambda e: self.count_label.setText(f"取歌失败：{e}"))
        w.start()
        self._loader = w

    def on_tracks_loaded(self, tracks):
        self.tracks = tracks or []
        for t in self.tracks:
            it = QListWidgetItem(f"{t.title}    ·  {t.artist}")
            it.setData(Qt.ItemDataRole.UserRole, t)
            self.list.addItem(it)
        self.count_label.setText(f"{len(self.tracks)} 首 · 双击播放")
        if self.tracks and self.current is None:
            self.play_index(0)

    def refresh_fav_list(self):
        self.fav_list.clear()
        for key, meta in list(self.index.items())[-60:][::-1]:
            it = QListWidgetItem(f"{meta.get('title','')}    ·  {meta.get('artist','')}")
            it.setData(Qt.ItemDataRole.UserRole, meta.get("path", ""))
            self.fav_list.addItem(it)

    def play_fav(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            self.player.play_local(path)
            self.now_title.setText(os.path.splitext(os.path.basename(path))[0])
            self.now_sub.setText("本地音乐库")
            self.play_btn.setText("暂停")
            self.status.setText("正在播放本地文件")

    # ------------------------------------------------------------ 播放
    def play_index(self, i: int):
        if not self.tracks:
            return
        i = max(0, min(i, len(self.tracks) - 1))
        self.queue_pos = i
        t = self.tracks[i]
        self.current = t
        self.list.setCurrentRow(i)
        self.now_title.setText(t.title)
        self.now_sub.setText(f"{t.artist}    ·    {t.album or '单曲'}    ·    {PLATFORMS[self.source_box.currentIndex()][1]}")
        self.cover.set_url(t.cover)
        self.like_btn.setEnabled(True)
        self.like_btn.setText("♥ 喜欢并存 FLAC")
        self.status.setText("正在解析播放地址…")

        def work(progress):
            return resolve_play(t)

        w = LoadWorker(work)
        w.done.connect(lambda r: self.on_resolved(r, t))
        w.failed.connect(lambda e: self.status.setText(f"解析失败：{e}"))
        w.start()
        self._resolver = w

    def on_resolved(self, result, track):
        url, desc = result if isinstance(result, tuple) else (None, "解析失败")
        if not url:
            self.status.setText("该曲目无法解析播放，已跳到下一首")
            QTimer.singleShot(1200, self.play_next)
            return
        self.current_url = url
        self.player.play_url(url, track.title)
        self.status.setText(f"正在播放 · {desc}")
        self.play_btn.setText("暂停")

    def play_selected(self, item):
        row = self.list.row(item)
        if row >= 0:
            self.play_index(row)

    def play_next(self):
        if not self.tracks:
            return
        self.play_index((self.queue_pos + 1) % len(self.tracks))

    def play_prev(self):
        if not self.tracks:
            return
        self.play_index((self.queue_pos - 1) % len(self.tracks))

    def toggle_play(self):
        if self.player.is_playing():
            self.player.toggle()
            self.play_btn.setText("播放")
        else:
            if self.current_url:
                self.player.play_url(self.current_url)
                self.play_btn.setText("暂停")

    def on_track_finished(self):
        self.play_next()

    def on_seek(self):
        d = self.player.duration
        if d > 0:
            self.player.seek(int(self.slider.value() / 1000 * d))

    def update_position(self):
        d = self.player.duration
        p = self.player.position
        if d > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(int(p / d * 1000))
            self.slider.blockSignals(False)
            self.time_total.setText(self._fmt(d))
        self.time_cur.setText(self._fmt(p))

    @staticmethod
    def _fmt(ms: int) -> str:
        s = max(0, ms // 1000)
        return f"{s // 60}:{s % 60:02d}"

    # ------------------------------------------------------------ 喜欢 → 下载
    def on_like(self):
        t = self.current
        if not t:
            return
        if t.source == "radio":
            self.dl_status.setText("电台直播流没有单曲文件，无法收藏为 FLAC")
            return
        key = f"{t.source}:{t.source_id}"
        if key in self.index:
            self.dl_status.setText(f"已在收藏：{self.index[key].get('title', t.title)}")
            return
        self.like_btn.setEnabled(False)
        self.like_btn.setText("解析无损中…")
        self.dl_status.setText("正在寻找 FLAC 无损直链…")

        def work(progress):
            url, desc = resolve_flac(t)
            if not url:
                return ("", "未找到无损版本", desc)
            nid = t.source_id if t.source == "netease" else ""
            if not nid:
                from core.sources import netease_search_ids
                hits = netease_search_ids(t.title, t.artist)
                nid = hits[0][0] if hits else ""
            res = download_flac(url, t, self.library_dir, nid, progress)
            return (res.path if res.ok else "", res.message if res.ok else res.message, desc)

        w = LoadWorker(work)
        w.progress.connect(self.on_dl_progress)
        w.done.connect(self.on_downloaded)
        w.failed.connect(lambda e: self._like_failed(str(e)))
        w.start()
        self._downloader = w

    def on_dl_progress(self, got: int, total: int):
        self.dl_progress.setVisible(True)
        if total > 0:
            self.dl_progress.setValue(int(got / total * 100))
            self.dl_status.setText(f"正在下载 FLAC… {got // 1048576} / {total // 1048576} MB")
        else:
            self.dl_progress.setRange(0, 0)
            self.dl_status.setText(f"正在下载 FLAC… {got // 1048576} MB")

    def on_downloaded(self, result):
        path, message, desc = result if isinstance(result, tuple) else ("", "失败", "")
        t = self.current
        if path:
            self.downloaded_count += 1
            if t:
                key = f"{t.source}:{t.source_id}"
                self.index[key] = {"title": t.title, "artist": t.artist, "path": path,
                                   "source": t.source, "at": self._now()}
                save_index(self.library_dir, self.index)
            self.like_btn.setText("♥ 已收藏")
            self.dl_status.setText(f"✓ {message} · {desc}\n{path}")
            self.update_stat()
            self.refresh_fav_list()
        else:
            self._like_failed(message)
        self.dl_progress.setVisible(False)
        self.like_btn.setEnabled(True)

    def _like_failed(self, msg: str):
        self.dl_status.setText(f"收藏失败：{msg}")
        self.like_btn.setEnabled(True)
        self.like_btn.setText("♥ 喜欢并存 FLAC")
        self.dl_progress.setVisible(False)

    @staticmethod
    def _now() -> str:
        import datetime
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def closeEvent(self, event):
        self.save_settings()
        self.player.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("墨语电台")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
