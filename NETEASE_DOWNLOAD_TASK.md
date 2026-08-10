# 任务：网易云歌曲 title/artist 分离 + 改为下载播放模式

## 项目位置
- botamusique 源码：`E:/Hermes/Mumblebot/botamusique/`
- git 仓库，当前分支 master

## 背景
当前网易云歌曲用 `type='radio'` 流式播放（ffmpeg 直接拉 CDN 流），有两个问题：
1. **title/artist 没分离**：radio item 的 name 被设为 `"歌曲名 - 歌手名"`（如 "日落大道 - 梁博"），播放列表显示时整个字符串作为标题，歌手显示 "??"。
2. **流式播放有局限**：网易云 CDN URL 20 分钟过期，且每次都要重新请求 API 拿 URL。用户希望改为**下载模式**：播放前下载到本地，之后同一首歌直接播本地文件（缓存命中）。

## 目标

### 1. title/artist 分离显示
网易云歌曲元数据来自 API：`name` = 歌曲名（"日落大道"），`artist` = 歌手名（"梁博"）。
播放列表/播放器应显示：标题 = "日落大道"，歌手 = "梁博"（分开两栏），而不是 "日落大道 - 梁博" 挤在一起。

### 2. 下载播放模式
新建媒体类型 `netease`，逻辑：
- **validate()**：请求网易云 API 拿 mp3 直链（带 cookie），存 `self.url`；设置 `self.title`（歌曲名）、`self.artist`（歌手名）、`self.duration`。如果本地文件已存在 → ready=yes 直接通过（缓存命中）。
- **prepare()**：用 `requests` 直接下载 mp3 到 `var.tmp_folder`（不走 yt-dlp——yt-dlp 无法解析网易云 CDN 链接，这是之前流式播放的原因）。下载完成后 ready=yes。
- **is_ready()**：检查本地文件存在。
- **uri()**：返回本地文件路径。
- **id 生成**：`md5("netease:" + song_id)`，同一首歌 id 稳定 → 数据库/cache 命中后不再重新下载。
- 支持从 dict 恢复（to_dict/from_dict 保存 song_id、title、artist、url、path、duration），重启后播放列表恢复时若本地文件在 → 直接播放，不在 → 重新 validate 拿 URL 再下载。

## 现有代码参考

### media/item.py（BaseItem 基类）
```python
class BaseItem:
    def __init__(self, from_dict=None):
        self.log = logging.getLogger("bot")
        self.type = "base"
        self.title = ""
        self.path = ""
        self.tags = []
        self.keywords = ""
        self.duration = 0
        self.version = 0
        if from_dict is None:
            self.id = ""
            self.ready = "pending"  # pending - is_valid() -> validated - prepare() -> yes, failed
        else:
            self.id = from_dict['id']
            self.ready = from_dict['ready']
            self.tags = from_dict['tags']
            self.title = from_dict['title']
            self.path = from_dict['path']
            self.keywords = from_dict['keywords']
            self.duration = from_dict['duration']
    def is_ready(self): ...
    def validate(self): raise ValidationFailedError(None)
    def uri(self): raise
    def prepare(self): return True
    def format_song_string(self, user): return self.id
    def format_current_playing(self, user): return self.id
    def format_title(self): return self.title
    def format_debug_string(self): return self.id
    def display_type(self): return ""
    def to_dict(self): return {"type","id","ready","title","path","tags","keywords","duration"}
```

### media/url.py（URLItem，最接近的参考——下载模式）
- `validate()`：检查本地文件 → 设置 title/duration → ready=validated
- `prepare()`：实际下载 → ready=yes
- `is_ready()`：`self.downloading or self.ready != 'yes'` → False；文件缺失 → ready='validated' 返回 False
- `to_dict()` 额外存 url

### media/item.py 的注册机制
```python
# 每种类型要注册三个函数
item_builders['url'] = url_item_builder
item_loaders['url'] = url_item_loader
item_id_generators['url'] = url_item_id_generator
```
builder: `def netease_item_builder(**kwargs): return NeteaseItem(kwargs['song_id'])`
loader: `def netease_item_loader(_dict): return NeteaseItem("", _dict)`
id_generator: `def netease_item_id_generator(**kwargs): return hashlib.md5(("netease:" + str(kwargs['song_id'])).encode()).hexdigest()`

### netease.py（API 客户端）
```python
client.get_song_url(song_id, cookie)  # 返回 mp3 URL 或 None
client.get_song_detail(song_id)       # 返回 {id, name, artist, album, cover, duration, fee}
client.search(keywords, limit)        # [{id, name, artist, album, cover, duration, fee}]
```

### 现在的调用点（都要改）
1. **netease_cmd.py** `_queue_url()`（67-74 行）：`type='radio', url=url, name=title` → 改成 `type='netease', song_id=..., title=..., artist=...`
2. **netease_cmd.py** `_song_label()`（60-64 行）：不再需要拼 "name - artist"
3. **interface.py** `_add_netease_tracks()`（410-452 行）：批量入队，`type='radio', url=url, name=name` → `type='netease', song_id=song_id, title=title, artist=artist`
4. **interface.py** `add_netease` 分支（602-618 行）：单曲入队
5. **interface.py** `move_item_next` rebuild（570 行附近）：`type='radio', url=item_obj.url, name=item_obj.title` → 需要处理 netease 类型（song_id, title, artist）

### interface.py 当前 add_netease 单曲分支（参考）
```python
elif 'add_netease' in payload:
    song_id = payload['add_netease']
    try:
        client = NeteaseClient(var.config.get('netease', 'api_url'))
        cookie_manager = NeteaseCookieManager(
            var.config.get('netease', 'cookie_file', fallback='config/netease_cookie.txt'))
        url = client.get_song_url(song_id, cookie_manager.get_cookie())
        detail = client.get_song_detail(song_id)
        title = (detail.get('name', '') or '') if detail else ''
        artist = (detail.get('artist', '') or '') if detail else ''
        name = f"{title} - {artist}" if title else ""
    except ...: abort(502)
    if not url: abort(400)
    music_wrapper = get_cached_wrapper_from_scrap(type='radio', url=url, name=name, user=user)
    var.playlist.append(music_wrapper)
    if len(var.playlist) == 2:
        var.bot.async_download_next()
```
改后：`music_wrapper = get_cached_wrapper_from_scrap(type='netease', song_id=song_id, title=title, artist=artist, user=user)`
（注意：get_cached_wrapper_from_scrap 内部用 item_id_generators 算 id，若 cache/db 已有该 id 则直接复用，不再请求 URL——validate 时才会处理下载）

## 新建文件：media/netease_item.py

```python
# coding=utf-8
"""Netease Cloud Music item - downloads the song to local storage before playing."""
import hashlib
import logging
import os
import threading
import requests

import util
import variables as var
from constants import tr_cli as tr
from media.item import BaseItem, item_builders, item_loaders, item_id_generators, ValidationFailedError, \
    PreparationFailedError
from netease import NeteaseClient, NeteaseCookieManager


def netease_item_builder(**kwargs):
    return NeteaseItem(kwargs['song_id'], kwargs.get('title', ''), kwargs.get('artist', ''))


def netease_item_loader(_dict):
    return NeteaseItem("", "", "", _dict)


def netease_item_id_generator(**kwargs):
    return hashlib.md5(("netease:" + str(kwargs['song_id'])).encode()).hexdigest()


item_builders['netease'] = netease_item_builder
item_loaders['netease'] = netease_item_loader
item_id_generators['netease'] = netease_item_id_generator


class NeteaseItem(BaseItem):
    def __init__(self, song_id, title="", artist="", from_dict=None):
        self.validating_lock = threading.Lock()
        if from_dict is None:
            super().__init__()
            self.song_id = str(song_id)
            self.title = title
            self.artist = artist
            self.url = ""
            self.duration = 0
            self.id = netease_item_id_generator(song_id=song_id)
            self.path = var.tmp_folder + self.id + ".mp3"
            self.keywords = f"{title} {artist}"
        else:
            super().__init__(from_dict)
            self.song_id = from_dict['song_id']
            self.artist = from_dict.get('artist', '')
            self.url = from_dict.get('url', '')
            self.path = from_dict.get('path', '')

        self.downloading = False
        self.type = "netease"

    def uri(self):
        return self.path

    def is_ready(self):
        if self.downloading or self.ready != 'yes':
            return False
        if self.ready == 'yes' and not os.path.exists(self.path):
            self.log.info("netease: music file missed for %s", self.format_debug_string())
            self.ready = 'validated'
            return False
        return True

    def _get_client_and_cookie(self):
        client = NeteaseClient(var.config.get('netease', 'api_url'))
        cookie_manager = NeteaseCookieManager(
            var.config.get('netease', 'cookie_file', fallback='config/netease_cookie.txt'))
        return client, cookie_manager.get_cookie()

    def validate(self):
        try:
            self.validating_lock.acquire()
            if self.ready in ['yes', 'validated']:
                return True

            # 本地文件已存在 → 直接可用（缓存命中）
            if os.path.exists(self.path):
                self.ready = "yes"
                return True

            # 请求网易云 API 拿直链
            client, cookie = self._get_client_and_cookie()
            url = client.get_song_url(self.song_id, cookie)
            if not url:
                self.ready = 'failed'
                raise ValidationFailedError(tr('netease_play_error'))
            self.url = url
            if not self.title or not self.artist:
                detail = client.get_song_detail(self.song_id)
                if detail:
                    self.title = detail.get('name', '') or self.title
                    self.artist = detail.get('artist', '') or self.artist
                    self.duration = detail.get('duration', 0) or self.duration

            # 时长检查（沿用 url 类型的逻辑）
            max_duration = var.config.getint('bot', 'max_track_duration') * 60
            if max_duration and self.duration and self.duration > max_duration:
                raise ValidationFailedError(tr('too_long', song=self.format_title(),
                                               duration=util.format_time(self.duration),
                                               max_duration=util.format_time(max_duration)))

            self.ready = "validated"
            self.version += 1
            return True
        finally:
            self.validating_lock.release()

    # Run in another thread
    def prepare(self):
        if not self.downloading:
            assert self.ready == 'validated'
            return self._download()
        else:
            assert self.ready == 'yes'
            return True

    def _download(self):
        util.clear_tmp_folder(var.tmp_folder, var.config.getint('bot', 'tmp_folder_max_size'))
        self.downloading = True
        self.ready = "preparing"

        try:
            self.log.info("netease: downloading %s - %s from %s", self.title, self.artist, self.url)
            # 断点续传式下载（网易云 CDN 支持 Range）
            headers = {'User-Agent': 'Mozilla/5.0'}
            with requests.get(self.url, stream=True, timeout=30, headers=headers) as r:
                r.raise_for_status()
                with open(self.path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            self.ready = "yes"
            self.log.info("netease: finished downloading %s", self.path)
        except (requests.RequestException, OSError) as e:
            self.log.error("netease: download failed: %s", e)
            self.ready = "failed"
            raise PreparationFailedError(tr('unable_download', item=self.format_title()))
        finally:
            self.downloading = False

        return True

    # ---- 显示 ----
    def format_title(self):
        return self.title if self.title else (f"网易云 {self.song_id}")

    def format_song_string(self, user):
        return tr("netease_song_item",
                  title=self.title,
                  artist=self.artist,
                  user=user)

    def format_current_playing(self, user):
        return tr("now_playing", item=self.format_song_string(user))

    def display_type(self):
        return tr("netease")

    def to_dict(self):
        dict_data = super().to_dict()
        dict_data['song_id'] = self.song_id
        dict_data['artist'] = self.artist
        dict_data['url'] = self.url
        return dict_data
```

## 语言文件新增（zh_CN.json / en_US.json 的 cli 段）
```json
"netease_song_item": "<b>{title}</b> - {artist}，由<i>{user}</i>添加。",
"netease": "网易云"
```
（netease_play_error 已存在，检查并复用；不需要新 key 就不加）

## 调用点改造

### 1. netease_cmd.py
```python
def _song_label(song):
    # 现在返回 "name - artist"，改为只返回 name（或保留给消息用，播放列表用 NeteaseItem 自带 title/artist）
    ...

def _queue_url(bot, user, url, title=""):
    # 改成 _queue_song(bot, user, song_id, title, artist)
    music_wrapper = get_cached_wrapper_from_scrap(
        type="netease", song_id=song_id, title=title, artist=artist, user=user)
    var.playlist.append(music_wrapper)
    ...
```
所有调用 `_queue_url` 的地方（cmd_yun_play/add/playid/addid/gedanid）都要传 song_id/title/artist。参考现有逻辑：
- `_play_or_add_song()`（94-111 行）：song dict 有 id/name/artist → 传这些
- `cmd_yun_gedanid`（227 行后）：tracks 有 id/name/artist → 传这些
- `_song_by_id`（186 行附近）：playid/addid 用

注意：cmd_yun_play 的 `_play_or_add_song` 之前先调 `_song_url(client, song_id)` 拿 URL 再入队——**现在不需要了**，直接 `_queue_song`（NeteaseItem.validate 会在后台线程处理 URL 获取+下载）。但要注意：如果 URL 拿不到（VIP/地域限制），validate 会失败 → bot 播放循环里会跳过并提示。检查 `_play_or_add_song` 的 `netease_play_error` 提示逻辑是否还合理（可以保留提前检查：先 get_song_url 试探，None 就直接提示错误，避免入队后才发现播不了）。

### 2. interface.py `_add_netease_tracks()`（批量）
当前：先 get_song_url 拿 URL，None 跳过，否则 `type='radio', url=url, name=name` 入队。
改后：
```python
def _add_netease_tracks(client, cookie, tracks, playlist_user):
    added = 0
    skipped = 0
    should_start_download = False
    for batch_start in range(0, len(tracks), 50):
        for track in tracks[batch_start:batch_start + 50]:
            song_id = track.get('id') if isinstance(track, dict) else None
            if not song_id:
                skipped += 1
                continue
            title = (track.get('name', '') or '') if isinstance(track, dict) else ''
            artist = (track.get('artist', '') or '') if isinstance(track, dict) else ''
            # 提前试探 URL（VIP/地域限制的直接跳过，不浪费入队）
            try:
                url = client.get_song_url(song_id, cookie)
            except (requests.RequestException, ValueError, TypeError):
                log.warning("Could not get Netease song URL: %s", song_id)
                skipped += 1
                continue
            if not url:
                skipped += 1
                continue
            try:
                music_wrapper = get_cached_wrapper_from_scrap(
                    type='netease', song_id=song_id, title=title, artist=artist, user=playlist_user)
                var.playlist.append(music_wrapper)
                added += 1
                if len(var.playlist) == 2:
                    should_start_download = True
                log.info("web: add Netease item to playlist: " + music_wrapper.format_debug_string())
            except Exception:
                log.exception("web: could not add Netease playlist track: %s", song_id)
                skipped += 1
    if should_start_download:
        var.bot.async_download_next()
    return added, skipped
```
注意：这里仍保留 get_song_url 试探（URL None 的跳过），但入队时传 song_id 让 NeteaseItem 自己管理下载。听歌时长累计逻辑（_add_netease_listening_time）保留。

### 3. interface.py `add_netease` 单曲分支
类似改造：试探 URL → 入队 type='netease'。

### 4. interface.py `move_item_next` rebuild
加 netease 类型分支：
```python
if item_obj.type == 'netease':
    rebuild_kwargs = {'type': 'netease', 'song_id': item_obj.song_id,
                      'title': item_obj.title, 'artist': item_obj.artist}
```

### 5. 前端
- interface.py 的 `/playlist` 渲染：RadioItem 分支（286 行）只处理 radio。需要确认 netease 类型在 playlist() 里能正常显示（title/artist）。看 273-305 行——item.format_title() 已用于 title，artist 默认 "??" 除非 FileItem 设置。NeteaseItem 需要被识别，在 interface.py playlist() 里加分支：
```python
elif isinstance(item, NeteaseItem):
    artist = item.artist
    duration = item.duration
```
（import NeteaseItem from media.netease_item）
- 前端 main.mjs 网易云搜索结果显示 title/artist 已经是分开的（song.name / song.artist），不需要改。
- 播放列表表格的 artist 列会显示 "梁博" 而非 "??"。

## 硬性约束
1. 所有现有 DOM id、data-* 属性、Jinja2 {{ tr() }} 保持不变
2. 网易云搜索/歌单/账号/置顶/听歌时长功能逻辑不能破坏
3. 播放列表刷新机制（playlist_current_index、checkForPlaylistUpdate）不动
4. 下载失败要友好处理：validate/prepare 失败 → bot 跳过该曲目并提示，不影响队列其他歌
5. **保持对 radio 类型向后兼容**：已保存的播放列表里可能还有旧 radio 类型的网易云歌曲，move_item_next 等要兼容

## 测试
```bash
python -c "import py_compile; py_compile.compile('media/netease_item.py'); py_compile.compile('interface.py'); py_compile.compile('netease_cmd.py')"
node --check web/js/main.mjs
git diff --check
```
自查：
- [ ] netease item 注册到 item_builders/item_loaders/item_id_generators
- [ ] 播放列表 artist 列显示歌手名
- [ ] 下载到本地后 is_ready 返回 True（文件存在）
- [ ] 同一首歌第二次添加不重新下载（id 稳定 → cache 命中）
- [ ] move_item_next 兼容 netease 类型
- [ ] 听歌时长累计仍工作
