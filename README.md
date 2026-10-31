# 墨语电台

> 随机听歌，遇到喜欢的点一下 ♥，自动把 **FLAC 无损** 下载到本地音乐库。

本地桌面应用（PySide6），五个平台随机播，点「♥ 喜欢并存 FLAC」自动解析无损直链并落盘。

## 快速开始

**双击 `启动墨语电台.bat` 即可** —— 项目自带 Python 运行时（`runtime/`），
不依赖你电脑上是否装过 Python。首次启动会自动补齐缺失的依赖。

## 功能

| 能力 | 说明 |
|---|---|
| 多平台随机播 | 网易云 / QQ 音乐 / 酷狗 / 咪咕 / 全球电台，右上角下拉切换 |
| 点喜欢自动存 FLAC | 自动解析无损直链 → 下载 → 写 ID3 标签 + 内嵌封面 + 侧挂 LRC 歌词 |
| 智能落盘 | `音乐库/歌手/专辑/歌名.flac` |
| 本地曲库 | 右侧「已收藏」列表，双击直接播本地文件 |
| 断点友好 | 同名同歌手文件已存在则跳过；收藏记录存 JSON |

## 代码结构

```
app/
├─ main.py              主窗口、线程调度、交互
└─ core/
   ├─ sources.py        五平台接口层 + eapi 加密 + 跨平台匹配 + FLAC 解析
   ├─ player.py         播放内核（Qt 多媒体，ffplay 兜底）
   ├─ downloader.py     下载、校验、写标签封面歌词
   └─ quiet.py          屏蔽 ffmpeg 底层噪音（保留异常可见）
runtime/                自带 Python 3.12 + PySide6（embeddable）
```

## 关键技术点

**网易云 eapi 加密**（无需登录）
- AES-128-ECB，密钥 `e82ckenh8dichen8`
- 明文 `{url}-36cd479b6b5-{json}-36cd479b6b5-{md5}`，md5 对 `nobody{url}use{json}md5forencrypt`
- 域名 `interfacepc.music.163.com`，路径 `/eapi/...`

**FLAC 直链**：`GET https://music-api.gdstudio.xyz/api.php?types=url&source=netease&id={songId}&br=999` —— 唯一免登录能拿真 FLAC 的通路。

**跨平台匹配**：QQ / 酷狗 / 咪咕 的免登录接口拿不到稳定播放直链，因此用「歌名 + 歌手」在网易云精确搜索，按标题与歌手双维度打分（版本号如"钢琴版/女声版"降权），再取播放与无损直链。

详见 `使用说明.md` 第五、六节（含已废弃接口清单，避免重复踩坑）。

## 验证脚本

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY   # 本机有代理会连不上
runtime/python.exe smoke_test.py    # 核心链路冒烟
runtime/python.exe regression.py    # 五平台全链路回归
runtime/python.exe gui_test.py      # 无头 GUI 流程
runtime/python.exe shot.py          # 截图
```

## 依赖

PySide6 ≥ 6.5 · mutagen ≥ 1.45 · requests ≥ 2.31 · pycryptodome ≥ 3.19
（已内置在 `runtime/`，`requirements.txt` 仅供手动安装时参考）

> 注：mutagen 1.48 起 `Picture.TYPE_FRONT_COVER` 常量已移除，代码中改用裸数字 3 并显式赋值 `mime`/`desc`/`data`。
