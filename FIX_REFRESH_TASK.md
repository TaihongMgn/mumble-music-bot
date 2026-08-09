# 任务：修复播放列表持续刷新（current_index 死循环）+ 删除封面元素 + 网易云账号/听歌时长模块

## 项目位置
- botamusique 源码：`E:/Hermes/Mumblebot/botamusique/`
- git 仓库，当前分支 master

## 问题 1：播放列表还在一直刷新（真正的死循环）

### 完整根因（上次只修了一半）
前端 `web/js/main.mjs`：

**上次修复**：`request()` 的 statusCode 200 加了 `typeof data.ver === 'number'` 守卫，修掉了 ver 字段缺失导致的死循环。**但还有第二条死循环没修**。

**本次根因**：`setInterval(checkForPlaylistUpdate, 3000)`（约 1481 行）每 3 秒轮询一次。`checkForPlaylistUpdate()`（约 270 行）里：
```javascript
if (data.current_index !== playlist_current_index) {
  if (data.current_index !== -1) {
    if ((data.current_index > playlist_range_to || data.current_index < playlist_range_from)) {
      playlist_range_from = 0;
      playlist_range_to = 0;
      updatePlaylist();
    } else {
      playlist_current_index = data.current_index;
      ...
```
- 播放中 `data.current_index` 一直前进（0 → 1 → 2 ...）
- `playlist_current_index` 初始为 0
- 当 current_index 超出显示范围（默认显示 11 条）→ `updatePlaylist()` → 重新渲染整表
- **但 `displayPlaylist(data)`（约 160-215 行）渲染完成后没有更新 `playlist_current_index = data.current_index`**
- 下次轮询：current_index 又前进且 `!== playlist_current_index`（仍是旧值）→ 又超范围 → 又 updatePlaylist → **无限循环，播放列表不停刷新闪烁**

### 修复方案
**在 `displayPlaylist(data)` 里（约 210 行 `displayActiveItem(data.current_index)` 附近）加一行**：
```javascript
playlist_current_index = data.current_index;
```
这样每次整表渲染后 current_index 被同步，下次轮询不再触发刷新。

**同时检查 `checkForPlaylistUpdate()` 的 if 分支**（超范围走 updatePlaylist 的那支）也补上 `playlist_current_index = data.current_index;`，双保险。

### 自查要求
模拟轮询场景：
1. 播放中 current_index 前进
2. checkForPlaylistUpdate 触发 → current_index 超范围 → updatePlaylist → displayPlaylist 更新 playlist_current_index
3. 下一次轮询 current_index 已同步 → 不再触发 updatePlaylist
必须确认这个循环被彻底打断。

## 问题 2：删除所有歌曲封面图片元素并重新排版

### 范围
**a) 播放列表表格（main.mjs 的 addPlaylistItem + index.template.html）**
- 每行歌曲有封面缩略图 `<img class="playlist-item-thumbnail">`（80px）
- 删除表格里的封面列/缩略图，让每行更紧凑：标题 + 歌手 + 类型 + 操作按钮
- 检查模板里 playlist 表头（Thumbnail/封面列）一并删除

**b) 网易云搜索卡片（netease-results）**
- 每首歌显示 `<img src="${song.cover}">` 40x40
- 删除封面图片，只留文字：歌曲名 - 歌手 + 免费/VIP 标记 + 添加按钮

**c) 网易云歌单卡片**
- 歌单封面（playlist.cover 64x64）保留还是删除？用户说"所有歌曲的封面"，歌单封面是歌单本身的封面，**保留歌单封面**（它是歌单身份标识）
- 但歌单歌曲列表（neteasePlaylistResult 的 <ol>）本身没有单曲封面，不需要动

**d) 播放器 toast（playerArtwork / playerArtworkIdle）**
- 播放器右下角迷你条的封面，**保留**（这是正在播放的显示，不算列表里的封面元素）

### 排版要求
删除封面后让布局更紧凑美观：
- 播放列表每行：编号 + 标题（粗体）+ 歌手 + 类型徽章 + 右侧操作按钮（播放/删除/标签）
- 网易云搜索每行：歌曲名（粗体）- 歌手 + 免费/VIP 小字 + 右侧 + 按钮
- 保持 Bootstrap 的 d-flex / align-items-center 风格
- 表格列宽要重新分配（原来封面列空出来的宽度给标题列）

## 问题 3：网易云歌单下方新增"网易云账号 + 听歌时长"模块

### 需求
在 `netease-playlist-card`（网易云歌单卡片）**下面**新增一个卡片，显示：
1. **当前登录的网易云账号昵称**（如果登录了）
2. **累计听歌时长**（bot 播放网易云歌曲的累计时长）
3. 未登录时显示"未登录"提示 + 提示用 !yun login 登录

### 后端实现

**a) 获取账号信息（interface.py 新增路由）**
```python
@web.route("/api/netease/account", methods=['GET'])
@requires_auth
def netease_account():
    # 读 cookie（NeteaseCookieManager）
    # 有 cookie：调网易云 API /login/status 或 /user/account 获取昵称
    #   注意：netease.py 需要新增方法 user_account(cookie) 或 login_status(cookie)
    # 无 cookie：返回 {'logged_in': False}
    # 返回 {'logged_in': True, 'nickname': 'xxx', 'avatar': 'url', 'level': n}
```

**netease.py 新增方法**：
```python
def login_status(self, cookie=None):
    # GET /login/status?cookie=xxx 或带 cookie header
    # 返回 {logged_in: bool, profile: {nickname, avatarUrl, userId, ...}} 或 None
```
如果 /login/status 不可用，试 `/user/account`。参考 netease-api 文档：
- `GET /login/status` → `{data: {code: 200, account: {id}, profile: {nickname, avatarUrl}}}`（需要带 cookie）
- 如果带 cookie 参数不行，就用 `cookie` 查询参数

**b) 听歌时长统计（interface.py + mumbleBot.py）**

思路：网易云歌曲每次**成功解析到 URL 并入队/播放**时，把歌曲时长累加到数据库。

实现方式（简单可靠）：
- 在 `_add_netease_tracks()` 和 `add_netease` 分支里，每首歌获取到 URL 时，顺便用 `client.get_song_detail(song_id)` 拿时长（duration 毫秒），累加到 `var.db` 的 `netease_listening_time`（秒）
- 或者更简单：因为 radio 流式播放拿不到播放完成事件，就用"成功入队即累计"的方式（点播即计入）
- 存储：`var.db.set('netease', 'total_listening_seconds', str(total))`
- 读取：`var.db.get('netease', 'total_listening_seconds', fallback='0')`

**c) 账号 + 时长接口合并**：`/api/netease/account` 一次返回两个数据：
```python
return jsonify({
    'logged_in': bool,
    'nickname': str,
    'avatar': str or None,
    'listening_seconds': int,   # 累计听歌秒数
    'listening_hours': float,   # 换算成小时，保留1位小数
})
```

### 前端实现（main.mjs + index.template.html）

**HTML（netease-playlist-card 之后新增）**：
```html
<div id="netease-account-card" class="card">
    <div class="card-header">
        <h3 class="card-title">{{ tr('netease_account') }}</h3>
    </div>
    <div class="card-body" id="netease-account-body">
        <!-- JS 填充 -->
    </div>
</div>
```

**JS（loadNeteaseAccount 函数）**：
```javascript
async function loadNeteaseAccount() {
  const response = await fetch('/api/netease/account');
  const data = await response.json();
  // data.logged_in: 显示头像(如果有) + 昵称 + 听歌时长
  // 未登录: 显示"未登录" + 提示 !yun login
  // 听歌时长: 显示 "累计听歌 X.X 小时" 或 "X 分钟"
}
// 页面加载时调用 + 每次获取歌单/播放歌单后刷新
```

### 语言文件（zh_CN.json / en_US.json web 段）
新增：
```
netease_account: 网易云账号 / Netease Account
netease_not_logged_in: 未登录，在 Mumble 里发送 !yun login 扫码登录 / Not logged in. Use !yun login in Mumble to scan QR code
netease_listening_time: 累计听歌 {hours} 小时 / Total listening time: {hours} hours
netease_nickname: 账号：{name} / Account: {name}
```

## 需要修改的文件
1. `web/js/main.mjs` — displayPlaylist 补 playlist_current_index 同步；删除封面元素；新增账号模块 JS
2. `web/templates/index.template.html` — 删除封面列；新增账号卡片
3. `interface.py` — 新增 /api/netease/account 路由；听歌时长累计
4. `netease.py` — 新增 login_status / user_account 方法
5. `lang/zh_CN.json` / `lang/en_US.json` — 新文案

## 编码要求
1. 保持代码风格一致（4 空格缩进、函数签名风格一致）
2. 前端 HTML 拼接必须用 escapeNeteaseHtml() 转义
3. 不破坏现有功能（搜索、歌单获取/播放/保存/删除、URL/电台）
4. 听歌时长累计逻辑要轻量（不能因为统计拖慢入队速度；get_song_detail 可以只在批量入队时调用，或者干脆不用 detail——如果 song 数据里已带 duration 就用自带的，netease.py 的 _song() 已返回 duration 字段，get_playlist_tracks 也返回 duration，直接累加即可，不要额外 API 调用！）
5. 注意：get_playlist_tracks 返回的歌曲带 duration（毫秒），_song() 里已有 duration 字段。累加时毫秒转秒：duration_ms / 1000

## 测试
```bash
python -c "import py_compile; py_compile.compile('interface.py'); py_compile.compile('netease.py')"
node --check web/js/main.mjs
git diff --check
```
重点自查：
1. displayPlaylist 里 playlist_current_index 已同步 → 轮询不再触发整表刷新
2. 删除封面后页面排版正常（无残留的 img 引用导致 404）
3. 账号模块接口和前端都能工作
