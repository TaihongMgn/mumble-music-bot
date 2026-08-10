# 网易云音乐库显示 + 登录/登出按钮

## 背景
botamusique 项目（Python Flask + jQuery 前端），已新增 netease 媒体类型（media/netease_item.py），歌曲下载到 /tmp/ 缓存。现在需要两个改进。

## 任务1：音乐库页面显示已下载的网易云歌曲

### 现状
- 音乐库页面（library view）有3个类型筛选按钮：file / url / radio（web/templates/index.template.html L284-296）
- 前端 filters 对象只有 file/url/radio（web/js/main.mjs L394-396）
- 后端 build_library_query_condition 按类型查询数据库（interface.py L833-869）
- 后端 library 查询结果：file 类型显示 path+artist，其他类型显示 url+"??"（interface.py L971-976）
- netease 类型的 item 有 path（/tmp/xxx.mp3）和 artist 字段

### 需要改动

1. **web/templates/index.template.html** L293 后面加一个 netease 筛选按钮：
```html
<label id="filter-type-netease" class="btn btn-secondary">
    <input type="checkbox" name="options">{{ tr('netease') }}
</label>
```

2. **web/js/main.mjs** L394-396 filters 对象加 netease：
```js
const filters = {
  file: $('#filter-type-file'),
  url: $('#filter-type-url'),
  radio: $('#filter-type-radio'),
  netease: $('#filter-type-netease'),
};
```

3. **interface.py** L971-976 library 查询结果，netease 类型也要显示 path+artist（和 file 一样）：
```python
if item.type in ('file', 'netease'):
    result['path'] = item.path
    result['artist'] = item.artist
else:
    result['path'] = item.url
    result['artist'] = "??"
```

4. **lang/zh_CN.json** 和 **lang/en_US.json** 确保有 `netease` 翻译键（如果没有就加：zh "网易云", en "Netease"）

## 任务2：网易云账号卡片加登录/登出按钮

### 现状
- 账号卡片在 web/templates/index.template.html L229-238
- 前端渲染逻辑在 web/js/main.mjs renderNeteaseAccount() L1231-1252
- 后端 /api/netease/account 返回 logged_in/nickname/avatar/listening_hours（interface.py L374-396）
- QR 登录流程已有（netease_cmd.py cmd_yun_login L290-324）：qr_login_start() 获取 key+qrimg_base64，保存 QR 图片，轮询 qr_login_check(key) 直到 code=803 拿到 cookie
- NeteaseCookieManager 有 set_cookie() 和 clear_cookie()（netease.py L189-204）
- 已有 /netease/qr_login.png 端点返回保存的 QR 图片（interface.py L513-520）
- QR 登录在 Mumble 端用 !yun login 触发，需要改成 Web 端也能用

### 需要改动

1. **interface.py** 新增3个 API 端点：

   a) `POST /api/netease/qr_start` - 启动 QR 登录：
   - 调用 client.qr_login_start() 获取 key + qrimg_base64
   - 保存 QR 图片到配置的路径（和 netease_cmd.py _qr_image_path() 一样）
   - 返回 `{"qr_url": "/netease/qr_login.png?t=<timestamp>", "key": key}`
   - 注意：key 存在内存变量里供后续 check 用

   b) `GET /api/netease/qr_check` - 检查登录状态：
   - 接收 `key` 参数
   - 调用 client.qr_login_check(key)
   - code=801: 等待扫码; code=802: 已扫码等待确认; code=803: 登录成功
   - code=803 时调用 cookie_manager.set_cookie(cookie) 保存 cookie
   - 返回 `{"code": code, "message": "..."}`

   c) `POST /api/netease/logout` - 登出：
   - 调用 cookie_manager.clear_cookie() 清除 cookie 文件
   - 返回 `{"success": true}`

2. **web/js/main.mjs** renderNeteaseAccount() 改造：
   - 未登录时：显示提示文字 + **"扫码登录"按钮**
   - 已登录时：显示账号信息 + **"退出登录"按钮**
   - 登录按钮点击：fetch /api/netease/qr_start -> 弹出 modal 显示 QR 图片 -> 轮询 /api/netease/qr_check -> 成功后刷新账号
   - 登出按钮点击：`confirm("确定要退出网易云登录吗？")` 二次确认 -> fetch /api/netease/logout -> 刷新账号

3. **web/templates/index.template.html** 账号卡片区域加 QR 登录 modal：
   - 可以用 Bootstrap modal，包含一个 img 标签显示 QR 图片
   - 或者用简单的弹窗/折叠区域

4. **lang/zh_CN.json** 和 **lang/en_US.json** 加翻译键：
   - `netease_login_btn`: "扫码登录" / "QR Login"
   - `netease_logout_btn`: "退出登录" / "Logout"  
   - `netease_logout_confirm`: "确定要退出网易云登录吗？" / "Are you sure to logout from Netease?"
   - `netease_qr_waiting`: "请使用网易云音乐 App 扫码" / "Scan with Netease Music app"
   - `netease_qr_scanned`: "已扫码，请在手机上确认" / "Scanned, please confirm on phone"
   - `netease_qr_expired`: "二维码已过期，请重新扫码" / "QR code expired, please retry"

## 约束
- 不要修改 media/netease_item.py（刚修好的缓存逻辑）
- 不要修改 netease.py（Client 和 CookieManager 已完善）
- 不要修改 netease_cmd.py 的 Mumble 命令逻辑
- 前端用 jQuery（已加载），不要引入新依赖
- QR 登录轮询用 setInterval，2秒一次，超时5分钟自动停止
- 所有新 API 端点加 @requires_auth
- QR 图片端点 /netease/qr_login.png 已有，不需要重复创建
- 修改后运行 `python -c "import py_compile; py_compile.compile('interface.py')"` 和 `node --check web/js/main.mjs` 验证语法

## 文件路径
- E:/Hermes/Mumblebot/botamusique/interface.py
- E:/Hermes/Mumblebot/botamusique/web/js/main.mjs
- E:/Hermes/Mumblebot/botamusique/web/templates/index.template.html
- E:/Hermes/Mumblebot/botamusique/lang/zh_CN.json
- E:/Hermes/Mumblebot/botamusique/lang/en_US.json
