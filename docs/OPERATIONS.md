# 部署与运维手册

本文档用于生产环境部署和日常维护。项目需要同时运行两个常驻进程，并建议配置一个定时清理任务：

- `api_server.py`：Flask API，负责网页请求、SSE 推送和媒体代理。
- `tg_bot.py`：Telegram Bot，负责管理命令和客服回复。
- `python -m api.cleanup_worker`：定时执行过期会话和媒体清理，避免普通 HTTP 请求被清理任务拖慢。

> ⚠️ **必须配置清理 timer**：API 请求链路已经不再触发清理，如果 `webchat-cleanup.timer` 未启用，过期会话和媒体文件会**永久堆积**，最终撑爆磁盘。详见下文「定时清理任务」一节。

## 部署前准备

准备以下资源：

- Python 3.11。
- 一个 Telegram Bot Token。
- 一个已开启话题功能的 Telegram 超级群。
- 服务器能访问 Telegram Bot API。
- Nginx 或其他反向代理。
- 可写的客服媒体目录。默认值为项目根目录 `media/`；如需覆盖，可通过 `WEBCHAT_MEDIA_ROOT` 环境变量指向其他可写目录。

建议服务运行用户使用 `www`，并让该用户拥有项目目录、`data/` 目录、数据库文件和媒体目录的读写权限。

前后端分离部署（例如后端在新加坡、前端 Nginx 在香港）目前仍把媒体落在后端项目根目录 `media/`，访客通过 Flask `GET /api/media/<file_id>` 取文件。把媒体迁到前端机器（远程挂载、HTTPS 推送或对象存储）是后续独立优化项，本手册暂不展开。

## 安装依赖

进入项目目录：

```bash
cd /www/wwwroot/webchat
```

创建虚拟环境并安装依赖：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

创建数据目录（数据库和默认媒体目录都在 `data/` 下）：

```bash
mkdir -p /www/wwwroot/webchat/media
chown -R www:www /www/wwwroot/webchat
```

如果生产环境希望把媒体目录放到其他位置，可以单独建一个目录并通过环境变量 `WEBCHAT_MEDIA_ROOT` 覆盖默认值：

```bash
mkdir -p /www/wwwroot/webchat/media
chown -R www:www /www/wwwroot/webchat/media
# 在 systemd unit 或 shell profile 中：
# export WEBCHAT_MEDIA_ROOT=/www/wwwroot/webchat/media
```

### 从旧版本迁移

旧版本把 `webchat.db` 直接放在项目根目录。升级到分层目录结构后，默认数据库路径变成 `data/webchat.db`。一次性迁移：

```bash
systemctl stop webchat-api webchat-bot
mkdir -p data
mv webchat.db data/webchat.db
# 如果旧版本媒体也放在项目内，可一并搬迁
[ -d data/media ] && mv data/media media
systemctl start webchat-api webchat-bot
```

若不想搬动现有数据，也可以在 `config.py` 里把 `DB_PATH` 显式写回旧路径，或者通过环境变量覆盖。

## 修改配置

编辑 `config.py`，确认以下配置：

| 配置项 | 建议 |
| --- | --- |
| `WEBCHAT_BOT_TOKEN` | 通过环境变量提供主 Telegram Bot Token，不写入 `config.py`。 |
| `WEBCHAT_TOKEN_KEY` | 必填。客户侧 Bot Token 的落盘加密密钥，使用 `Fernet.generate_key()` 生成并固定保存。 |
| `WEBCHAT_INTERNAL_TOKEN` | 必填。`/internal/notify` 的 Bearer Token，API 服务和 Bot 服务必须一致。 |
| `WEBCHAT_ADMIN_IDS` | 管理员 Telegram 用户 ID，逗号分隔，例如 `1316912879,8257830578`。 |
| `API_HOST` | 生产环境建议保持 `127.0.0.1`。 |
| `API_PORT` | 默认 `5055`。 |
| `DB_PATH` | 默认 `data/webchat.db`。 |
| `WEBCHAT_MEDIA_ROOT` | 客服媒体落盘目录，默认项目根目录 `media/`，可通过环境变量覆盖到其他可写目录。 |
| `SESSION_TTL_SECONDS` | 会话创建超过该时间后自动删除，默认约 2 个月。 |
| `SESSION_IDLE_TTL_SECONDS` | 最后一次客户/客服消息超过该时间后自动删除，默认约 2 个月。 |
| `MEDIA_TTL_SECONDS` | 本地媒体文件超过该时间后自动删除，默认约 3 天。 |
| `CUSTOMER_WAITING_HINT` | 客户对话界面的等待提示文案。 |

安全建议：不要把真实 `WEBCHAT_BOT_TOKEN` 发布到公开仓库，也不要写入 `config.py`；如曾经提交过真实 Token，应立即在 BotFather 重置。`WEBCHAT_TOKEN_KEY` 换值后，数据库中已有的客户侧 Bot Token 密文无法继续解密，生产环境应固定保存并纳入密钥备份。

`WEBCHAT_ADMIN_IDS` 是管理员初始化来源。对应 Telegram 用户首次 `/start` 或使用命令时会写入 `users` 表，并同步为 `admin` 角色。未设置该环境变量时，程序会使用 `config.py` 里的默认管理员列表；生产环境建议显式设置，避免不同环境误授权。

## 用户角色初始化与权限

系统支持三类角色：

| 角色 | Key 数量 | 运维含义 |
| --- | --- | --- |
| `normal` | 1 个 | 默认新用户。可创建自己的入口、绑定客服群和客户侧机器人，但不能使用网页客服入口、来源统计和快速回复。 |
| `vip` | 5 个 | 可使用网页客服入口、来源统计和快速回复。 |
| `admin` | 不限制 | 可管理所有用户、入口、全局帮助链接和管理员联系方式。 |

常用管理员操作：

```text
/userls
/userget <telegram_user_id>
/userset <telegram_user_id> vip
/userban <telegram_user_id>
/userunban <telegram_user_id>
/userkeys <telegram_user_id>
```

如果用户反馈网页入口返回 `WEB_DISABLED`，先用 `/userget` 查看角色和禁用状态；普通用户需要升级为 `vip` 或 `admin` 后才能使用网页客服能力。
`/kls` 不带参数时只查看当前账号名下的所有 key；管理员排查其他账号时，使用 `/kls <telegram_user_id>` 查看对方入口列表，再用 `/adminkeyinfo <key>` 查看入口详情。`/userkeys <telegram_user_id>` 保留为兼容管理命令。

## 手动启动

先启动 API：

```bash
cd /www/wwwroot/webchat
source venv/bin/activate
python api_server.py
```

再另开一个终端启动 Bot：

```bash
cd /www/wwwroot/webchat
source venv/bin/activate
python tg_bot.py
```

健康检查：

```bash
curl http://127.0.0.1:5055/health
```

## systemd 示例

### API 服务

创建 `/etc/systemd/system/webchat-api.service`：

```ini
[Unit]
Description=WebChat Flask API
After=network.target

[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/www/wwwroot/webchat
Environment=WEBCHAT_BOT_TOKEN=替换为你的主BotToken
Environment=WEBCHAT_TOKEN_KEY=替换为Fernet生成的固定密钥
Environment=WEBCHAT_INTERNAL_TOKEN=替换为API和Bot共用的随机长字符串
ExecStart=/www/wwwroot/webchat/venv/bin/gunicorn -k gthread -w 1 --threads 32 -b 127.0.0.1:5055 "api.app:create_app()"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

> ⚠️ **必须使用 `-w 1`**：SSE 订阅者字典是 worker 进程内的内存结构,`tg_bot.py` 通过 `/internal/notify` 推送事件时,反向代理会把请求路由到任意一个 worker,只有恰好持有订阅者队列的 worker 能把事件推给客户端。开多个 worker 会让客户端按 1/N 的概率漏收消息。需要更高并发时,把 `--threads` 调到 64/128,或改用 `gevent`/`eventlet` worker(单进程几千并发连接)。

### Bot 服务

创建 `/etc/systemd/system/webchat-bot.service`：

```ini
[Unit]
Description=WebChat Telegram Bot
After=network.target webchat-api.service

[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/www/wwwroot/webchat
Environment=WEBCHAT_BOT_TOKEN=替换为你的主BotToken
Environment=WEBCHAT_TOKEN_KEY=替换为Fernet生成的固定密钥
Environment=WEBCHAT_INTERNAL_TOKEN=替换为API和Bot共用的随机长字符串
ExecStart=/www/wwwroot/webchat/venv/bin/python /www/wwwroot/webchat/tg_bot.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
systemctl daemon-reload
systemctl enable --now webchat-api
systemctl enable --now webchat-bot
```

### 定时清理任务

清理任务已经从 API 请求链路中拆出，**必须**用 systemd timer 或 cron 单独运行，否则过期数据永远不会被清掉：

示例 service `/etc/systemd/system/webchat-cleanup.service`：

```ini
[Unit]
Description=WebChat expired cleanup

[Service]
Type=oneshot
User=www
Group=www
WorkingDirectory=/www/wwwroot/webchat
Environment=WEBCHAT_BOT_TOKEN=替换为你的主BotToken
Environment=WEBCHAT_TOKEN_KEY=替换为Fernet生成的固定密钥
ExecStart=/www/wwwroot/webchat/venv/bin/python -m api.cleanup_worker
```

示例 timer `/etc/systemd/system/webchat-cleanup.timer`：

```ini
[Unit]
Description=Run WebChat cleanup every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Unit=webchat-cleanup.service

[Install]
WantedBy=timers.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now webchat-cleanup.timer
```

查看状态和日志：

```bash
systemctl status webchat-api
systemctl status webchat-bot
journalctl -u webchat-api -f
journalctl -u webchat-bot -f
```

## Nginx 示例

以下示例适用于当前配置：由 Flask 返回 `/<key>` 页面、`/widget/` 配置接口和 `/api/media/<file_id>` 媒体响应，由 Nginx 反向代理动态接口。

```nginx
location /api/stream/ {
    proxy_pass http://127.0.0.1:5055;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
}

location /api/ {
    proxy_pass http://127.0.0.1:5055;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /widget/ {
    proxy_pass http://127.0.0.1:5055;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

媒体目录有两种托管方式：

1. 默认走 Flask：媒体落在后端项目根目录 `media/`，访客通过 `GET /api/media/<file_id>` 拉取，Nginx 不需要额外配置 `location`。前后端跨机房部署时也走这种方式。
2. 当前版本默认不配置静态媒体 location；如后续改为 Nginx 直接托管媒体，需要同步调整媒体 URL 生成逻辑。

媒体文件默认约 3 天后会被清理。这里不要配置过长缓存，否则客户浏览器可能继续展示已经从服务器删除的旧媒体。

内部通知接口不要暴露公网：

```nginx
location /internal/ {
    allow 127.0.0.1;
    deny all;
    proxy_pass http://127.0.0.1:5055;
}
```

客户页面入口：

```nginx
location / {
    proxy_pass http://127.0.0.1:5055;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

如果同一个域名还承载其他站点页面，不要直接把整站 `location /` 都转给本项目，应只把实际客服入口 `key` 对应的路径转发到 Flask。

## Telegram 初始化

1. 创建 Telegram Bot，拿到 `BOT_TOKEN`。
2. 创建或选择一个超级群。
3. 开启群的「话题」功能。
4. 把 Bot 添加为管理员。
5. 确认 Bot 有创建话题、关闭话题、发送消息和读取消息的权限。
6. 管理员私聊主 Bot，发送 `/start` 初始化管理员账号，再发送 `/adminhelp` 确认可见管理员命令。
7. 在目标客服群里发送 `/id`，确认返回的是超级群 `chat_id`。
8. 管理员可用兼容命令直接创建入口：

```text
/kadd yaoyao -1001234567890 客服瑶瑶
```

9. 普通用户或 VIP 也可以先私聊主 Bot 创建入口，再到客服群绑定：

```text
/keyadd yaoyao 客服瑶瑶
```

在目标超级群里发送：

```text
/groupbind yaoyao
```

10. 如果需要网页端使用 `https://你的域名/yaoyao?src=abc`，确认入口所属用户是 `vip` 或 `admin`。普通用户入口会返回 `WEB_DISABLED`。

绑定客户侧 Telegram 机器人建议使用交互式流程：

```text
/tokenadd yaoyao
```

主 Bot 提示后，用户在私聊里发送客户侧 Bot Token。系统会校验 Token、保存绑定并尝试删除含 Token 的消息。绑定到 `key` 后不需要重启 `tg_bot.py`；客户访问该机器人并发送 `/start link123` 时，`link123` 会作为 Telegram 来源参数进入统计。

管理员仍可使用兼容命令 `/botadd <key> <bot_token> [bot_username]`，但生产运维优先使用 `/tokenadd`，减少 Token 暴露在群聊或日志里的机会。

## 日常操作

用户自查：

```text
/myinfo
/keyinfo
```

用户创建和维护入口：

```text
/keyadd yaoyao 客服瑶瑶
/groupbind yaoyao
/welcome yaoyao 欢迎咨询，我们会尽快回复您。
/tokenadd yaoyao
```

查看入口：

```text
/kls
```

`/kls` 只列出当前账号自己的所有入口。管理员需要查看其他账号时，执行 `/kls <telegram_user_id>`，必要时再执行 `/adminkeyinfo <key>` 查看详情。

切换上/下班状态：

```text
/kstatus yaoyao        # 仅切换 yaoyao 这个 key
/kstatus               # 不带参数：按多数决统一切换名下全部 key
```

更新下班留言（也可在 `/kls → 选择 key → 🛌 下班留言` 按钮里设置）：

```text
/kls
# 选 yaoyao → 点「🛌 下班留言」→ 私聊里发送新的下班留言文本
```

设置全局帮助链接（显示在主机器人 /start 和 /help 末尾）：

```text
/helplink https://你的域名/help
```

VIP 或管理员查看来源统计和维护快速回复：

```text
/stats yaoyao
/qradd yaoyao 价格|请发送您的需求，客服会为您确认。
/qrls yaoyao
```

结束会话：

```text
/end
```

客服会话命令不要求管理员权限，但必须在对应客服会话话题内发送：

| 命令 | 说明 |
| --- | --- |
| `/valid` | 标记当前会话为有效客户。 |
| `/deal` | 标记当前会话为成交客户。 |
| `/end` | 结束当前会话。 |

`/end` 会删除或关闭客服群话题、删除会话事件、删除该会话的本地媒体。

定时过期清理会执行同样的会话收尾动作：会话开始超过约 2 个月，或最后一次客户/客服消息超过约 2 个月后，系统会尝试删除或关闭对应 Telegram 话题，并删除会话和聊天事件。本地媒体文件默认约 3 天后单独过期，过期后网页端显示占位提示。

## 客户机器人 Token 安全

- 优先使用 `/tokenadd <key>` 进入私聊绑定流程，避免在群聊或多人可见环境中粘贴 Token。
- 发送 Token 后，主 Bot 会尝试删除该消息；如果 Telegram 权限或客户端限制导致删除失败，应手动删除。
- 不要把客户侧 Bot Token 写入 README、工单、截图或公开日志。
- 如怀疑 Token 泄露，先到 BotFather 重置 Token，再重新执行 `/tokenadd <key>`。
- 绑定完成后不需要重启 `tg_bot.py`；进程会热加载新的客户机器人绑定，服务重启后也会从 `bot_bindings` 恢复。

## 备份与恢复

需要备份：

- `/www/wwwroot/webchat/data/webchat.db`
- `/www/wwwroot/webchat/media`（如果 `WEBCHAT_MEDIA_ROOT` 指向别处，备份目标也要相应调整）

停机备份：

```bash
systemctl stop webchat-api webchat-bot
cp data/webchat.db backup/webchat.db
rsync -a media/ backup/webchat-media/
systemctl start webchat-api webchat-bot
```

不停机备份数据库：

```bash
sqlite3 data/webchat.db ".backup 'backup/webchat.db'"
```

恢复时先停止两个服务，再替换数据库和媒体目录。

## 升级流程

1. 备份数据库和媒体目录。
2. 更新代码。
3. 安装或更新依赖：

```bash
source venv/bin/activate
pip install -r requirements.txt
```

4. 重启服务：

```bash
systemctl restart webchat-api webchat-bot
```

5. 检查健康状态：

```bash
curl http://127.0.0.1:5055/health
journalctl -u webchat-api -n 100
journalctl -u webchat-bot -n 100
```

## 上线前回归验证清单

每次调整多用户权限或上线前，至少执行：

```bash
python -m compileall api_server.py tg_bot.py config.py api bot db shared
```

测试环境手动验收：

- 普通用户只能创建 1 个 `key`，第 2 个应被拒绝。
- VIP 最多可创建 5 个 `key`，第 6 个应被拒绝。
- 管理员可通过 `/userset` 调整角色，通过 `/userban` 和 `/userunban` 改变用户禁用状态。
- 普通用户入口访问网页端返回 `WEB_DISABLED`；升级 VIP 后网页端可访问。
- `/kls` 只返回当前账号自己的入口；管理员查看他人入口时必须带对方账号，例如 `/kls <telegram_user_id>`。
- `/tokenadd <key>` 能热绑定客户侧机器人，绑定后不重启服务也能响应。
- 重启 `tg_bot.py` 后，客户侧机器人绑定能从 `bot_bindings` 恢复。
- 客户侧机器人 `/start` 显示对应 `welcome_text`；携带 `/start link123` 时记录 Telegram 来源点击。
- 在目标超级群内执行 `/groupbind <key>` 后，新会话能在该群创建话题。

## 排障清单

### 多用户权限排查

- 用户先发送 `/myinfo`，确认自己的角色、禁用状态和 key 使用量。
- 管理员使用 `/userget <telegram_user_id>` 查看用户角色，必要时用 `/userset <telegram_user_id> vip` 升级。
- 管理员使用 `/userkeys <telegram_user_id>` 或 `/adminkeyinfo <key>` 确认入口归属、客服群绑定和客户机器人绑定。
- 网页端返回 `WEB_DISABLED` 通常表示入口属于普通用户或已禁用用户；这是权限分级的预期行为。
- 网页端返回 `KEY_NOT_FOUND` 表示入口不存在或 `key` 写错，和权限不足不同。
- 旧数据如果 `owner_user_id` 为空，会返回 `WEB_DISABLED`；建议管理员重新创建或补齐入口归属，减少排查歧义。

### API 不通

- 检查 `webchat-api` 是否运行。
- 检查 `API_HOST` 和 `API_PORT`。
- 检查 Nginx `proxy_pass` 是否指向 `127.0.0.1:5055`。
- 执行 `curl http://127.0.0.1:5055/health`。

### SSE 没有实时推送

- 检查 `tg_bot.py` 是否运行。
- 检查 Bot 服务能否请求 `http://127.0.0.1:5055/internal/notify`。
- 检查 Nginx 的 `/api/stream/` 是否配置 `proxy_buffering off`。
- 浏览器断线重连时可带上 `since_id` 补拉遗漏消息。

### Bot 无法创建话题

- 确认目标群是超级群。
- 确认群已开启话题功能。
- 确认 Bot 是管理员，并有管理话题权限。
- 用 `/id` 确认 `forum_chat_id` 是否正确。

### 客户机器人不响应

- 用 `/keyinfo <key>` 或 `/adminkeyinfo <key>` 确认客户机器人已绑定且启用。
- 确认客户侧 Bot Token 没有被 BotFather 重置。
- 重新执行 `/tokenadd <key>` 后，无需重启服务；如仍无响应，再查看 `webchat-bot` 日志。
- 客户机器人 `/start` 后应返回入口欢迎文案；携带 `/start link123` 时才会记录 Telegram 来源点击。

### 媒体下载失败

- 检查服务器是否能访问 Telegram 文件接口。
- 检查媒体目录是否存在。
- 检查运行用户是否有写入权限。
- 查看 `webchat-bot` 日志中的下载错误。
