"""无 GUI 冒烟测试：核心链路（取歌 → 解析 → 下载 → 打标签）。"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from core.downloader import download_flac, load_index, save_index
from core.sources import random_tracks, resolve_flac, resolve_play

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_test")

print("=" * 66)
for src in ["netease", "tencent", "kugou", "radio"]:
    t0 = time.time()
    tracks = random_tracks(src, limit=12)
    dt = time.time() - t0
    print(f"[{src:<8}] 取到 {len(tracks):>2} 首  ({dt:.1f}s)")
    for t in tracks[:2]:
        print(f"    · {t.display}  [id={t.source_id}]")

print("=" * 66)
print("随机源全部测试完毕，开始下载链路…")
tracks = random_tracks("netease", limit=8)
ok = 0
for t in tracks[:3]:
    pu, desc = resolve_play(t)
    print(f"\n播放 {t.display[:34]:<36} {'OK' if pu else 'FAIL'} {desc}")
    fu, fdesc = resolve_flac(t)
    print(f"无损 {t.display[:34]:<36} {'OK' if fu else 'FAIL'} {fdesc}")
    if not fu:
        continue
    res = download_flac(fu, t, LIB, t.source_id)
    print(f"下载 -> {res.ok} {res.message} {res.path}")
    if res.ok:
        ok += 1
        print(f"     size={res.bytes} bytes")

print("=" * 66)
print(f"下载成功 {ok}/3")
print("产物：")
for root, dirs, files in os.walk(LIB):
    for f in files:
        p = os.path.join(root, f)
        print(f"  {os.path.getsize(p):>10}  {os.path.relpath(p, LIB)}")
