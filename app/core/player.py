"""播放内核：优先用 Qt 多媒体；失败时回退 ffplay。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

FFPLAY_CANDIDATES = [
    r"C:\Users\linlin\Tools\yt-dlp\ffplay.exe",
    "ffplay",
]


class Player(QObject):
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._q.setAudioOutput(self._audio)
        self._audio.setVolume(0.7)
        self._fallback = False
        self._proc: subprocess.Popen | None = None
        self._ended = False
        self._q.mediaStatusChanged.connect(self._on_status)

    # ---------------------------------------------------------- 状态
    @property
    def duration(self) -> int:
        return max(0, self._q.duration())

    @property
    def position(self) -> int:
        return max(0, self._q.position())

    def set_volume(self, v: float) -> None:
        self._audio.setVolume(max(0.0, min(1.0, v)))

    def is_playing(self) -> bool:
        if self._fallback and self._proc:
            return self._proc.poll() is None
        return self._q.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    # ---------------------------------------------------------- 控制
    def play_url(self, url: str, title: str = "") -> bool:
        self.stop()
        self._ended = False
        if not url:
            return False
        self._q.setSource(QUrl(url))
        self._q.play()
        return True

    def play_local(self, path: str) -> bool:
        return self.play_url(QUrl.fromLocalFile(path).toString(), os.path.basename(path))

    def toggle(self) -> None:
        if self._fallback and self._proc:
            return
        if self._q.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._q.pause()
        else:
            self._q.play()

    def stop(self) -> None:
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        self._q.stop()

    def seek(self, ms: int) -> None:
        if not self._fallback:
            self._q.setPosition(max(0, ms))

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia and not self._ended:
            self._ended = True
            self.finished.emit()

    # ---------------------------------------------------------- ffplay 回退
    def _find_ffplay(self) -> str | None:
        for c in FFPLAY_CANDIDATES:
            if os.path.isfile(c):
                return c
        found = shutil.which("ffplay")
        return found

    def play_with_ffplay(self, url: str) -> bool:
        exe = self._find_ffplay()
        if not exe:
            return False
        try:
            self._q.stop()
            self._fallback = True
            self._proc = subprocess.Popen(
                [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            self._proc = None
            return False
        return True
