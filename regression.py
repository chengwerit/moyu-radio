"""多平台全链路回归：每个平台取歌 → 解析播放 → 解析 FLAC → 下载。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from core.downloader import download_flac
from core.sources import random_tracks, resolve_flac, resolve_play

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_test")
SAMPLES = 3

for src in ["netease", "tencent", "kugou", "migu", "radio"]:
    print("=" * 70, flush=True)
    print(f"平台：{src}", flush=True)
    tracks = random_tracks(src, limit=14)
    print(f"  取歌 {len(tracks)} 首", flush=True)
    if not tracks:
        print("  !! 无曲目", flush=True)
        continue
    for t in tracks[:SAMPLES]:
        pu, pdesc = resolve_play(t)
        print(f"  ▸ {t.display[:32]:<34} 播放 {'OK' if pu else 'FAIL'} ({pdesc})", flush=True)
        fu, fdesc = resolve_flac(t)
        if fu:
            res = download_flac(fu, t, LIB, t.source_id if t.source == "netease" else "")
            print(f"      FLAC {'OK' if res.ok else 'FAIL'} {res.message} "
                  f"{os.path.getsize(res.path)//1024 if res.ok and os.path.exists(res.path) else 0}KB", flush=True)
        else:
            print(f"      FLAC FAIL ({fdesc})", flush=True)

print("=" * 70, flush=True)
print("全部平台测试结束", flush=True)
