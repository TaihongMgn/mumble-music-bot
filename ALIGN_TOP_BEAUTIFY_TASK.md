# 任务：卡片对齐修复 + 置顶按钮 + 界面美化

## 项目位置
- botamusique 源码：`E:/Hermes/Mumblebot/botamusique/`
- git 仓库，当前分支 master

## 改动 1：网易云视图卡片对齐（根因已定位）

### 现状
`web/templates/index.template.html` 的 `#view-netease` 里，搜索卡片外层残留 `card-deck`：
```html
<div id="view-netease" class="app-view">
    <div class="netease-card-wrap">
        <div class="card-deck">          ← 问题在这
            <div id="add-netease" class="card" ...>
                ...
            </div>
        </div>
    </div>
    <div class="netease-card-wrap">
        <div id="netease-playlist-card" class="card" ...>...</div>
    </div>
    <div class="netease-card-wrap">
        <div id="netease-account-card" class="card" ...>...</div>
    </div>
    ...
</div>
```

Bootstrap `card-deck` 有 `margin-left: -15px; margin-right: -15px`，导致搜索卡片实际渲染比歌单/账号卡片宽 30px、左偏 15px（实测：搜索卡片 left=265 width=1171，歌单/账号 left=280 width=1141）。

### 修复
把搜索卡片外面的 `<div class="card-deck">` 层删掉，让它直接成为 `netease-card-wrap` 的子元素（和其他两个卡片一致）：
```html
<div class="netease-card-wrap">
    <div id="add-netease" class="card" ...>...</div>
</div>
```
保持 `add-netease` 所有 id 和 data-* 属性不变。

同时检查 `web/sass/main.scss` 里 `#view-netease .card-deck` 相关规则（如果有）清理掉。

## 改动 2：播放列表列重排 + 置顶按钮

### 现状
播放列表表格列：编号 | 标题(含歌手/标签) | URL/路径 | 操作（播放按钮 + 删除按钮）

### 目标
1. **URL/路径列移到最右边**（在操作列之后）：编号 | 标题 | 操作 | URL/路径
2. **操作栏的"播放"按钮换成"置顶"按钮**：
   - 图标：`fa-arrow-up` 或 `fa-level-up-alt`（FontAwesome）
   - 点击后：把该歌曲**移动到当前播放歌曲的后面**（插到 current_index + 1 的位置），即"下一首播放"效果
   - 播放列表重新渲染后能看到歌曲出现在当前播放歌曲下一行
3. 删除按钮保留

### 后端实现（interface.py 的 post() 加分支）
```python
elif 'move_item_next' in payload:
    index = int(payload['move_item_next'])
    # 校验 index 有效
    if 0 <= index < len(var.playlist):
        current = var.playlist.current_index
        if index != current and index != current + 1:
            item = var.playlist[index]
            var.playlist.remove(index)
            # remove 后如果 index <= current，current 会 -1，需要重新定位
            # 目标插入位置：当前播放歌曲后面
            target = var.playlist.current_index + 1
            # 如果 remove 导致 current_index 变化，调整 target
            var.playlist.insert(target, item)
```
注意：`var.playlist.remove(index)` 会更新 current_index（如果删除位置在 current 之前）。处理逻辑：
- 先拿到 item = var.playlist[index]
- 如果 index < var.playlist.current_index：先记 current = var.playlist.current_index，remove 后 current 变为 current-1，插入位置 = current（即原 current_index，等价于新的 current_index + 1）
- 如果 index > var.playlist.current_index：remove 不影响 current，插入位置 = current_index + 1
- 插入后 `var.bot.interrupt()`（如果正在播放，通知刷新）
- 返回 jsonify 正常响应

可以参考现有 `add_item_next` 分支（约 363-369 行）的写法：
```python
elif 'add_item_next' in payload:
    music_wrapper = get_cached_wrapper_by_id(payload['add_item_next'], user)
    if music_wrapper:
        var.playlist.insert(var.playlist.current_index + 1, music_wrapper)
```

### 前端实现（web/js/main.mjs + index.template.html）
- 表格表头顺序调整：`#` | 标题 | 操作 | URL/路径
- 操作栏按钮：置顶按钮（fa-arrow-up）+ 删除按钮（fa-trash-alt）
- 绑定时用 `request('post', {move_item_next: index})`（index 从行号获取，参考现有 play_music 的获取方式）
- main.mjs 里现有 `bindPlaylistEvent()` 里 `.playlist-item-play` 的绑定改为 `.playlist-item-top`（新类名），触发放置顶
- 保留 `.playlist-item-trash` 删除逻辑不变

## 改动 3：界面美化 + 矢量图标

在现有基础上适度美化，不改变布局骨架：

### 3a. 图标增强（FontAwesome 已引入）
`web/js/app.mjs` 的 library.add 已有：faList, faMusic, faFolder, faUpload, faPlay, faPause, faFastForward, faTrashAlt, faEdit, faVolumeUp/Down, faLightbulb, faRandom, faRedo, faTasks, faPlus, faCheck, faDownload, faSyncAlt, faFileAlt, faPlayCircle, faTimes, faTimesCircle

需要补充导入的图标（如需要）：
- `faListMusic`（播放列表工具栏）
- `faSortDown` / `faCaretDown`（下拉指示）
- `faHeart` / `faStar`（收藏/歌单）
- `faHeadphones`（听歌时长）
- `faUserCircle` / `faUser`（账号）
- `faSignInAlt`（登录提示）
- `faClock`（时长）
- `faChartBar`（统计）
- `faPlayCircle`（已导入）

### 3b. 具体美化点
1. **侧边栏**：导航项加图标（已有），hover 效果增强（左侧亮条指示当前激活项）：
```scss
.sidebar .nav-link.active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 8px;
    bottom: 8px;
    width: 3px;
    border-radius: 3px;
    background: #4da3ff;
}
.sidebar .nav-link { position: relative; }
```
2. **播放列表工具栏**：播放/暂停/下一首按钮用圆形按钮，模式下拉加图标指示
3. **卡片**：header 加图标（网易云音乐卡片加 faMusic，歌单卡片加 faListMusic，账号卡片加 faUserCircle，音乐库加 faFolder，上传加 faUpload）
4. **账号卡片内容**（renderNeteaseAccount 在 main.mjs）：昵称前加 faUserCircle 图标，听歌时长前加 faHeadphones 或 faClock 图标，未登录提示加 faSignInAlt 图标
5. **网易云搜索结果**（main.mjs renderNeteaseSearch）：每行加 faMusic 图标（歌曲图标），VIP/免费标签用不同颜色（免费=绿色 badge，VIP=金色 badge）
6. **按钮 hover 效果**：全局按钮轻微 transform 缩放（transition）
7. **表格行 hover**：播放列表行 hover 时背景色变化（Bootstrap table-hover 已有，可以加强对比度）
8. **空状态**：播放列表空/无搜索结果时用图标（已有 empty_box.svg，可以保留）

### 3c. 注意
- 图标通过 FontAwesome 的 `<i class="fas fa-xxx"></i>` 使用（webpack 会替换为 SVG）
- 新增图标必须在 app.mjs 里 import + library.add，否则不渲染
- 不要过度设计，保持整洁

## 需要修改的文件
1. `web/templates/index.template.html` — 删除 card-deck、表格列顺序、操作栏按钮
2. `web/sass/main.scss` — 美化样式
3. `web/js/main.mjs` — 置顶按钮绑定、图标、账号卡片/搜索结果图标
4. `web/js/app.mjs` — 补充图标导入
5. `interface.py` — move_item_next 分支
6. `lang/zh_CN.json` / `lang/en_US.json` — 如新增按钮文字（置顶 = "置顶" / "Top"）

## 硬性约束
- 所有 DOM id、data-* 属性、Jinja2 {{ tr() }} 保持不变
- 播放列表刷新机制（playlist_current_index 同步、checkForPlaylistUpdate）不能破坏
- 网易云搜索/歌单/账号功能逻辑不动

## 测试
```bash
python -c "import py_compile; py_compile.compile('interface.py')"
node --check web/js/main.mjs
node --check web/js/app.mjs
git diff --check
```
自查：
- [ ] card-deck 已从 view-netease 删除
- [ ] 播放列表列顺序：编号 | 标题 | 操作 | URL/路径
- [ ] 置顶按钮存在且绑定 move_item_next
- [ ] 新图标都在 app.mjs 注册
- [ ] 搜索卡片/歌单卡片/账号卡片 left 和 width 一致（对齐）
