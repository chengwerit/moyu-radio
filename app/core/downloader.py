"""下载器：抓 FLAC 直链 → 落盘 → 写标签与封面。

落盘结构：<音乐库>/<歌手>/<专辑>/<歌名>.flac
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass

from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, TALB, TCON, TDRC, TIT2, TPE1, TRCK, APIC, USLT
from mutagen.id3 import ID3NoHeaderError

from .sources import UA, Track, netease_public

ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def safe(name: str, fallback: str = "未知") -> str:
    name = ILLEGAL.sub("_", (name or "").strip())
    name = name.rstrip(". ")
    return name or fallback


@dataclass
class DownloadResult:
    ok: bool
    path: str = ""
    message: str = ""
    bytes: int = 0


def _fetch_bytes(url: str, referer: str = "https://music.163.com/", timeout: int = 60) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def fetch_cover(cover_url: str) -> bytes | None:
    if not cover_url:
        return None
    try:
        data, _ = _fetch_bytes(cover_url, referer="https://music.163.com/", timeout=20)
        return data if len(data) > 1000 else None
    except Exception:
        return None


def fetch_lyric(netease_id: str) -> str:
    try:
        r = netease_public(f"/api/song/lyric?id={netease_id}&lv=1&kv=1&tv=-1")
        return ((r.get("lrc") or {}).get("lyric")) or ""
    except Exception:
        return ""


def write_tags(path: str, track: Track, netease_id: str = "", cover: bytes | None = None) -> None:
    """FLAC 标签用 mutagen.flac；若是 mp3 等则用 ID3。"""
    if path.lower().endswith(".flac"):
        try:
            f = FLAC(path)
            f["title"] = track.title
            f["artist"] = track.artist
            if track.album:
                f["album"] = track.album
            f["genre"] = "随机电台"
            if cover:
                pic = Picture()
                # mutagen 1.48 起 Picture 不再暴露 TYPE_* 常量，
                # 直接用裸数字 3（前封面）并显式给全部必填字段。
                pic.type = 3
                pic.mime = "image/jpeg"
                pic.desc = "Cover"
                pic.data = cover
                f.clear_pictures()
                f.add_picture(pic)
            f.save()
        except Exception as e:  # noqa: BLE001
            print(f"[标签写入失败] {path}: {e}", flush=True)
        return
    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.add(TIT2(encoding=3, text=track.title))
        tags.add(TPE1(encoding=3, text=track.artist))
        if track.album:
            tags.add(TALB(encoding=3, text=track.album))
        tags.add(TCON(encoding=3, text="随机电台"))
        if cover:
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
        tags.save(path, v2_version=3)
    except Exception as e:  # noqa: BLE001
        print(f"[标签写入失败] {path}: {e}", flush=True)


def write_lyric_sidecar(path: str, lyric: str) -> None:
    if not lyric:
        return
    try:
        with open(os.path.splitext(path)[0] + ".lrc", "w", encoding="utf-8") as f:
            f.write(lyric)
    except Exception:
        pass


def download_flac(url: str, track: Track, library: str, netease_id: str = "",
                  progress=None) -> DownloadResult:
    """下载 FLAC 并落盘。progress 为可选回调 (received, total)。"""
    artist = safe(track.artist.split("/")[0] if track.artist else "", "未知歌手")
    album = safe(track.album, "单曲")
    title = safe(track.title, "未知歌曲")
    folder = os.path.join(library, artist, album)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        return DownloadResult(False, message=f"无法创建目录：{e}")

    path = os.path.join(folder, f"{title}.flac")
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        return DownloadResult(True, path, "已存在，跳过", os.path.getsize(path))

    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://music.163.com/"})
        with urllib.request.urlopen(req, timeout=120) as r:
            total = int(r.headers.get("Content-Length") or 0)
            ctype = r.headers.get("Content-Type", "")
            chunks: list[bytes] = []
            got = 0
            while True:
                chunk = r.read(262_144)
                if not chunk:
                    break
                chunks.append(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
        data = b"".join(chunks)
    except Exception as e:  # noqa: BLE001
        return DownloadResult(False, message=f"下载失败：{e}")

    if len(data) < 20_000:
        return DownloadResult(False, message=f"响应过小（{len(data)} 字节），可能不是音频")

    if not data[:4] == b"fLaC":
        ct = (ctype or "").lower()
        if "flac" not in ct and "audio/mpeg" not in ct:
            return DownloadResult(False, message=f"返回的不是 FLAC（{ctype or '未知类型'}）")
        if "audio/mpeg" in ct:
            return DownloadResult(False, message="该源只提供 MP3，无损版本不可用")

    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as e:
        return DownloadResult(False, message=f"写入失败：{e}")

    cover = fetch_cover(track.cover) if track.cover else None
    write_tags(path, track, netease_id, cover)
    if netease_id:
        write_lyric_sidecar(path, fetch_lyric(netease_id))
    return DownloadResult(True, path, "FLAC 已保存", len(data))


def library_index_path(library: str) -> str:
    return os.path.join(library, ".moyu-radio-index.json")


def load_index(library: str) -> dict:
    p = library_index_path(library)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_index(library: str, index: dict) -> None:
    p = library_index_path(library)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
