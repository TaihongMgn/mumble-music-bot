# 任务：3 个小改动（标题改名 + 导航合并 + 卡片对齐）

## 项目位置
- botamusique 源码：`E:/Hermes/Mumblebot/botamusique/`
- git 仓库，当前分支 master

## 改动 1：标题改名
`lang/zh_CN.json` 的 web 段 `page_title` 从 `botamusique控制面板` 改为 `Ffmusicbot面板`。
`lang/en_US.json` 的 web 段 `page_title` 从 `botamusique Web Interface` 改为 `Ffmusicbot Panel`。
（注意：Jinja 模板编译后这个值会出现在 HTML 的 `<title>` 和 sidebar-brand 里）

## 改动 2：合并导航项
`web/templates/index.template.html` 的侧边栏（sidebar-nav）现在有 4 个导航项：
1. 播放列表（data-view="view-playlist"）
2. 网易云（data-view="view-netease"）
3. 音乐库（data-view="view-library"）
4. 上传（data-view="view-library" data-scroll-target="upload"）

把"音乐库"和"上传"合并成**一个**导航项：
- 删除单独的上传导航项
- 合并后的导航项：图标用 fa-folder，文字用**新的翻译 key** `nav_library_upload`（值："音乐库&上传" / "Library & Upload"），`data-view="view-library"`
- 保留上传的滚动行为：给合并后的项加 `data-scroll-target="upload"`？不行——这样每次点音乐库都滚到上传。**正确做法**：合并项不加 data-scroll-target，音乐库视图内用户自己往下滚。但如果用户希望点"音乐库&上传"能展示上传表单，可以把 upload 卡片在 view-library 里的位置调整（可选，不做也行）
- 简化为 3 个导航项

同时 `web/js/main.mjs` 里如果有对上传导航项的引用（比如高亮逻辑），检查并适配（Codex 自查：grep "scroll-target" 和 nav 相关逻辑）

新增翻译 key（zh_CN + en_US 的 web 段）：
```
nav_library_upload: 音乐库&上传 / Library & Upload
```

## 改动 3：网易云歌单卡片和账号卡片对齐
`web/templates/index.template.html` 的 `#view-netease` 视图里，卡片结构不一致导致歌单卡片和账号卡片没对齐。当前结构：
```html
<div id="view-netease" class="app-view">
    <div class="container mb-5">
        <div class="card-deck"> [搜索卡片 add-netease] </div>
    </div>
    <div class="container mb-5">
        <div id="netease-playlist-card" class="card"> ... </div>
    </div>
    <div class="container mb-5">
        <div id="netease-account-card" class="card"> ... </div>
    </div>
    <div class="container mb-5">
        <div class="card-deck"> [URL/电台卡片] </div>
    </div>
</div>
```

**统一结构**：把 `#view-netease` 里的所有卡片统一成同一种容器结构，确保对齐：
```html
<div id="view-netease" class="app-view">
    <div class="netease-card-wrap">
        [搜索卡片 add-netease]
    </div>
    <div class="netease-card-wrap">
        [歌单卡片 netease-playlist-card]
    </div>
    <div class="netease-card-wrap">
        [账号卡片 netease-account-card]
    </div>
    <div class="netease-card-wrap">
        [URL/电台卡片 - 两个可以并排]
    </div>
</div>
```
- 外层统一用 `netease-card-wrap`（新增 CSS 类，定义：margin-bottom 18px，width 100%）
- 搜索卡片、歌单卡片、账号卡片内部结构（card-header + card-body + 所有 id/data-*）不动
- URL/电台两个小卡片可以并排在一个 wrap 里（保持 card-deck 或 flex）
- `web/sass/main.scss` 新增：
```scss
#view-netease .netease-card-wrap {
    margin-bottom: 18px;
}
#view-netease .netease-card-wrap > .card {
    border-radius: 10px;
    overflow: hidden;
}
```
- 检查 `web/sass/main.scss` 现有的 `#view-netease .card-deck { display: block; }` 等规则，保持兼容或清理

## 需要修改的文件
1. `lang/zh_CN.json` — page_title 改名 + nav_library_upload
2. `lang/en_US.json` — page_title 改名 + nav_library_upload
3. `web/templates/index.template.html` — 导航合并 + 网易云视图卡片统一结构
4. `web/sass/main.scss` — netease-card-wrap 样式
5. `web/js/main.mjs` — 如有导航引用需适配（自查）

## 硬性约束
- 所有 DOM id 和 data-* 属性保持不变（JS 依赖）
- Jinja2 {{ tr('...') }} 语法保持
- 不破坏网易云搜索/歌单/账号功能

## 测试
```bash
node --check web/js/main.mjs
git diff --check
```
自查：grep 确认 nav_upload 相关旧引用已清理、netease-card-wrap 存在于 HTML 和 SCSS。
