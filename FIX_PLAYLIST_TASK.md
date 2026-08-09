# 任务：修复播放列表刷新死循环 + 调整网易云模块布局 + 歌单播放覆盖列表

## 项目位置
- botamusique 源码：`E:/Hermes/Mumblebot/botamusique/`
- git 仓库，当前分支 master

## 背景
上次实现了网易云歌单 Web 功能（获取/播放/保存/删除），部署后发现 3 个问题要修复。

## 问题 1：播放列表一直在刷新（死循环）

### 根因分析
前端 `web/js/main.mjs` 的 `request()` 函数（约 98-120 行）：
```javascript
function request(_url, _data, refresh = false) {
  console.log(_data);
  return $.ajax({
    type: 'POST',
    url: _url,
    data: _data,
    statusCode: {
      200: function(data) {
        if (data.ver !== playlist_ver) {
          checkForPlaylistUpdate();
        }
        ...
```
- 普通操作（add_netease 等）后端返回 `{ver, current_index, ...}`，`data.ver` 有值
- **但歌单操作**（play_netease_playlist / play_netease_playlist_url）后端返回 `{added, skipped}`，**没有 ver 字段** → `undefined !== playlist_ver` 恒为 true → 每次调用都触发 `checkForPlaylistUpdate()` → 里面又 POST /post → 返回 `{ver: N}` → `N !== playlist_ver` → 调 `updatePlaylist()` 重渲染整个表格 → 然后又有人触发 request → 死循环，播放列表不停刷新闪烁

### 修复方案
1. **前端 `request()`**：statusCode 200 回调里加守卫，只有 `typeof data.ver === 'number'` 时才做 ver 比较：
```javascript
200: function(data) {
  if (typeof data.ver === 'number' && data.ver !== playlist_ver) {
    checkForPlaylistUpdate();
  }
  if (typeof data.ver === 'number') {
    updateControls(data.empty, data.play, data.mode, data.volume);
    updatePlayerPlayhead(data.playhead);
  }
},
```
2. **歌单播放按钮的 `.done()` 回调**：播放歌单成功后（added/skipped 返回），需要**主动手动刷新一次**播放列表（因为 ver 会变，但 checkForPlaylistUpdate 不再被误触发）。在 `.done()` 里调用：
```javascript
request('post', {play_netease_playlist_url: playlist.id}).done((data) => {
  // 手动同步播放列表状态
  playlist_ver = -1;  // 强制下次检查更新
  checkForPlaylistUpdate();
  // ... 显示 added 提示
});
```
或者更直接：播放歌单成功后重置 `playlist_ver = 0; playlist_range_from = 0; playlist_range_to = 0; updatePlaylist();`（但要小心 updatePlaylist 里也有 ver 检查，直接调用 updatePlaylist() 即可）

3. 检查 `checkForPlaylistUpdate()` 本身：它 POST 到 'post' 空 body，如果返回的 `data.ver !== playlist_ver` 会调 updatePlaylist。这是正常机制，保留。但要确认 `playlist_ver` 在 updatePlaylist 后是否正确更新（`displayPlaylist` 回调里应该有 `playlist_ver = data.ver`，检查一下，如果没有就补上，否则即使修复了 request 的守卫，checkForPlaylistUpdate 内部还是会死循环——因为每次 updatePlaylist 后 playlist_ver 没同步，下一次 checkForPlaylistUpdate 又发现 ver 不同又刷新）

### 关键检查点
- `displayPlaylist(data)` 函数（约 160-235 行）：确认它设置了 `playlist_ver = data.ver`
- `checkForPlaylistUpdate()` 里：`playlist_ver = data.ver` 只在 272 行更新，但那是 checkForPlaylistUpdate 自己的回调。displayPlaylist 里也要更新 playlist_ver
- `updateControls()` 和 `updatePlayerPlayhead()` 被调用时 data 里要有 ver（否则旧代码可能报错）——注意歌单响应 {added, skipped} 没有这些字段，所以守卫必须包住这两个调用

## 问题 2：网易云模块布局调整

### 当前页面结构（web/templates/index.template.html）
```
[main id="playlist"]      ← 播放列表区域（约 150-368 行）
<div class="container mb-5">
  <div class="card-deck">
    [add-music-url]        ← URL 卡片（373-386 行）
    [add-radio-url]        ← 电台卡片（387-400 行）
  </div>
</div>
<div class="container mb-5">
  <div class="card-deck">
    [add-netease]          ← 网易云搜索卡片（406-420 行）
  </div>
</div>
<div class="container mb-5">
  [netease-playlist-card]  ← 网易云歌单卡片（424-455 行）
</div>
```

### 目标布局
把**网易云搜索卡片（add-netease）**和**网易云歌单卡片（netease-playlist-card）**两个模块上移到**播放列表区域（main#playlist）下面**，即放在 URL 卡片和电台卡片**之前**：

```
[main id="playlist"]      ← 播放列表区域
[add-netease]            ← 网易云搜索卡片（移到这）
[netease-playlist-card]  ← 网易云歌单卡片（移到这）
[add-music-url]          ← URL 卡片（原来的）
[add-radio-url]          ← 电台卡片（原来的）
```

具体操作：把 `add-netease` 的整个 container 和 `netease-playlist-card` 的整个 container 移到 `main#playlist` 结束标签之后、第一个 `card-deck`（URL/电台）之前。

注意：
- 网易云搜索和歌单可以并排放一个 card-deck（如果宽度允许），或者各自独立 container。建议把两个网易云卡片放一个 `card-deck` 里并排（跟 URL/电台的并排风格一致）
- 保持所有 `data-*` 属性和 id 不变（JS 依赖它们）
- 保持 Jinja2 `{{ tr('...') }}` 语法不变

## 问题 3：播放歌单时直接覆盖整个播放列表

### 当前行为
`interface.py` 的 `_add_netease_tracks()`（约 375-415 行）用 `var.playlist.append()` **追加**到现有播放列表尾部。

### 目标行为
播放歌单（play_netease_playlist 或 play_netease_playlist_url）时，**先清空整个播放列表**，再加入歌单歌曲。

### 修改方案
在 `interface.py` 的 `play_netease_playlist` 分支里，调用 `_add_netease_tracks()` **之前**先清空：

```python
elif 'play_netease_playlist' in payload or 'play_netease_playlist_url' in payload:
    playlist_id = payload.get('play_netease_playlist') or payload.get('play_netease_playlist_url')
    playlist_id = _extract_netease_playlist_id(playlist_id)
    if not playlist_id:
        abort(400)
    try:
        client, cookie = _get_netease_client_and_cookie()
        if 'play_netease_playlist' in payload:
            saved_value = var.db.get('netease_playlists', playlist_id, fallback=None)
            if not saved_value:
                return jsonify({'error': tr_web('netease_playlist_no_result')}), 404
            saved_playlist = json.loads(saved_value)
            tracks = saved_playlist.get('songs') or []
        else:
            tracks = client.get_playlist_tracks(playlist_id)
        # 覆盖模式：先清空播放列表
        var.playlist.clear()
        added, skipped = _add_netease_tracks(client, cookie, tracks, user)
    ...
```

注意：
- `var.playlist.clear()` 会释放缓存并重置 current_index，是安全的（media/playlist.py 191-197 行）
- 清空后 `_add_netease_tracks` 里 `len(var.playlist) == 2` 的下载触发逻辑仍有效（第一条加入时 len=1，第二条 len=2 触发）
- 前端"播放全部"按钮的提示文案可以改成"已覆盖播放列表并添加 N 首歌曲"（如果需要，在 zh_CN/en_US 加 key 或复用现有）

## 需要修改的文件
1. `web/js/main.mjs` — 修复 request() 守卫 + 歌单播放后手动刷新 + 确认 displayPlaylist 更新 playlist_ver
2. `web/templates/index.template.html` — 调整卡片顺序
3. `interface.py` — 播放歌单前 clear()
4. `lang/zh_CN.json` / `lang/en_US.json` — 如有新文案

## 编码要求
1. 保持代码风格一致
2. 不破坏现有功能（网易云搜索、歌单保存/删除、普通 URL/电台添加）
3. 前端 HTML 转义继续用 escapeNeteaseHtml()
4. 注意 main.mjs 里 `request()` 是全局函数，其他调用点可能依赖它返回 $.ajax Promise（.done()），改动时不要破坏

## 测试
```bash
python -c "import py_compile; py_compile.compile('interface.py')"
node --check web/js/main.mjs
git diff --check
```
重点自查：播放列表刷新死循环是否真的修复（request 守卫 + playlist_ver 同步两点都要做）。
