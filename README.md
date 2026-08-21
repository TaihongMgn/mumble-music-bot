<div align="center">
<img src="static/image/logo.png" alt="FX Music Bot" width="120px" />
<h1>FX Music Bot</h1>
<p>Mumble 音乐点播机器人 · 网易云音乐深度集成 · Web 控制面板</p>
</div>

---

基于 [botamusique](https://github.com/azlux/botamusique) 深度定制的 Mumble 音乐机器人，**单容器融合部署**（机器人 + 网易云 API 一个镜像跑完），带完整的 Web 账号系统。

## ✨ 功能亮点

- **🎵 多音乐源**：网易云音乐、喜马拉雅（链接播放/专辑）、YouTube、SoundCloud、本地文件、网络电台
- **☁️ 网易云深度集成**：
  - `!yun` 命令搜索 / 点播 / 歌单，Web 面板搜索、保存歌单
  - **下载播放模式**：歌曲先下载到本地再播放，同一首歌二次点播秒开（本地缓存命中）
  - **二维码登录**：Web 面板扫码登录账号，播放 VIP 歌曲
- **👤 Web 账号系统**：
  - 登录界面（session 认证），告别浏览器密码弹窗
  - **仅管理员可注册新账号**（Web 端账号管理页：注册 / 列表 / 删除）
  - 播放列表显示每首歌的**点歌人**（`👤 用户名`）
- **🛡️ 安全**：登录失败防暴力（同一 IP 连续失败 10 次封禁 5 分钟）、密码加密存储、密码最小 6 位
- **🎨 现代化 Web 界面**：深色主题、侧边栏导航、底部播放条（进度 / 音量 / 播放模式）、响应式适配手机

## 📦 部署（单容器）

镜像已发布到 Docker Hub：`taihong422/fx-music-bot:latest`（内含 bot + 网易云 API，supervisord 管理双进程）。

```yaml
# docker-compose.yml
services:
  fx-music-bot:
    image: taihong422/fx-music-bot:latest
    container_name: fx-music-bot
    restart: unless-stopped
    ports:
      - "127.0.0.1:8181:8181"
    environment:
      BAM_CONFIG_file: /config/config.ini
      BAM_MUSIC_DB: /config/music.db
      BAM_DB: /config/setting.db
    volumes:
      - ./config:/config
      - ./music:/music
```

```bash
mkdir -p config music
# 复制 configuration.example.ini 为 config/config.ini 并修改
docker compose up -d --pull always
```

> **完整部署教程**（含 config.ini 模板、验收清单、常见问题）见 [`deploy/`](deploy/) 目录，或直接使用 `deploy/deploy.sh` 一键脚本。

### 必须修改的配置项

| 配置 | 位置 | 说明 |
|------|------|------|
| `host` | `[server]` | Mumble 服务器地址 |
| `admin` | `[bot]` | 你的 Mumble 用户名（管理员） |
| `password` | `[webinterface]` | Web 面板管理员密码 |
| `session_secret` | `[webinterface]` | 生成：`python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `access_address` | `[webinterface]` | Web 面板公网地址（二维码从这里取） |

## 🎮 Mumble 命令

| 命令 | 功能 |
|------|------|
| `!yun play [歌名]` | 搜索并立即播放网易云歌曲 |
| `!yun add [歌名]` | 搜索并添加到播放列表 |
| `!yun search [歌名]` | 搜索显示结果，`!sl [序号]` 选择 |
| `!yun playid [id]` / `!yun addid [id]` | 按歌曲 ID 播放 / 添加 |
| `!yun gedan [歌单名]` / `!yun gedanid [id]` | 搜索 / 按 ID 播放歌单 |
| `!yun login` | 网易云二维码登录（VIP 歌曲需要） |
| `!xm <链接或ID>` | 播放喜马拉雅声音 / 整单加入专辑（`ximalaya.com/sound/xxx` 或 `/album/xxx`） |
| `!play [搜索词]` | 播放 YouTube / SoundCloud |
| `!help` | 全部命令 |
| `!duck on/off` | 说话自动降低音量开关 |

## 🌐 Web 面板

访问 `http://服务器:8181`（或反向代理域名）。

- **登录**：管理员用 config 里的 `user`/`password`；普通用户由管理员在「账号管理」页注册
- **网易云**：搜索歌曲 / 歌单 → 添加到播放列表；账号卡片扫码登录（VIP 歌曲）
- **播放列表**：每首歌显示点歌人、来源类型、可拖动排序 / 置顶 / 删除
- **音乐库**：浏览 / 上传本地音乐文件（需 config 开启 `upload_enabled`）

### 反向代理（推荐，自动 HTTPS）

```caddy
# Caddyfile
music.example.com {
    reverse_proxy 127.0.0.1:8181
}
```

## 🐳 本地构建镜像

```bash
# 需要 Docker，构建单容器融合镜像
docker build -f Dockerfile.netease -t fx-music-bot:latest .
```

## 📁 项目结构

```
├── netease.py              # 网易云 API 客户端
├── netease_cmd.py          # !yun Mumble 命令
├── media/netease_item.py   # 网易云下载播放媒体类型（缓存命中）
├── interface.py            # Web 面板 Flask 后端（账号系统/防暴力/网易云路由）
├── command.py              # Mumble 命令注册
├── web/                    # 前端（侧边栏+播放条深色界面）
├── netease-api/            # 网易云 Node API（融合进镜像）
├── Dockerfile.netease      # 单容器构建（supervisord 管双进程）
└── deploy/                 # 可移植部署包（README + 一键脚本 + agent 提示词）
```

## 📄 License

MIT（上游 botamusique 为 MIT，netease-api 为 [0525sd/neteasecloudmusicapi](https://gitlab.com/0525sd/neteasecloudmusicapi) 的 fork）
