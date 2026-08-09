# 任务：为 botamusique 添加网易云音乐支持

## 项目位置
- botamusique 源码：`E:/Hermes/Mumblebot/botamusique/`
- 已 git init，是有效的 git 仓库

## 背景
botamusique 是一个 Mumble 音乐 bot（Python），已部署在首尔服务器上。现在需要添加网易云音乐解析功能。
NeteaseCloudMusicApi（Node.js 服务）已部署在服务器上，地址 `http://netease-api:3000`（Docker 内部网络）。

## NeteaseCloudMusicApi 已验证可用的接口
1. **搜索歌曲**：`GET /search?keywords={关键词}&limit={数量}`
   - 返回：`{result: {songs: [{id, name, artists: [{name}], album: {name, picUrl}, duration, fee}]}}`
   - fee=0 免费, fee=1 VIP, fee=8 数字专辑

2. **获取播放URL**：`GET /song/url?id={歌曲ID}`
   - 返回：`{code: 200, data: [{id, url, br, size, type, code}]}`
   - url 可能是 null（VIP歌曲需登录cookie）
   - 带cookie：`GET /song/url?id={歌曲ID}&cookie={cookie字符串}`

3. **搜索歌单**：`GET /search?keywords={关键词}&type=1000`
   - 返回：`{result: {playlists: [{id, name, coverImgUrl}]}}`

4. **获取歌单歌曲**：`GET /playlist/track/all?id={歌单ID}`
   - 返回：`{songs: [{id, name, ar: [{name}], al: {name}}]}`

5. **歌曲详情**：`GET /song/detail?ids={歌曲ID}`
   - 返回：`{songs: [{id, name, ar: [{name}], al: {picUrl}}]}`

6. **二维码登录**：
   - `GET /login/qr/key` -> `{data: {unikey: "xxx"}}`
   - `GET /login/qr/create?key={key}&qrimg=true` -> `{data: {qrimg: "data:image/png;base64,..."}}`
   - `GET /login/qr/check?key={key}` -> `{code: 801/802/803, cookie: "..."}` (801=等待扫描, 802=已扫描等待确认, 803=登录成功)

7. **登录后获取VIP歌曲URL**：`GET /song/url?id={歌曲ID}&cookie={cookie}`

## botamusique 代码结构

### 命令系统（command.py）
- 命令注册：在 `register_all_commands(bot)` 函数中用 `bot.register_command(commands('xxx'), cmd_xxx)` 注册
- 命令函数签名：`def cmd_xxx(bot, user, text, command, parameter):`
- `parameter` 是用户输入的参数（命令后面的文本）
- `bot.send_msg(text_message, text)` 发送消息到 Mumble
- `tr('key', **kwargs)` 获取翻译文本
- 已有的 `cmd_play_url` 可以直接播放 URL：
  ```python
  def cmd_play_url(bot, user, text, command, parameter):
      url = util.get_url_from_input(parameter)
      if url:
          music_wrapper = get_cached_wrapper_from_scrap(type='url', url=url, user=user)
          var.playlist.append(music_wrapper)
          send_item_added_message(bot, music_wrapper, len(var.playlist) - 1, text)
          if len(var.playlist) == 2:
              bot.async_download_next()
  ```
- yt_search/yt_play 的模式：搜索->展示结果给用户->用户选号->播放

### 配置文件（configuration.default.ini）
- 使用 INI 格式，`[bot]`、`[server]`、`[webinterface]` 等 section
- 用户自定义配置放在 `config.ini`，只写需要改的项

### Web 接口（interface.py）
- Flask Blueprint `web`，路由用 `@web.route("/path", methods=['POST'])`
- `@requires_auth` 装饰器做认证
- `post()` 函数处理前端 POST 请求，根据 payload 里的 key 分发：
  ```python
  if 'add_url' in payload:
      music_wrapper = get_cached_wrapper_from_scrap(type='url', url=payload['add_url'], user=user)
      var.playlist.append(music_wrapper)
  elif 'add_radio' in payload:
      ...
  ```
- 新增 API 端点用 `@web.route("/api/netease/search", methods=['GET'])` 格式

### Web 前端
- 模板：`web/templates/index.template.html`（Jinja2，编译后变成 `web/templates/index.{lang}.html`）
- JS：`web/js/main.mjs`（ES module，用 webpack 编译）
- 现有 URL 输入和 Radio 输入在 HTML 里的结构（card-deck 布局）：
  ```html
  <div class="card-deck">
      <div id="add-music-url" class="card">...</div>
      <div id="add-radio-url" class="card">...</div>
  </div>
  ```
- JS 里添加 URL 的逻辑：
  ```javascript
  document.getElementById('add-music-url').querySelector('button').addEventListener('click', () => {
    request('post', {add_url: musicUrlInput.value});
    musicUrlInput.value = '';
  });
  ```

### 语言文件（lang/zh_CN.json）
- JSON 格式，`cli` key 存命令行消息，`web` key 存 Web 界面文案
- 同时更新 `lang/en_US.json`

## 需要你创建/修改的文件

### 1. 新建 `netease.py`（核心模块）
API 客户端，封装对 NeteaseCloudMusicApi 的调用：
- `class NeteaseClient`：
  - `__init__(self, api_base_url)`：初始化
  - `search(self, keywords, limit=10)` -> 返回歌曲列表 `[{id, name, artist, album, duration, fee}]`
  - `get_song_url(self, song_id, cookie=None)` -> 返回 mp3 URL 或 None
  - `search_playlist(self, keywords)` -> 返回歌单列表 `[{id, name}]`
  - `get_playlist_tracks(self, playlist_id)` -> 返回歌曲列表 `[{id, name, artist}]`
  - `get_song_detail(self, song_id)` -> 返回歌曲详情
  - `qr_login_start(self)` -> 返回 `(key, qrimg_base64)`
  - `qr_login_check(self, key)` -> 返回 `(status_code, cookie)` (801/802/803)
- `class NeteaseCookieManager`：
  - 管理登录 cookie 的持久化（读写 `config/netease_cookie.txt`）
  - `get_cookie()` / `set_cookie(cookie)` / `clear_cookie()`
- 使用 `requests` 库（已在 requirements.txt 中）

### 2. 新建 `netease_cmd.py`（命令处理）
实现以下命令（仿照 cmd_yt_search / cmd_yt_play 的模式）：

| 命令 | 功能 |
|------|------|
| `!yun play [歌名]` | 搜索并立即播放第一首 |
| `!yun add [歌名]` | 搜索并添加到播放列表 |
| `!yun search [歌名]` | 搜索并显示结果列表（用 shortlist 机制） |
| `!yun playid [id]` | 按歌曲ID直接播放 |
| `!yun addid [id]` | 按歌曲ID添加到播放列表 |
| `!yun gedan [名]` | 搜索歌单并播放 |
| `!yun gedanid [id]` | 按歌单ID播放 |
| `!yun login` | 二维码登录（在Mumble发二维码图片链接） |

关键实现要点：
- `!yun play` 和 `!yun add` 应该先搜索，取第一个结果，获取URL，用 `cmd_play_url` 播放
- `!yun search` 仿照 `cmd_yt_search`，结果存入 `song_shortlist`，用户用 `!sl` 选择
- `!yun login` 调用二维码API，将base64图片保存到 `/music/qr_login.png`，发送 Web 界面URL给用户
- 获取URL时如果有 cookie 就带上 cookie
- 如果 URL 返回 null，发送友好提示"该歌曲可能需要VIP，请先使用 !yun login 登录"

### 3. 修改 `command.py`
- 在文件顶部 import：`from netease_cmd import *`
- 在 `register_all_commands` 末尾添加注册：
  ```python
  bot.register_command('yun', cmd_yun_dispatch, access_outside_channel=True)
  ```
  或者注册每个子命令：
  ```python
  bot.register_command(commands('yun_play'), cmd_yun_play)
  bot.register_command(commands('yun_add'), cmd_yun_add)
  ...
  ```
  注意：botamusique 的命令系统用 `commands()` 函数从配置文件读取命令别名，需要先在 `configuration.default.ini` 的 `[commands]` section 添加。但也可以直接用字符串注册。

### 4. 修改 `configuration.default.ini`
- 添加 `[netease]` 配置段：
  ```ini
  [netease]
  api_url = http://netease-api:3000
  cookie_file = config/netease_cookie.txt
  qr_image_path = music/qr_login.png
  default_search_limit = 10
  ```
- 在 `[commands]` section 添加命令别名：
  ```ini
  yun_play = yplay
  yun_add = yadd
  yun_search = ysearch
  yun_playid = yplayid
  yun_addid = yaddid
  yun_gedan = ygedan
  yun_gedanid = ygedanid
  yun_login = ylogin
  ```

### 5. 修改 `interface.py`
- 添加 API 端点供前端搜索：
  ```python
  @web.route("/api/netease/search", methods=['GET'])
  @requires_auth
  def netease_search():
      keywords = request.args.get('keywords', '')
      if keywords:
          client = NeteaseClient(var.config.get('netease', 'api_url'))
          results = client.search(keywords)
          return jsonify({'songs': results})
      return jsonify({'songs': []})
  ```
- 在 `post()` 函数中添加处理 `add_netease` 的逻辑：
  ```python
  elif 'add_netease' in payload:
      song_id = payload['add_netease']
      client = NeteaseClient(var.config.get('netease', 'api_url'))
      cookie_manager = NeteaseCookieManager(var.config.get('netease', 'cookie_file'))
      url = client.get_song_url(song_id, cookie_manager.get_cookie())
      if url:
          music_wrapper = get_cached_wrapper_from_scrap(type='url', url=url, user=user)
          var.playlist.append(music_wrapper)
      else:
          abort(400)
  ```

### 6. 修改 `web/templates/index.template.html`
在 URL 和 Radio 的 card-deck 后面添加网易云搜索 card：
```html
<div id="add-netease" class="card">
    <div class="card-header">
        <h3 class="card-title">{{ tr('add_netease') }}</h3>
    </div>
    <div class="card-body">
        <label for="netease-search-input">{{ tr('netease_search_label') }}</label>
        <div class="input-group mb-2">
            <input class="form-control" type="text" id="netease-search-input" placeholder="{{ tr('netease_placeholder') }}">
        </div>
        <button type="submit" class="btn btn-primary" id="netease-search-btn">
            {{ tr('search') }}
        </button>
        <div id="netease-results" class="mt-3"></div>
    </div>
</div>
```

### 7. 修改 `web/js/main.mjs`
添加网易云搜索和添加逻辑：
```javascript
// 网易云搜索
const neteaseSearchInput = document.getElementById('netease-search-input');
const neteaseSearchBtn = document.getElementById('netease-search-btn');
const neteaseResults = document.getElementById('netease-results');

neteaseSearchBtn.addEventListener('click', async () => {
  const keywords = neteaseSearchInput.value.trim();
  if (!keywords) return;
  
  const res = await fetch(`/api/netease/search?keywords=${encodeURIComponent(keywords)}`);
  const data = await res.json();
  
  neteaseResults.innerHTML = data.songs.map((song, i) => `
    <div class="d-flex align-items-center mb-2">
      <img src="${song.cover || ''}" width="40" height="40" class="mr-2">
      <div class="flex-grow-1">
        <div>${song.name} - ${song.artist}</div>
        <small class="text-muted">${song.fee === 0 ? '免费' : 'VIP'}</small>
      </div>
      <button class="btn btn-sm btn-primary ml-2 netease-add-btn" data-id="${song.id}">+</button>
    </div>
  `).join('');
  
  document.querySelectorAll('.netease-add-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      request('post', {add_netease: btn.dataset.id});
    });
  });
});
```

### 8. 修改 `lang/zh_CN.json` 和 `lang/en_US.json`
添加翻译 key（在 `cli` 和 `web` 两个 section 都加需要的）：
```json
{
  "cli": {
    "netease_searching": "正在搜索网易云音乐...",
    "netease_no_result": "未找到相关歌曲。",
    "netease_play_error": "无法获取该歌曲的播放链接，可能需要VIP。请使用 !yun login 登录。",
    "netease_playing": "正在播放：{song} - {artist}",
    "netease_added": "已添加到播放列表：{song} - {artist}",
    "netease_login_qr": "请扫描二维码登录网易云账号（5分钟内有效）：{url}",
    "netease_login_success": "网易云账号登录成功！现在可以播放VIP歌曲了。",
    "netease_login_timeout": "登录超时，请重试。",
    "netease_login_waiting": "等待扫描登录...",
    "netease_playlist_loading": "正在加载歌单...",
    "netease_playlist_added": "已添加歌单中的 {count} 首歌曲。",
    "netease_help": "网易云音乐命令..."
  },
  "web": {
    "add_netease": "网易云音乐",
    "netease_search_label": "搜索网易云音乐",
    "netease_placeholder": "输入歌曲名或歌手名...",
    "search": "搜索"
  }
}
```

## 编码要求
1. 代码风格跟现有代码保持一致（Python: 4空格缩进，函数签名风格一致）
2. 所有用户可见的消息用 `tr()` 翻译函数
3. 错误处理要完善：API 超时、返回null、网络错误都要有友好提示
4. cookie 持久化到文件，重启后保持登录状态
5. 二维码登录是异步的：发完二维码后用后台线程轮询检查状态
6. 不要破坏现有功能
7. netease.py 和 netease_cmd.py 放在项目根目录（和 command.py 同级）

## 测试
不需要写测试。但完成后做一次语法检查：`python -c "import py_compile; py_compile.compile('netease.py'); py_compile.compile('netease_cmd.py')"`
