# 账号系统 + 登录界面 + 点歌显示账号 + 防暴力 + 安全加固

## 背景
botamusique 项目（Python Flask + jQuery 前端），部署在服务器上，web 面板当前用 HTTP Basic Auth（auth_method=password，admin/BamSeoul2026!）。网易云功能已完善（netease.py / netease_cmd.py / media/netease_item.py）。

## 需求
1. 账号系统 + 登录界面：只有管理员可以注册账号和密码
2. 点歌记录：播放列表显示是哪个账号点的歌
3. 安全系统：防暴力攻击
4. Docker 融合：bot + netease-api 单容器（这个由 Hermes 处理，你不用管）

## 现有机制（必须了解）

### 认证（interface.py）
- `check_auth(username, password)` L89-104：先查 config 里的 webinterface/user+password（管理员），再查 db 里的 web_access 用户列表
- `requires_auth` L119-186：
  - `auth_method == 'password'`：HTTP Basic Auth（request.authorization）
  - `auth_method == 'token'`：token 登录
  - 已有防暴力：`bad_access_count` 按 IP 计数，超 `max_attempts`（默认10）加入 `banned_ip`，被 ban 的 IP 直接 403
- `authenticate()` L107：返回 401 + WWW-Authenticate Basic realm

### 用户管理（command.py）
- `cmd_web_user_add` L1302：`!webuseradd <name>` 添加用户到 web_access 列表（仅管理员）
- `cmd_user_password` L1288：`!password <pass>` 给当前 Mumble 用户设置密码，存 db user 表 `{'password': salted, 'salt': ...}`
- util.get_salted_password_hash / util.verify_password 已有

### 点歌 user（media/cache.py）
- `CachedItemWrapper.__init__` L141 有 `self.user = user`
- playlist API（interface.py L306-316）返回 items 时**没有** user 字段，需要加

### 前端
- web/js/main.mjs：播放列表渲染函数（约 L130-160），有 playlist-item-title / playlist-item-artist / playlist-item-path 等
- web/templates/index.template.html：播放列表 item 模板 L137-164
- 登录目前是浏览器 Basic Auth 弹窗，没有登录界面

## 需求1：登录界面 + 管理员注册

### 设计
1. **登录页面** `web/templates/login.html`（新建）：
   - 表单：用户名 + 密码 + 登录按钮
   - POST /login 提交，成功跳转主页面，失败显示错误
   - 页面样式复用现有 dark 主题（web/sass/app-dark.scss）

2. **后端登录**：
   - `POST /login`：验证用户名密码（复用 check_auth），成功存 session['user']=username，返回 redirect /；失败返回错误信息
   - `GET /logout`：清 session，跳回登录页
   - session 需要 secret key：`web.secret_key` 从 config 读（webinterface/session_secret，默认随机生成但每次启动变化会导致 session 失效，最好配置固定值）

3. **认证改造**（关键决策）：
   - 保持 auth_method=password 配置兼容性
   - 新增 auth_method=session（或扩展 password）：requires_auth 里，如果有合法 session['user'] 直接放行；否则重定向到 /login 页面
   - **注意**：现有所有 API 调用（fetch/ajax）都是 Basic Auth 无 cookie 的，改成 session 后浏览器 fetch 会自动带 cookie（同源），所以 API 不需要改 Authorization 头
   - 保留 HTTP Basic Auth 作为兼容（check_auth 逻辑不动），但要求 auth_method=session 时优先用 session

4. **管理员注册**（只有管理员能注册账号）：
   - 登录界面下方/右上角"注册新账号"入口（仅管理员可见）
   - `POST /register`：校验当前 session 是管理员（username == webinterface/user）才允许注册
   - 表单：新用户名 + 密码 + 确认密码
   - 逻辑：用户添加到 web_access 列表（同 cmd_web_user_add）+ db user 表存 salted hash
   - 用户名唯一性检查

### 翻译
lang/zh_CN.json + lang/en_US.json 加：login_title, username, password, login_btn, login_failed, logout_btn, register_btn, register_title, register_username, register_password, register_confirm, register_success, register_failed, username_exists 等

## 需求2：点歌显示账号

1. **后端**：playlist API（interface.py L306-316）items 加 `'user': item.user` 字段
2. **前端**：播放列表渲染（web/js/main.mjs 播放列表 item 部分）加显示 user：在 artist 旁边或 title 上方显示 `👤 user`，样式用 text-muted
3. **模板**：web/templates/index.template.html 播放列表 item 模板加 `<span class="playlist-item-user"></span>`

## 需求3：安全系统（已有基础 + 增强）

1. **已有**：bad_access_count 按 IP 计数，超 max_attempts 封禁（requires_auth L134-144）。保留
2. **增强**：
   - 登录失败返回统一错误信息（不暴露用户名是否存在）
   - /login 和 /register 也纳入防暴力计数（复用 bad_access_count）
   - 封禁时间：banned_ip 加时间戳，5 分钟后自动解封（或保持现状手动重启，二选一，建议自动解封）
   - 密码长度最小 6 位校验
   - 用户名只允许字母数字下划线
3. **config**：max_attempts 已有配置（webinterface/max_attempts）

## 约束
- 不要修改 media/netease_item.py、netease.py、netease_cmd.py
- 前端用 jQuery（已加载），不引入新依赖
- 所有页面/API 保持 @requires_auth 保护
- 修改后运行 `python -c "import py_compile; py_compile.compile('interface.py'); py_compile.compile('command.py')"` 和 `node --check web/js/main.mjs` 验证
- 登录页面要响应式，适配移动端

## 文件路径
- E:/Hermes/Mumblebot/botamusique/interface.py
- E:/Hermes/Mumblebot/botamusique/command.py
- E:/Hermes/Mumblebot/botamusique/web/js/main.mjs
- E:/Hermes/Mumblebot/botamusique/web/templates/index.template.html
- E:/Hermes/Mumblebot/botamusique/web/templates/login.html（新建）
- E:/Hermes/Mumblebot/botamusique/lang/zh_CN.json
- E:/Hermes/Mumblebot/botamusique/lang/en_US.json
- E:/Hermes/Mumblebot/botamusique/configuration.default.ini（加 session_secret 说明）
- E:/Hermes/Mumblebot/botamusique/util.py（如果加密码校验工具）

## 验证清单（Codex 完成后告诉我）
1. py_compile 通过
2. node --check 通过
3. login.html 存在
4. /login POST 处理存在
5. playlist API 返回 user 字段
6. 前端播放列表显示 user
