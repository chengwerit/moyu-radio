"""音乐源接口层。

多平台接入：网易云 / QQ 音乐 / 酷狗 / 咪咕 / 全球电台。
每个平台提供两类能力：
  - 随机播：给出一批候选曲目（榜单 / 歌单 / 电台）
  - 解析：把曲目解析成可播放的直链，以及可下载的 FLAC 直链

设计要点：
  * 网易云走 eapi 加密（AES-128-ECB + MD5 摘要），无需登录即可取到 320k 播放直链。
  * FLAC 统一走 gdstudio 的解灰接口，用网易云 song id 换取无损直链。
  * 非网易云的曲目（QQ / 酷狗）先用歌名+歌手在网易云搜到对应 id，再走同一条 FLAC 通路。
"""
from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from Crypto.Cipher import AES

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
GDSTUDIO = "https://music-api.gdstudio.xyz/api.php"
EAPI_DOMAIN = "https://interfacepc.music.163.com"
EAPI_KEY = b"e82ckenh8dichen8"

# 网易云榜单 id
NETEASE_TOPLISTS = [
    ("3778678", "热歌榜"), ("3778679", "飙升榜"), ("3778680", "原创榜"),
    ("7452421333", "新歌榜"), ("2801058394", " DJs 榜"), ("1974443814", "电音榜"),
]


@dataclass
class Track:
    title: str
    artist: str
    source: str            # netease / tencent / kugou / migu / radio
    source_id: str         # 各平台内的曲目 id
    album: str = ""
    cover: str = ""
    duration: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def display(self) -> str:
        return f"{self.title} - {self.artist}"


class HttpError(Exception):
    pass


def http_bytes(url: str, referer: str | None = None, timeout: int = 25,
               data: bytes | None = None, headers: dict | None = None) -> bytes:
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_json(url: str, referer: str | None = None, timeout: int = 25,
              form: dict | None = None, headers: dict | None = None) -> dict | list:
    body = urllib.parse.urlencode(form).encode() if form else None
    h = {"Content-Type": "application/x-www-form-urlencoded"} if form else None
    if headers:
        h = {**(h or {}), **headers}
    raw = http_bytes(url, referer=referer, timeout=timeout, data=body, headers=h)
    return json.loads(raw.decode("utf-8", "replace"))


def http_json_retry(url: str, tries: int = 4, pause: float = 1.5, **kw):
    """gdstudio 偶发超时，重试几次。"""
    last = None
    for i in range(tries):
        try:
            return http_json(url, **kw)
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(pause)
    raise last if last else HttpError("request failed")


# ---------------------------------------------------------------- 网易云 eapi
def _eapi_params(url_path: str, obj: dict) -> str:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.md5(f"nobody{url_path}use{text}md5forencrypt".encode()).hexdigest()
    raw = f"{url_path}-36cd479b6b5-{text}-36cd479b6b5-{digest}".encode()
    pad = 16 - len(raw) % 16
    raw += bytes([pad]) * pad
    return AES.new(EAPI_KEY, AES.MODE_ECB).encrypt(raw).hex().upper()


def netease_api(url_path: str, obj: dict, timeout: int = 30) -> dict:
    params = _eapi_params(url_path, obj)
    url = f"{EAPI_DOMAIN}/eapi{url_path}"
    raw = http_bytes(url, referer="https://music.163.com/", timeout=timeout,
                     data=urllib.parse.urlencode({"params": params}).encode(),
                     headers={"Content-Type": "application/x-www-form-urlencoded",
                              "Cookie": "os=pc; appver=2.9.7"})
    return json.loads(raw.decode("utf-8", "replace"))


def netease_public(path: str, referer: str = "https://music.163.com/", timeout: int = 20) -> dict:
    return http_json(f"https://music.163.com{path}", referer=referer, timeout=timeout)


# ---------------------------------------------------------------- 各平台取曲
def netease_playlist_pool(limit: int = 40) -> list[tuple[str, str]]:
    """歌单广场 + 榜单，组成随机池。"""
    pool: list[tuple[str, str]] = []
    try:
        r = netease_public("/api/playlist/list?cat=%E5%85%A8%E9%83%A8&order=hot&limit=30&offset=0")
        for p in r.get("playlists") or []:
            pool.append((str(p["id"]), p.get("name") or "网易云歌单"))
    except Exception:
        pass
    try:
        r = netease_public("/api/playlist/list?cat=%E5%8F%8D%E9%A6%99%E9%9F%B3%E4%B9%90&order=hot&limit=20&offset=0")
        for p in r.get("playlists") or []:
            pool.append((str(p["id"]), p.get("name") or "网易云歌单"))
    except Exception:
        pass
    pool.extend((pid, f"网易云·{name}") for pid, name in NETEASE_TOPLISTS)
    return pool


def netease_playlist_tracks(pid: str, limit: int = 60) -> list[Track]:
    """歌单曲目。公共 API 只返回前 10 首，用 eapi v3 拿完整列表。"""
    tracks: list[dict] = []
    try:
        r = netease_api("/api/v3/playlist/detail", {"id": pid, "n": 1000, "s": 0})
        tracks = (r.get("playlist") or {}).get("tracks") or []
    except Exception:
        tracks = []
    if not tracks:
        try:
            r = netease_public(f"/api/v6/playlist/detail?id={pid}&n=1000&s=0")
            tracks = (r.get("playlist") or {}).get("tracks") or []
        except Exception:
            tracks = []
    out: list[Track] = []
    for t in tracks[:limit]:
        artists = t.get("ar") or t.get("artists") or []
        al = t.get("al") or t.get("album") or {}
        out.append(Track(
            title=t.get("name") or "",
            artist="/".join(a.get("name", "") for a in artists),
            source="netease",
            source_id=str(t.get("id")),
            album=al.get("name") or "",
            cover=al.get("picUrl") or "",
            duration=int(t.get("duration") or t.get("dt") or 0),
        ))
    return out


def tencent_toplist_tracks(topid: int = 26, limit: int = 60) -> list[Track]:
    r = http_json(f"https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg?topid={topid}"
                   "&format=json&page=detail&type=top", referer="https://y.qq.com/")
    out: list[Track] = []
    for item in (r.get("songlist") or [])[:limit]:
        d = item.get("data") or {}
        singers = d.get("singer") or []
        out.append(Track(
            title=d.get("songname") or "",
            artist="/".join(s.get("name", "") for s in singers),
            source="tencent",
            source_id=str(d.get("songmid") or ""),
            album=d.get("albumname") or "",
            duration=int(d.get("interval") or 0),
            extra={"albumid": d.get("albumid"), "pic": f"https://y.gtimg.cn/music/photo_new/T002R500x500M000{d.get('albumid')}.jpg"},
        ))
    return out


def tencent_search(keyword: str, limit: int = 10) -> list[Track]:
    data = json.dumps({
        "comm": {"ct": -1, "cv": 2},
        "req": {"module": "music.search.SearchCgiService",
                "method": "DoSearchForQQMusicDesktop",
                "param": {"query": keyword, "num_per_page": limit, "page_num": 1}},
    }, ensure_ascii=False)
    r = http_json(f"https://u.y.qq.com/cgi-bin/musicu.fcg?data={urllib.parse.quote(data)}",
                  referer="https://y.qq.com/")
    out: list[Track] = []
    for d in ((r.get("req") or {}).get("data") or {}).get("body", {}).get("song", {}).get("list") or []:
        out.append(Track(
            title=d.get("title") or "",
            artist="/".join(s.get("name", "") for s in d.get("singer") or []),
            source="tencent",
            source_id=str(d.get("mid") or ""),
            album=(d.get("album") or {}).get("name") or "",
            extra={"pic": f"https://y.gtimg.cn/music/photo_new/T002R500x500M000{(d.get('album') or {}).get('mid')}.jpg"},
        ))
    return out


def kugou_search(keyword: str, limit: int = 10) -> list[Track]:
    """酷狗搜索（mobileservice v3，字段更干净）。"""
    try:
        r = http_json(f"https://mobileservice.kugou.com/api/v3/search/song?"
                      f"keyword={urllib.parse.quote(keyword)}&page=1&pagesize={limit}",
                      referer="https://www.kugou.com/")
    except Exception:
        return []
    out: list[Track] = []
    for s in (r.get("data") or {}).get("info") or []:
        name = s.get("songname") or ""
        artist = s.get("singername") or ""
        if not name:
            fn = s.get("filename") or ""
            if " - " in fn:
                artist, name = fn.split(" - ", 1)
        out.append(Track(
            title=name,
            artist=artist,
            source="kugou",
            source_id=s.get("hash") or "",
            album=s.get("album_name") or "",
            duration=int(s.get("duration") or 0) * 1000,
            extra={"sqhash": s.get("sqhash"), "320hash": s.get("320hash"),
                   "album_id": s.get("album_id"), "cover": s.get("img")},
        ))
    return out


def kugou_play_url(filehash: str) -> str | None:
    """酷狗播放直链（免登录）。"""
    for host in ("https://wwwapi.kugou.com/yy/index.php?r=play/getdata&hash=",
                 "https://www.kugou.com/yy/index.php?r=play/getdata&hash="):
        try:
            r = http_json(f"{host}{filehash}", referer="https://www.kugou.com/")
            files = (r.get("data") or {}).get("files") or []
            for f in files:
                if f.get("url"):
                    return f["url"]
        except Exception:
            continue
    return None


def migu_search(keyword: str, limit: int = 10) -> list[Track]:
    """咪咕搜索（免登录）。"""
    try:
        r = http_json("https://app.c.nf.migu.cn/MIGUM2.0/v1.0/content/search_all.do?"
                      f"isCopyright=1&isCorrect=1&pageNo=1&pageSize={limit}"
                      "&searchSwitch=%7B%22song%22%3A1%7D&sort=0&text="
                      + urllib.parse.quote(keyword),
                      referer="https://music.migu.cn/")
    except Exception:
        return []
    out: list[Track] = []
    for group in (r.get("songResultData") or {}).get("resultList") or []:
        for it in group:
            artists = "/".join(s.get("name", "") for s in (it.get("singers") or []))
            out.append(Track(
                title=it.get("name") or "",
                artist=artists,
                source="migu",
                source_id=str(it.get("id") or ""),
                album=it.get("album") or "",
                extra={"copyrightId": it.get("copyrightId"),
                       "formats": [(x.get("formatType"), x.get("size"))
                                   for x in (it.get("newRateFormats") or [])]},
            ))
    return out


def radio_stations(limit: int = 60, tag: str = "") -> list[Track]:
    """全球电台（radio-browser.info）。"""
    url = "https://de1.api.radio-browser.info/json/stations/topclick/100"
    if tag:
        url = f"https://de1.api.radio-browser.info/json/stations/search?tag={urllib.parse.quote(tag)}&limit=100&hidebroken=true"
    try:
        r = http_json(url, timeout=20)
    except Exception:
        return []
    out: list[Track] = []
    for st in (r or [])[:limit]:
        if not st.get("url_resolved"):
            continue
        out.append(Track(
            title=st.get("name") or "Radio",
            artist=st.get("country") or "全球电台",
            source="radio",
            source_id=st.get("stationuuid") or "",
            extra={"stream": st.get("url_resolved"), "codec": st.get("codec"),
                   "bitrate": st.get("bitrate"), "homepage": st.get("homepage")},
        ))
    return out


# ---------------------------------------------------------------- 统一解析
def netease_play_url(sid: str, level: str = "exhigh", br: int = 320000) -> str | None:
    """网易云播放直链（无需登录）。"""
    try:
        r = netease_api("/api/song/enhance/player/url",
                        {"ids": f"[{sid}]", "br": br, "level": level, "encodeType": "mp3"})
        d = r.get("data") or []
        return d[0].get("url") if d else None
    except Exception:
        return None


def netease_flac_url(sid: str) -> str | None:
    """通过 gdstudio 解灰换无损直链。"""
    try:
        r = http_json_retry(f"{GDSTUDIO}?types=url&source=netease&id={sid}&br=999", timeout=30)
        if isinstance(r, dict) and r.get("url"):
            return r["url"]
    except Exception:
        pass
    return None


def netease_search(name: str, artist: str = "", limit: int = 12) -> list[dict]:
    """网易云精确搜索（eapi cloudsearch/pc），返回原始 song 列表。"""
    keyword = f"{name} {artist}".strip()
    try:
        r = netease_api("/api/cloudsearch/pc", {
            "s": keyword, "type": 1, "limit": limit, "offset": 0, "total": True,
        })
    except Exception:
        return []
    return (r.get("result") or {}).get("songs") or []


_NOISE = ("live", "remix", "cover", "钢琴", "钢琴版", "伴奏", "纯音乐", "钢琴曲",
          "原唱", "女声版", "男声版", "深情版", "版)", "remaster", "instrumental")


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum() or ch in " -_&")


def _title_score(src: str, cand: str) -> float:
    a, b = _norm(src), _norm(cand)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # 候选名包含原名（原名常带 (Live) 等后缀）
    if b.startswith(a):
        return 0.85
    if a.startswith(b):
        return 0.8
    if a in b or b in a:
        return 0.6
    return 0.0


def _artist_score(src: str, cand: str) -> float:
    a, b = _norm(src), _norm(cand)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    for x in a.split("/"):
        for y in b.split("/"):
            if x and x == y:
                return 0.95
            if x and y and (x in y or y in x):
                return 0.7
    return 0.0


def match_score(src_title: str, src_artist: str, song: dict) -> float:
    """给候选歌打分，标题与歌手双维度加权，版本号（翻唱/钢琴版）降权。"""
    cand_title = song.get("name") or ""
    cand_artists = "/".join(a.get("name", "") for a in (song.get("ar") or song.get("artists") or []))
    ts = _title_score(src_title, cand_title)
    as_ = _artist_score(src_artist, cand_artists)
    if ts <= 0 and as_ <= 0:
        return 0.0
    score = ts * 0.62 + as_ * 0.38
    # 候选名里带「翻唱/钢琴/伴奏」等字样时降权
    low = cand_title.lower()
    for kw in _NOISE:
        if kw in low and kw not in _norm(src_title):
            score -= 0.35
            break
    return score


def netease_search_ids(name: str, artist: str = "", limit: int = 3,
                        min_score: float = 0.55) -> list[tuple[str, str, str]]:
    """在网易云搜歌并按匹配度排序，返回 [(id, title, artist)]。"""
    songs = netease_search(name, artist, limit=12)
    if not songs:
        return []
    scored = []
    for s in songs:
        sc = match_score(name, artist, s)
        if sc > 0:
            scored.append((sc, s))
    scored.sort(key=lambda x: -x[0])
    out = []
    for sc, s in scored[:limit]:
        if sc < min_score:
            continue
        arts = "/".join(a.get("name", "") for a in (s.get("ar") or s.get("artists") or []))
        out.append((str(s["id"]), s.get("name", ""), arts))
    if not out and scored:
        sc, s = scored[0]
        arts = "/".join(a.get("name", "") for a in (s.get("ar") or s.get("artists") or []))
        out.append((str(s["id"]), s.get("name", ""), arts))
    return out


def resolve_play(track: Track) -> tuple[str | None, str]:
    """解析出可播放直链。返回 (url, 实际音质描述)。"""
    if track.source == "radio":
        return track.extra.get("stream"), "直播流"
    if track.source == "netease":
        u = netease_play_url(track.source_id, "exhigh", 320000)
        return u, "320k MP3"
    if track.source == "kugou":
        u = kugou_play_url(track.source_id)
        if u:
            return u, "酷狗源"
    # QQ / 酷狗 / 咪咕：先试本平台，退回网易云同名匹配
    for sid, _, _ in netease_search_ids(track.title, track.artist):
        u = netease_play_url(sid)
        if u:
            return u, "320k MP3（网易云匹配）"
    return None, "无法解析"


def resolve_flac(track: Track) -> tuple[str | None, str]:
    """解析出 FLAC 直链。返回 (url, 描述)。"""
    if track.source == "radio":
        return None, "电台直播流无法转为 FLAC 文件"
    if track.source == "netease":
        u = netease_flac_url(track.source_id)
        if u:
            return u, "FLAC 无损"
    # 其他平台：先在网易云找同名歌，再换无损
    for sid, title, artist in netease_search_ids(track.title, track.artist):
        u = netease_flac_url(sid)
        if u:
            return u, f"FLAC 无损（网易云匹配：{title} - {artist}）"
    # 放宽条件再试一次：只按歌名搜
    for sid, title, artist in netease_search_ids(track.title, "", limit=3, min_score=0.5):
        u = netease_flac_url(sid)
        if u:
            return u, f"FLAC 无损（网易云匹配：{title} - {artist}）"
    return None, "未找到无损"


KUGOU_KEYWORDS = ["华语热歌", "轻音乐", "古典", "摇滚", "民谣", "电子", "治愈",
                  "深夜电台", "钢琴曲", "流行热歌", "粤语金曲", "国风"]
MIGU_KEYWORDS = ["热歌", "轻音乐", "民谣", "摇滚", "流行", "古风", "纯音乐",
                 "热门推荐", "新歌", "伤感"]


def random_tracks(source: str, limit: int = 40) -> list[Track]:
    """按平台随机取一批曲目。"""
    try:
        if source == "netease":
            pool = netease_playlist_pool()
            if not pool:
                return []
            pid, name = random.choice(pool)
            tracks = netease_playlist_tracks(pid, limit)
            for t in tracks:
                t.extra["playlist"] = name
            return tracks
        if source == "tencent":
            return tencent_toplist_tracks(limit=limit)
        if source == "kugou":
            tracks: list[Track] = []
            for kw in random.sample(KUGOU_KEYWORDS, 3):
                tracks.extend(kugou_search(kw, limit=12))
            return tracks[:limit]
        if source == "migu":
            tracks = []
            for kw in random.sample(MIGU_KEYWORDS, 3):
                tracks.extend(migu_search(kw, limit=12))
            return tracks[:limit]
        if source == "radio":
            return radio_stations(limit=limit)
    except Exception:
        return []
    return []
