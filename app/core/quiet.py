"""静音 Qt/ffmpeg 底层库直接写到 stderr 的探测日志。

背景：Qt 6 的多媒体后端用 ffmpeg 解码，libavformat 会把
"Input #0, mp3, from ..." / "[av1_mf @ ...] could not find any MFT" 这类
探测信息直接写到 **C 层的 fd 2**。Qt 的 QT_LOGGING_RULES 管不到它们。

关键坑：fd 2 是 Python 的 sys.stderr 和 C 库共用的。
- 只做 dup2(devnull, 2) → ffmpeg 安静了，但 Python 的 traceback 也一起没了，
  真实错误彻底不可见，比噪音更危险。
- 只过滤 sys.stderr → 完全拦不住 ffmpeg（它不经过 Python）。

正确做法：**拆成两个通道**
  fd 2（dup2 到 devnull）→ 给 C 库（ffmpeg）用，噪音丢弃
  sys.stderr（重绑到 dup 出来的原 fd）→ 给 Python 用，异常照常可见
"""
from __future__ import annotations

import atexit
import os
import sys

_original_stderr = None
_enabled = False


def silence_native_stderr() -> None:
    """把 C 层 stderr 丢进 devnull，同时保留 Python 的 stderr 输出。"""
    global _original_stderr, _enabled
    if _enabled:
        return
    try:
        # 1) 先把当前 fd 2 复制一份，留给 Python 用
        python_fd = os.dup(2)
        # 2) 让 fd 2 指向 devnull，C 库的输出就都进黑洞了
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, 2)
        os.close(devnull_fd)
        # 3) Python 的 sys.stderr 改指向刚才复制出来的 fd
        _original_stderr = sys.stderr
        sys.stderr = os.fdopen(
            python_fd, "w", encoding="utf-8", errors="replace", closefd=True
        )
        atexit.register(_flush)
        _enabled = True
    except Exception:
        # 静音失败就保持原样，宁可吵也不要吞掉错误
        pass


def _flush() -> None:
    try:
        sys.stderr.flush()
    except Exception:
        pass


def restore_stderr() -> None:
    """恢复原始 stderr（调试用）。"""
    global _original_stderr, _enabled
    if not _enabled:
        return
    try:
        sys.stderr.flush()
        sys.stderr = _original_stderr or sys.stderr
    except Exception:
        pass
    finally:
        _enabled = False


def is_verbose() -> bool:
    """设 MOYU_VERBOSE=1 可保留全部底层日志。"""
    return os.environ.get("MOYU_VERBOSE", "") == "1"
