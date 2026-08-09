# 任务：为 botamusique Web 界面添加网易云歌单功能

## 项目位置
- botamusique 源码：`E:/Hermes/Mumblebot/botamusique/`
- 已 git init，是有效的 git 仓库（当前分支 master）

## 背景
botamusique 是 Mumble 音乐 bot（Python），已部署在首尔服务器。网易云音乐支持已实现（netease.py 客户端 + netease_cmd.py 命令 + Web 搜索卡片）。
现在需要在 **Web 界面**上增加网易云**歌单**功能：
1. 输入歌单 ID 或链接 → 获取歌单信息（名称、封面、歌曲列表）
2. 一键播放歌单（全部加入播放队列并播放）
3. 保存歌单到本地数据库（永久保存，重启不丢）
4. 查看已保存的歌单列表，可重新播放或删除

## 现有代码结构

### netease.py（已实现的 API 客户端，位于项目根目录）
```python
class NeteaseClient:
    def __init__(self, api_base_url)
    def search(self, keywords, limit=10) -> [{id, name, artist, album, cover, duration, fee}]
    def get_song_url(self, song_id, cookie=None) -> mp3 url or None
    def search_playlist(self, keywords) -> [{id, name}]   # 已实现
    def get_playlist_tracks(self, playlist_id) -> [{id, name, artist}]  # 已实现
    def get_song_detail(self, song_id) -> {id, name, artist, album, cover, ...}
    def qr_login_start(self) -> (key, qrimg_base64)
    def qr_login_check(self, key) -> (status_code, cookie)
class NeteaseCookieManager:
    def __init__(self, cookie_file)
    def get_cookie(self) / set_cookie(cookie) / clear_cookie()
```

### 网易云 API 端点（服务器 netease-api:3000）
- 歌单详情：`GET /playlist/detail?id={playlist_id}` → `{playlist: {id, name, coverImgUrl, trackCount, playCount, description, creator: {nickname}}}`
- 歌单全部歌曲：`GET /playlist/track/all?id={playlist_id}` → `{songs: [{id, name, ar: [{name}], al: {name, picUrl}, fee}]}`
- 搜索歌单：`GET /search?keywords={kw}&type=1000` → `{result: {playlists: [{id, name, coverImgUrl, trackCount}]}}`

### interface.py（Web 后端，Flask Blueprint）
- 路由模式：`@web.route("/api/netease/search", methods=['GET'])` + `@requires_auth`
- POST 处理在 `post()` 函数，用 payload key 分发，如 `elif 'add_netease' in payload:`
- 已有 netease 导入：`from netease import NeteaseClient, NeteaseCookieManager`
- 已有 `tr_web` 导入：`from constants import tr_web`
- 数据库：`var.db`（SettingsDatabase），用法 `var.db.set(section, option, value)` / `var.db.get(section, option, fallback=...)`，值必须是字符串

### web/js/main.mjs（前端逻辑，ES module）
- 网易云搜索已有实现（约 1150-1196 行），模式：
```javascript
const neteaseSearchInput = document.getElementById('netease-search-input');
const neteaseResults = document.getElementById('netease-results');
if (neteaseSearchBtn) {
  neteaseSearchBtn.addEventListener('click', async () => {
    const response = await fetch(`/api/netease/search?keywords=${encodeURIComponent(keywords)}`);
    const data = await response.json();
    neteaseResults.innerHTML = (data.songs || []).map(...)...
    neteaseResults.querySelectorAll('.netease-add-btn').forEach((button) => {
      button.addEventListener('click', () => { request('post', {add_netease: button.dataset.id}); });
    });
  });
}
```
- `request('post', payload)` 是已有的 POST 封装函数
- 有 HTML 转义函数 `escapeNeteaseHtml(value)`（1156 行）
- 添加网易云歌曲用 `request('post', {add_netease: songId})`，后端会解析 URL 并流式播放

### web/templates/index.template.html（Jinja2 模板）
- 网易云搜索卡片在 404-422 行：
```html
<div id="add-netease" class="card" data-free-label="{{ tr('netease_free') }}" data-vip-label="{{ tr('netease_vip') }}">
    <div class="card-header"><h3 class="card-title">{{ tr('add_netease') }}</h3></div>
    <div class="card-body">
        <label for="netease-search-input">{{ tr('netease_search_label') }}</label>
        <div class="input-group mb-2">
            <input class="form-control" type="text" id="netease-search-input" placeholder="{{ tr('netease_placeholder') }}">
        </div>
        <button type="button" class="btn btn-primary" id="netease-search-btn">{{ tr('search') }}</button>
        <div id="netease-results" class="mt-3"></div>
    </div>
</div>
```

### lang/zh_CN.json 和 lang/en_US.json
- 结构：`{"cli": {...}, "web": {...}}`，Web 文案放 `web` 段
- 已有 netease 相关 key：add_netease, netease_search_label, netease_placeholder, search, netease_search_error, netease_free, netease_vip

## 需要实现的功能

### 1. 后端 API（interface.py）

**a) 获取歌单详情**（新增路由）：
```python
@web.route("/api/netease/playlist", methods=['GET'])
@requires_auth
def netease_playlist():
    # 参数：url 或 id
    # url 支持：https://music.163.com/#/playlist?id=123456 或 https://music.163.com/playlist?id=123456
    # 从 url 中正则提取 id：re.search(r'id=(\d+)', url) 或纯数字
    # 调用 client.get_playlist_tracks(id) 获取歌曲列表
    # 调用 GET /playlist/detail?id={id} 获取歌单名、封面
    # 返回 jsonify({'id': ..., 'name': ..., 'cover': ..., 'songs': [...]})
```

**b) 保存歌单**（在 post() 加分支）：
```python
elif 'save_netease_playlist' in payload:
    # payload: {save_netease_playlist: {id, name, cover, songs: [...]}}
    # 用 var.db.set('netease_playlists', str(playlist_id), json.dumps({...})) 保存
    # 返回 jsonify({'ok': True})
```

**c) 已保存歌单列表**（新增路由）：
```python
@web.route("/api/netease/playlists", methods=['GET'])
@requires_auth
def netease_playlists():
    # 从 var.db 查询所有 netease_playlists section 的记录
    # 需要遍历查询，SettingsDatabase 没有"列出全部"方法，用 sqlite 直接查：
    #   conn = sqlite3.connect(var.db.db_path) ... SELECT option, value FROM botamusique WHERE section='netease_playlists'
    # 返回 jsonify({'playlists': [{id, name, cover, count}]})
```

**d) 播放已保存歌单**（在 post() 加分支）：
```python
elif 'play_netease_playlist' in payload:
    # payload: {play_netease_playlist: playlist_id}
    # 从 var.db 读取保存的歌单 JSON
    # 逐首歌调用 get_song_url + get_cached_wrapper_from_scrap(type='radio', url=url, name=name, user=user)
    # 全部加入 var.playlist（复用现有 radio 流式播放方式，参考 add_netease 分支）
    # 如果某首歌 URL 为 None（VIP/地域限制），跳过并计数
    # 返回 jsonify({'added': n, 'skipped': m})
```

**e) 删除已保存歌单**（在 post() 加分支）：
```python
elif 'delete_netease_playlist' in payload:
    # payload: {delete_netease_playlist: playlist_id}
    # var.db 删除该记录：直接用 sqlite DELETE FROM botamusique WHERE section='netease_playlists' AND option=?
    # 返回 jsonify({'ok': True})
```

**f) 播放网易云歌单（从网络获取）**（在 post() 加分支）：
```python
elif 'play_netease_playlist_url' in payload:
    # payload: {play_netease_playlist_url: playlist_id}
    # 实时调用 get_playlist_tracks(id) 获取最新歌曲
    # 逐首解析 URL 并加入队列（同上 d）
```

### 2. 前端（index.template.html + main.mjs）

**在现有网易云搜索卡片下方新增"网易云歌单"卡片**：
```html
<div id="netease-playlist-card" class="card">
    <div class="card-header"><h3 class="card-title">{{ tr('netease_playlist') }}</h3></div>
    <div class="card-body">
        <label for="netease-playlist-input">{{ tr('netease_playlist_input_label') }}</label>
        <div class="input-group mb-2">
            <input class="form-control" type="text" id="netease-playlist-input" placeholder="{{ tr('netease_playlist_placeholder') }}">
        </div>
        <button type="button" class="btn btn-primary" id="netease-playlist-fetch-btn">{{ tr('netease_playlist_fetch') }}</button>
        <div id="netease-playlist-result" class="mt-3"></div>
        <hr>
        <h5>{{ tr('netease_saved_playlists') }}</h5>
        <div id="netease-saved-playlists" class="mt-2"></div>
    </div>
</div>
```

**JS 逻辑（main.mjs 网易云搜索代码后追加）**：

a) 获取歌单：输入框 + 按钮 → `fetch('/api/netease/playlist?url=' + encodeURIComponent(input))` → 显示歌单名、封面、歌曲列表（每首歌显示 名称-歌手 和 免费/VIP 标记），提供两个按钮：
- "播放全部" → `request('post', {play_netease_playlist_url: playlistId})`
- "保存歌单" → `request('post', {save_netease_playlist: {id, name, cover, songs}})`（songs 用当前获取的列表）

b) 已保存歌单列表：页面加载时 `fetch('/api/netease/playlists')` → 每个歌单显示名称 + 歌曲数 + "播放"按钮（`request('post', {play_netease_playlist: id})`）+ "删除"按钮（`request('post', {delete_netease_playlist: id})` + 刷新列表）

c) 保存成功后刷新已保存歌单列表

### 3. 语言文件（zh_CN.json + en_US.json）

`web` 段新增 key：
```
netease_playlist: 网易云歌单 / Netease Playlist
netease_playlist_input_label: 输入歌单链接或ID / Enter playlist URL or ID
netease_playlist_placeholder: 歌单链接或ID... / Playlist URL or ID...
netease_playlist_fetch: 获取歌单 / Fetch Playlist
netease_saved_playlists: 已保存的歌单 / Saved Playlists
netease_playlist_play_all: 播放全部 / Play All
netease_playlist_save: 保存歌单 / Save Playlist
netease_playlist_play: 播放 / Play
netease_playlist_delete: 删除 / Delete
netease_playlist_no_result: 未找到歌单 / Playlist not found
netease_playlist_error: 获取歌单失败 / Failed to fetch playlist
netease_playlist_saved: 歌单已保存 / Playlist saved
netease_playlist_deleted: 歌单已删除 / Playlist deleted
netease_playlist_added: 已添加 {count} 首歌曲 / Added {count} songs
netease_playlist_empty: 没有已保存的歌单 / No saved playlists
```

### 4. 参考代码

添加网易云歌曲到播放队列（现有 add_netease 分支，注意用 radio 类型流式播放）：
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
    except (requests.RequestException, ValueError, TypeError):
        log.exception("web: could not get Netease song URL")
        abort(502)
    if not url:
        abort(400)
    music_wrapper = get_cached_wrapper_from_scrap(type='radio', url=url, name=name, user=user)
    var.playlist.append(music_wrapper)
    log.info("web: add Netease item to playlist: " + music_wrapper.format_debug_string())
    if len(var.playlist) == 2:
        var.bot.async_download_next()
```

注意：歌单可能有很多首歌，逐首处理时：
- 每首歌先 `get_song_url(song_id, cookie)` 拿 URL
- URL 为 None 的跳过（VIP 或地域限制），统计 skipped 数
- 有 URL 的用 `type='radio'` 加入队列
- 如果 `len(var.playlist) == 2` 只触发一次 `async_download_next()`

## 编码要求
1. 代码风格跟现有代码一致（Python 4 空格缩进，函数签名风格一致）
2. 所有用户可见消息用 tr() / tr_web() 翻译函数
3. 前端 HTML 拼接必须用 escapeNeteaseHtml() 转义（防 XSS）
4. 歌单歌曲列表可能很长（几百首），后端逐首解析 URL 时如果太多就分批，每批 50 首，避免请求超时
5. 保存的歌单 JSON 包含：{id, name, cover, saved_at, songs: [{id, name, artist}]}
6. 播放已保存歌单时**重新**解析 URL（旧的 URL 20 分钟就过期，不能存 URL 只存歌曲 ID）
7. 不要破坏现有功能
8. 参考 netease_cmd.py 的 _play_or_add_song 逻辑（cmd_yun_gedan 已实现歌单命令，可参考其逐首解析方式）

## 测试
完成后做语法检查：
```bash
python -c "import py_compile; py_compile.compile('interface.py')"
node --check web/js/main.mjs
```
以及 `git diff --check` 确保无格式问题。
