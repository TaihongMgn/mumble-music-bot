# 任务：重排 botamusique Web 前端为现代音乐播放器布局

## 项目位置
- botamusique 源码：`E:/Hermes/Mumblebot/botamusique/`
- git 仓库，当前分支 master

## 背景
当前 Web 界面是纵向堆叠的旧式布局：Header(大logo) → 播放列表表格 → 网易云搜索 → 网易云歌单 → 网易云账号 → 音乐库 → 上传 → URL/电台 → 悬浮播放器 toast。
用户要求"重新编排前端，要好看好用"。

## 目标布局（现代音乐播放器风格，类似网易云桌面版 / Spotify）

```
┌────────┬──────────────────────────────────────────────┐
│ 侧边栏  │  主内容区（根据导航切换）                       │
│ 260px  │                                               │
│        │  [播放列表视图]                               │
│ ▶ 播放  │   工具栏(播放/暂停/下一首/模式/音量/清空)       │
│ ♪ 网易云 │   歌曲表格                                   │
│   搜索  │                                               │
│   歌单  │  [网易云视图]                                 │
│   账号  │   搜索卡片 + 歌单卡片 + 账号卡片               │
│ ♫ 音乐库 │  [音乐库视图]                               │
│ ⬆ 上传  │   过滤器 + 列表 + 上传表单                    │
│        │                                               │
├────────┴──────────────────────────────────────────────┤
│ 底部播放条（fixed）：[封面][标题-歌手] [⏮⏯⏭] [进度条] [音量] │
└───────────────────────────────────────────────────────┘
```

## 布局要求

### 1. 整体框架
- 左侧固定侧边栏（宽 260px，深色背景）：垂直导航菜单，4 个导航项：
  - **播放列表**（fa-list）→ 显示播放列表视图
  - **网易云**（fa-music）→ 显示网易云搜索+歌单+账号视图
  - **音乐库**（fa-folder）→ 显示音乐库视图
  - **上传**（fa-upload）→ 显示上传视图
- 主内容区：`margin-left: 260px`，根据点击的导航项切换显示/隐藏对应视图
- 移动端（<768px）：侧边栏折叠成顶部汉堡菜单（简化：导航项变成顶部横向滚动条即可）
- 底部固定播放条：高 ~70px，`position: fixed; bottom: 0; left: 260px; right: 0`（移动端全宽）

### 2. 播放器改造（关键）
现有播放器是悬浮 toast（`#playerToast`，右上角）。改为**底部固定播放条**：
- 保留所有现有 DOM id 和 JS 绑定（main.mjs 依赖它们）：`playerToast`, `playerArtwork`, `playerArtworkIdle`, `playerTitle`, `playerArtist`, `playerBar`, `playerBarBox`, `playerPlayBtn`, `playerPauseBtn`, `playerSkipBtn`, `playerContainer`, `playerInfo`, `playerActionBox`
- 用 CSS 把 `#playerToast` 从右上角悬浮改为底部条：
  - `position: fixed; right: 0; left: 260px; bottom: 0; top: auto; width: auto; max-width: none;`
  - `#playerContainer` 改为横向 flex：封面(56px) + 信息(标题/歌手) + 控制按钮(居中) + 进度条(可伸展) + 音量
  - 需要检查 main.mjs 里 playerToast 的显示/隐藏逻辑（`$('#playerToast').show()` 之类），确保底部条始终可见或按需显示
- 主内容区底部留白 `padding-bottom: 80px` 防止被播放条遮挡

### 3. 播放列表视图
- 保留现有 `<main id="playlist">` 内的所有元素（工具栏按钮、表格、清空按钮），id 不变
- 外面包一层 `<div id="view-playlist" class="app-view">`（视图容器）
- 工具栏美化：播放/暂停/下一首按钮组 + 模式下拉 + 音量滑块放在工具栏右侧

### 4. 网易云视图
- 网易云搜索卡片、歌单卡片、账号卡片三个卡片从独立 container 挪进 `<div id="view-netease" class="app-view">`
- 保留所有 id：`add-netease`, `netease-search-input`, `netease-search-btn`, `netease-results`, `netease-playlist-card`, `netease-playlist-input`, `netease-playlist-fetch-btn`, `netease-playlist-result`, `netease-saved-playlists`, `netease-account-card`, `netease-account-body`
- 保留所有 data-* 属性（JS 依赖）
- 三个卡片纵向排列，账号卡片放最下面

### 5. 音乐库视图
- 现有的 `#forms`（music_library 标题 + 过滤器 + 列表 + 分页 + 操作按钮）挪进 `<div id="view-library" class="app-view">`
- 保留所有 id：`filter-type`, `filter-path`, `filter-dir`, `filter-keywords`, `filter-tags`, `library-group`, `library-item*`, `library-pagination`, `add-to-playlist-btn`, `library-rescan-btn`, `library-download-btn`, `deleteWarningModal`
- 上传卡片（`#upload`）也放进音乐库视图（上传是音乐库的一部分）

### 6. URL/电台卡片
- `add-music-url` 和 `add-radio-url` 两个卡片保留，放进 **网易云视图底部**（命名改为"添加链接"，放网易云卡片下面）
- 保留 id：`add-music-url`, `music-url-input`, `add-radio-url`, `radio-url-input`

### 7. Header
- 现有 `<header id="banner">` 巨大 logo（200px）改为紧凑顶栏：小 logo(32px) + 页面标题 + 主题切换按钮（`#theme-switch-btn` 挪到这）
- 保留 `#theme-switch-btn` id

### 8. 主题
- **默认使用暗色主题**：index.template.html 里 `<link id="pagestyle" href="static/css/main.css">` 默认指向暗色版本。检查 webpack 构建产物——`main.css` 和 `dark.css` 分别对应 app.scss（亮色）和 app-dark.scss（暗色）
- 主题切换 JS（main.mjs 里现有逻辑）应把 href 在两者间切换，确认现有切换逻辑工作正常
- 暗色主题下侧边栏用更深的色（如 #1a1a1a），主区用 #222，卡片 #2a2a2a

### 9. 新增 SCSS（web/sass/main.scss 追加）
```scss
// 布局
.app-view { display: none; }
.app-view.active { display: block; }
.sidebar { position: fixed; top: 0; left: 0; bottom: 0; width: 260px; ... }
.sidebar .nav-link.active { ... }
.main-content { margin-left: 260px; padding: 20px; padding-bottom: 90px; }
// 底部播放条
#playerToast { position: fixed; bottom: 0; left: 260px; right: 0; top: auto; max-width: none; ... }
// 响应式
@media (max-width: 767.98px) { .sidebar { position: static; width: 100%; height: auto; } .main-content { margin-left: 0; } #playerToast { left: 0; } }
```

### 10. 导航切换 JS（main.mjs 追加）
```javascript
// 视图切换
const navLinks = document.querySelectorAll('.sidebar .nav-link');
const appViews = document.querySelectorAll('.app-view');
function switchView(viewId) {
  appViews.forEach(v => v.classList.remove('active'));
  document.getElementById(viewId).classList.add('active');
  navLinks.forEach(l => l.classList.toggle('active', l.dataset.view === viewId));
}
navLinks.forEach(l => l.addEventListener('click', () => switchView(l.dataset.view)));
// 默认显示播放列表视图
switchView('view-playlist');
```

## 需要修改的文件
1. `web/templates/index.template.html` — 整体重构布局
2. `web/sass/main.scss` — 新增布局样式
3. `web/js/main.mjs` — 新增视图切换逻辑；检查 playerToast 显示逻辑适配底部条；确认主题切换逻辑
4. `lang/zh_CN.json` / `lang/en_US.json` — 如有新文案（导航名等）

## 硬性约束（违反会坏）
1. **所有现有 DOM id 必须保留**（main.mjs 有 ~100 处 getElementById / $('#...') 依赖）
2. **所有 data-* 属性必须保留**（netease 卡片依赖）
3. **所有 Jinja2 {{ tr('...') }} 必须保留**（模板编译依赖）
4. **所有现有按钮的类名和点击绑定不能丢**（playlist-item-play, playlist-item-trash, library-item-add-next 等）
5. 网易云功能（搜索/歌单/账号）逻辑完全不动，只挪 HTML 位置
6. 播放列表刷新机制不能破坏（playlist_current_index 同步、checkForPlaylistUpdate 轮询）

## 编码要求
1. 代码风格与现有保持一致
2. 响应式：桌面双栏，移动端单栏
3. 暗色为主，亮色主题切换保持可用
4. 不需要动后端（interface.py / netease.py 零改动）
5. 完成所有修改后：
   - `node --check web/js/main.mjs`
   - `git diff --check`
   - 人工检查：页面里每个 id 在 main.mjs 中出现过的是否都还在 HTML 里

## 测试
```bash
node --check web/js/main.mjs
git diff --check
```
自查清单：
- [ ] main.mjs 里所有 getElementById / $('#xxx') 引用的 id 都存在于新 HTML
- [ ] 四个视图切换正常
- [ ] 播放器底部条布局正确
- [ ] 网易云搜索/歌单/账号功能 id 完整
- [ ] 音乐库功能 id 完整
- [ ] 暗色默认主题生效
