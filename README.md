# WebChat

WebChat 是一个基于 Flask 和 Telegram Bot 的客服系统。网页访客或客户侧 Telegram 机器人发起人工咨询后，系统会为该客户会话创建一个 Telegram 论坛话题；客服在话题里回复，系统再把回复推回网页端或客户侧 Telegram 私聊。

本 README 描述当前功能和代码审查口径，后续审查以本文档为准。

## 功能特性

- 多客服入口：使用 `key` 区分不同入口、客服组和显示名。
- 多用户权限：支持 `normal`、`vip`、`admin` 三类角色，用户只能管理自己名下的入口，管理员可统一管理。
- Key 数量限制：普通用户最多 1 个 `key`，VIP 最多 5 个，管理员不限制。
- 网页入口：客户访问 `/<key>?src=abc`，页面调用 `/widget/<key>` 获取配置。
- 网页能力分级：普通用户可使用客户侧 Telegram 机器人接待客户；VIP 和管理员可使用网页客服入口、来源统计和快速回复。
- 客户侧 Telegram 机器人：每个 `key` 可以绑定额外 Bot，支持 `/start link123` 来源参数。
- 交互式绑定：用户可通过 `/tokenadd` 安全提交客户侧 Bot Token，通过 `/groupbind` 在客服群内绑定入口。
- 会话自动建话题：客户真正发送人工消息时，系统创建 Telegram 超级群论坛话题。
- 来源统计：网页有 `src` 或 Telegram `/start` 有参数时记录点击，客户发消息后记录会话转化；没有来源参数时不进入来源统计。
- 客户标记：客服可在会话话题内使用 `/valid` 和 `/deal` 标记有效客户或成交客户。
- 快速回复：每个 `key` 最多配置约 9 个常见问题；点击后只做自助回答，不创建客服话题。
- 会话自动过期：会话计划保留约 2 个月；本地媒体文件约 3 天后过期。
- 实时消息推送：网页端通过 SSE 接收客服回复。
- 浏览器通知：网页访客发送消息后会请求通知权限；当页面在后台且收到客服回复时，浏览器会弹出通知。
- 支持客服媒体消息：客服回复可包含文本、图片、视频、文档和相册笔记。
- 过期媒体占位：媒体文件删除后，网页端显示「图片已过期」「视频已过期」或「文件已过期」。
- 在线/离线状态：管理员可为每个 `key` 设置上班、下班和离线提示。
- SQLite 存储：用户、入口、会话、消息事件、统计和媒体记录保存在 `webchat.db`。
- 简单限流：同一 IP 每 60 秒发送消息次数可配置。

## 系统架构

```text
网页访客
  -> Flask API: /<key>、/widget、/api/msg、/api/stream
  -> SQLite: webchat.db
  -> Telegram Bot API
  -> Telegram 超级群论坛话题

客户侧 Telegram 机器人
  -> tg_bot.py
  -> SQLite: webchat.db
  -> Telegram 超级群论坛话题

客服在 Telegram 话题内回复
  -> tg_bot.py 写入 webchat.db
  -> 网页会话通过 /internal/notify 通知 Flask SSE
  -> Telegram 会话通过客户侧机器人私聊回推
```

## 目录结构

项目按「功能域」分层：根目录只保留两个进程入口和全局配置，业务代码按 `db/`、`api/`、`bot/`、`shared/` 分包，数据落在 `data/` 目录。

```text
.
├── api_server.py            # Flask API 进程入口（薄壳，调用 api.app.main）
├── tg_bot.py                # Telegram Bot 进程入口（薄壳，调用 bot.app.main）
├── config.py                # Bot Token、路径、端口、清理策略等全局配置
├── requirements.txt         # Python 依赖清单
│
├── data/                    # 运行时数据（默认全部落在后端本机）
│   ├── webchat.db           # 客服会话数据库（DB_PATH 默认值）
│   └── media/               # 客服媒体落盘目录（WEBCHAT_MEDIA_ROOT 默认值）
│
├── public/
│   └── chat.html            # 网页聊天入口，支持 /<key>?src=abc
│
├── db/                      # 数据访问层，按表/领域拆分
│   ├── __init__.py          # 统一再导出，对外只需 `from db import xxx`
│   ├── connection.py        # 连接、时间工具、通用列检测
│   ├── schema.py            # 建表 DDL 和迁移
│   ├── users.py             # 用户和角色
│   ├── settings.py          # 全局 KV 设置
│   ├── pending.py           # 待处理交互（如 /tokenadd 等待 Token）
│   ├── widgets.py           # 客服入口/key
│   ├── sessions.py          # 客服会话
│   ├── events.py            # 消息事件
│   ├── bot_bindings.py      # 客户侧 Bot 绑定
│   ├── quick_replies.py     # 快速回复
│   ├── stats.py             # 来源点击和会话转化统计
│   ├── marks.py             # /valid /deal 客户标记
│   └── media.py             # 媒体记录
│
├── api/                     # Flask API
│   ├── app.py               # 应用工厂、路由注册、main()
│   ├── telegram_client.py   # Telegram HTTP 调用、话题创建/删除
│   ├── rate_limit.py        # IP 限流与内网 IP 判定
│   ├── sse.py               # SSE 订阅者管理和广播
│   ├── cleanup.py           # 过期会话和媒体清理调度
│   ├── validators.py        # KEY/SOURCE 校验、错误响应
│   └── routes/
│       ├── health.py        # GET /health
│       ├── widget.py        # GET /<key>、GET /widget/<key>
│       ├── messages.py      # POST /api/msg/<key>、GET /api/history/<key>
│       ├── stream.py        # GET /api/stream/<session_id> (SSE)
│       ├── media.py         # GET /api/media/<file_id>
│       └── internal.py      # POST /internal/notify
│
├── bot/                     # Telegram Bot
│   ├── app.py               # Dispatcher 装配、客户侧 Bot 轮询、main()
│   ├── customer_bots.py     # 多 Bot 注册表与轮询任务
│   ├── telegram_api.py      # Telegram HTTP 调用、文件下载
│   ├── media.py             # 媒体落盘到 WEBCHAT_MEDIA_ROOT
│   ├── relay.py             # 话题创建、客服↔客户消息中继、notify_web
│   ├── auth.py              # 用户、角色、入口归属校验
│   ├── validators.py        # KEY/SOURCE 校验
│   ├── pending.py           # 私聊待处理动作分发（Token 提交等）
│   └── handlers/
│       ├── basic.py         # /start /help /adminhelp /helplink /admincontact /myinfo /id
│       ├── user_keys.py     # /keyadd /keyinfo /keydel
│       ├── binding.py       # /tokenadd /welcome /groupbind
│       ├── admin_users.py   # /userls /userget /userset /userban /userunban /userkeys /adminkeyinfo /adminkeydel
│       ├── admin_entries.py # /kadd /kdel /kls /koff /kon /kmsg
│       ├── customer_bots.py # /botadd /botdel /botls
│       ├── quick_replies.py # /qradd /qrls /qrdel + 内联回调
│       ├── stats.py         # /stats /statdel
│       ├── session_cmds.py  # /valid /deal /end
│       └── messages.py      # 客户私聊消息、客服话题回复、相册笔记合并
│
├── shared/                  # 跨层公用
│   ├── event_payload.py     # event_row → 前端 payload
│   └── session_cleanup.py   # 会话与媒体过期清理实现
│
└── docs/
    ├── ARCHITECTURE.md      # 分层结构和扩展指引
    ├── API.md               # HTTP API 文档
    ├── DATABASE.md          # 数据库结构说明
    └── OPERATIONS.md        # 部署与运维手册
```

添加新功能的位置约定：

- 新的 HTTP 路由：在 `api/routes/` 下加一个文件，在 `api/app.py` 注册。
- 新的 Telegram 命令：在 `bot/handlers/` 下加一个文件，在 `bot/handlers/__init__.py` 注册。
- 新的数据表：在 `db/` 下加一个文件，把 DDL 加进 `db/schema.py`，把对外函数加进 `db/__init__.py` 再导出。

后端在新加坡、前端 Nginx 在香港的部署模式下，本次重构仍把媒体落在后端 `data/media/`，访客通过 Flask `GET /api/media/<file_id>` 取媒体；将媒体迁到前端机器（挂载、HTTPS 推送或对象存储）作为后续独立优化项。

## 环境要求

- Python 3.11 或更新版本。
- 可访问 Telegram Bot API 的服务器网络。
- 一个已开启「话题」功能的 Telegram 超级群。
- Nginx 或其他反向代理，用于把公网请求转发到 Flask API，并托管媒体静态目录。
- 客服媒体文件静态目录，例如 `/www/wwwroot/kefu.ws/webchat/media`。

当前 `config.py` 使用 Linux 服务器路径。若在本地 Windows 环境调试，需要先把媒体目录改成当前机器可写的路径。

## 快速开始

安装依赖：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

修改配置：

```bash
vim config.py
```

主 Bot Token 和密钥必须通过环境变量提供，不要写入 `config.py`：

```bash
export WEBCHAT_BOT_TOKEN="替换为你的主BotToken"
export WEBCHAT_TOKEN_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export WEBCHAT_INTERNAL_TOKEN="替换为随机长字符串"
```

重点确认这些配置：

| 配置项 | 说明 |
| --- | --- |
| `WEBCHAT_BOT_TOKEN` | 主 Telegram Bot Token，通过环境变量提供；不要把真实 Token 写入代码或提交到仓库。 |
| `WEBCHAT_TOKEN_KEY` | 客户侧 Bot Token 的落盘加密密钥，必填，必须由 `Fernet.generate_key()` 生成。 |
| `WEBCHAT_INTERNAL_TOKEN` | `/internal/notify` 的 Bearer Token，API 进程和 Bot 进程必须使用同一个值。 |
| `WEBCHAT_ADMIN_IDS` | 初始化管理员 Telegram 用户 ID 集合，逗号分隔；对应用户会同步为 `admin` 角色。 |
| `API_HOST` / `API_PORT` | Flask API 监听地址和端口，默认 `127.0.0.1:5055`。 |
| `DB_PATH` | 客服会话数据库路径，默认 `data/webchat.db`。 |
| `WEBCHAT_MEDIA_ROOT` | 客服媒体文件落盘目录，默认 `data/media`，生产可通过环境变量覆盖到 Nginx 静态目录。 |
| `RATE_LIMIT_PER_60S` | 同一 IP 每 60 秒最多发送的访客消息数。 |
| `SESSION_TTL_SECONDS` / `SESSION_IDLE_TTL_SECONDS` | 会话最大保留约 2 个月。 |
| `MEDIA_TTL_SECONDS` | 本地媒体文件保留时间，默认约 3 天。 |
| `CUSTOMER_WAITING_HINT` | 客户对话界面的等待提示。 |

启动 API 服务：

```bash
python api_server.py
```

另开一个终端启动 Telegram Bot：

```bash
python tg_bot.py
```

再起一个 systemd timer 或 cron 定时清理过期会话和媒体，建议每分钟执行一次：

```bash
python -m api.cleanup_worker
```

生产环境的 systemd unit 和 timer 示例见 `docs/OPERATIONS.md` 的「定时清理任务」。

检查 API：

```bash
curl http://127.0.0.1:5055/health
```

正常返回：

```json
{"ok": true}
```

## 用户角色与权限

Telegram 用户首次发送 `/start` 或使用业务命令时会写入 `users` 表；`WEBCHAT_ADMIN_IDS` 中配置的用户会自动同步为管理员。

| 角色 | Key 数量 | 可用能力 |
| --- | --- | --- |
| `normal` | 1 个 | 创建和管理自己的入口，绑定客服群，绑定客户侧机器人，自定义欢迎文案。网页客服入口、来源统计和快速回复不可用。 |
| `vip` | 5 个 | 拥有普通用户能力，并可使用网页客服入口、来源统计和快速回复。 |
| `admin` | 不限制 | 管理所有用户和入口，调整角色和禁用状态，查看或删除任意用户的 key。 |

被禁用用户不能继续使用用户侧命令，也不能访问自己名下的网页客服入口。旧数据中没有 `owner_user_id` 的入口无法通过网页客服权限校验，会返回 `WEB_DISABLED`，建议由管理员后续补齐归属。

## Telegram 命令

### 基础命令

基础命令不要求管理员权限。

| 命令 | 说明 |
| --- | --- |
| `/start` | 初始化或刷新当前用户信息，并查看可用命令。 |
| `/help` | 查看当前角色可用的帮助。 |
| `/myinfo` | 查看自己的 Telegram ID、角色、禁用状态和 key 使用量。 |
| `/id` | 在群里发送时返回 `chat_id`、群类型和话题 ID。 |

### 用户入口命令

这些命令面向普通用户和 VIP。用户只能操作自己名下的 `key`；管理员可操作全部入口。

| 命令 | 说明 |
| --- | --- |
| `/keyadd <key> [显示名]` | 创建自己的客服入口。普通用户最多 1 个，VIP 最多 5 个。 |
| `/kls [telegram_user_id]` | 不带参数时查看自己名下的所有客服入口；管理员带对方 Telegram 用户 ID 时查看对方入口。 |
| `/keyinfo [key]` | 查看自己的入口、客服群绑定和客户机器人绑定状态。 |
| `/keydel <key>` | 删除自己的入口。 |
| `/tokenadd <key>` | 启动客户侧 Bot Token 绑定流程；随后私聊发送 Token，系统会尝试删除含 Token 的消息。 |
| `/welcome <key> <欢迎文案>` | 设置客户侧 Telegram 机器人 `/start` 欢迎文案。 |
| `/groupbind <key>` | 在目标超级群内发送，把该群绑定为 `key` 的客服群。 |

### VIP 和管理员命令

这些命令要求入口归属用户是 VIP 或管理员；普通用户不可使用网页端相关能力。

| 命令 | 说明 |
| --- | --- |
| `/qradd <key> <标题>\|<答案>` | 添加快速回复。 |
| `/qrls <key>` | 查看快速回复。 |
| `/qrdel <key> <编号>` | 删除快速回复。 |
| `/stats <key> [来源]` | 查看来源统计。 |
| `/statdel <key> [来源]` | 清理统计，不删除聊天记录。 |

### 管理员命令

管理员命令只对 `admin` 角色用户生效；`WEBCHAT_ADMIN_IDS` 会在用户初始化时自动同步为管理员。

| 命令 | 说明 |
| --- | --- |
| `/adminhelp` | 查看管理员命令。 |
| `/userls` | 查看用户列表。 |
| `/userget <telegram_user_id>` | 查看指定用户资料和 key 使用量。 |
| `/userset <telegram_user_id> <normal|vip|admin>` | 设置用户角色。 |
| `/userban <telegram_user_id>` | 禁用用户。 |
| `/userunban <telegram_user_id>` | 解除禁用。 |
| `/userkeys <telegram_user_id>` | 管理员查看指定用户拥有的入口；也可用 `/kls <telegram_user_id>`。 |
| `/adminkeyinfo <key>` | 查看任意入口详情。 |
| `/adminkeydel <key>` | 删除任意入口。 |
| `/helplink <URL>` | 设置全局帮助链接。 |
| `/admincontact <联系方式>` | 设置全局管理员联系方式。 |
| `/kadd <key> <forum_chat_id> <显示名>` | 添加或更新一个网页客服入口。 |
| `/kdel <key>` | 删除客服入口。 |
| `/koff <key> [离线提示]` | 将入口设为离线，可同时设置离线提示。 |
| `/kon <key>` | 将入口设为在线。 |
| `/kmsg <key> <离线提示>` | 只更新离线提示，不改变在线状态。 |
| `/botadd <key> <bot_token> [bot_username]` | 给 `key` 绑定客户侧 Telegram 机器人，绑定后不需要重启 `tg_bot.py`。 |
| `/botdel <key> [bot_username]` | 删除客户机器人绑定。 |
| `/botls [key]` | 查看客户机器人绑定。 |

### 客服会话命令

客服会话命令不要求管理员权限，但必须在对应客服群会话话题内使用。

| 命令 | 说明 |
| --- | --- |
| `/valid` | 在客服会话话题中标记有效客户，不需要管理员权限。 |
| `/deal` | 在客服会话话题中标记成交客户，不需要管理员权限。 |
| `/end` | 在客服会话话题里结束当前会话，删除/关闭客服群话题、会话数据和本地媒体。 |

添加入口示例：

```text
/kadd yaoyao -1001234567890 客服瑶瑶
```

添加后，网页端访问 `https://你的域名/yaoyao?src=abc`。

普通用户和 VIP 创建入口示例：

```text
/keyadd yaoyao 客服瑶瑶
```

在客服超级群中绑定入口：

```text
/groupbind yaoyao
```

绑定客户侧 Telegram 机器人：

```text
/tokenadd yaoyao
```

机器人提示后，在私聊里发送客户侧 Bot Token。绑定后不需要重启 `tg_bot.py`。客户访问该机器人并发送 `/start link123` 时，`link123` 作为 Telegram 来源参数记录点击；客户真正发送人工咨询消息后，系统才创建客服群话题并记录会话转化。客户没有携带 `/start` 参数时不进入来源统计。

## 前端接入概览

典型接入流程：

1. 访问 `GET /{key}?src=abc` 打开客户聊天页。
2. 聊天页调用 `GET /widget/{key}?src=abc&visitor_id=...` 获取入口配置、快速回复和来源点击统计。
3. 客户点击快速回复时，只在前端展示自助答案，不创建客服群话题。
4. 客户主动发送人工消息时，调用 `POST /api/msg/{key}` 创建或复用会话。
5. 使用 `EventSource('/api/stream/{session_id}')` 接收客服回复。
6. 访客发送消息后，网页端会在浏览器支持且用户授权的情况下启用通知；页面处于后台时收到客服回复会弹出浏览器通知，历史消息不会重复通知。
7. 需要历史消息时调用 `GET /api/history/{key}?session_id=...`。
8. 客服媒体可通过 `GET /api/media/{file_id}` 获取文件；媒体过期时显示占位提示。

网页访问没有 `src` 参数时不进入来源统计；只有客户真正发送人工消息后，才记录来源会话转化。

网页客服入口只对 VIP 和管理员名下的 `key` 开放。普通用户或被禁用用户访问 `GET /{key}`、`GET /widget/{key}`、`POST /api/msg/{key}`、`GET /api/history/{key}` 或对应 SSE 流时，会返回 403 和 `WEB_DISABLED`。

接口细节见 [API 文档](./docs/API.md)；代码分层和扩展指引见 [架构说明](./docs/ARCHITECTURE.md)。

## 部署与运维

生产环境建议把 API 服务和 Bot 分成两个常驻进程，用 systemd 或 Supervisor 管理。Nginx 负责反向代理 `/<key>`、`/widget/`、`/api/` 和 `/internal/`，并直接托管媒体静态目录。

详细步骤见 [部署与运维手册](./docs/OPERATIONS.md)。

## 数据库

项目使用 `webchat.db` 存储用户、全局设置、待处理操作、客服入口、会话、消息事件、客户机器人绑定、快速回复、来源统计、客户标记和媒体记录。表结构和数据保留规则见 [数据库说明](./docs/DATABASE.md)。

当前实现需要兼容旧版本数据库字段；但本次重构不要求旧地址或旧数据迁移流程，新环境可以按当前表结构初始化。

## 代码审查重点

审查代码时，以以下行为作为验收口径：

- 路由使用 `/<key>` 和 `/widget/<key>`，不再把 `/chat/<key>` 或 `/api/widget/<key>` 作为入口。
- 用户权限以 `owner_user_id` 和 `users.role` 为准：普通用户最多 1 个 `key`，VIP 最多 5 个，管理员不限制。
- 普通用户的网页客服入口应返回 `WEB_DISABLED`，VIP 和管理员入口可正常使用网页端能力。
- 网页 `?src=abc` 和 Telegram `/start link123` 分别记录来源点击；没有来源参数时不写入来源统计。
- 客户点击快速回复只展示自助答案，不创建客服话题，不记录快速回复点击统计。
- 客户真正发送人工咨询消息后才创建或复用客服会话，并记录来源会话转化。
- 每个 `key` 可以绑定客户侧 Telegram 机器人，绑定后不需要重启 `tg_bot.py`。
- `/valid`、`/deal` 和 `/end` 是客服会话命令，不要求管理员权限，但必须在对应客服话题内使用。
- `/statdel <key> [来源]` 只清理统计，不删除会话、聊天记录、媒体记录或客服群话题。
- 会话默认保留约 2 个月；本地媒体默认约 3 天后过期，过期媒体在网页端显示占位提示。
- 网页端渲染客服文本、图片、视频、文档和相册笔记时，必须保持排版稳定，不让长文本或媒体撑乱聊天流。
- 网页端浏览器通知只针对 SSE 收到的客服消息触发，且必须满足页面在后台、浏览器支持 Notification API、用户已授权通知；历史消息加载和访客自己发送的消息不得触发通知。

## 安全注意事项

- 不要把真实 `WEBCHAT_BOT_TOKEN` 提交到公开仓库，也不要写入 `config.py`；如曾经提交过真实 Token，应立即在 BotFather 重置。
- `WEBCHAT_TOKEN_KEY` 是客户侧 Bot Token 的加密密钥，换值后旧的客户侧 Bot Token 密文将无法解密。生产环境应固定保存该环境变量，并纳入密钥备份。
- `WEBCHAT_INTERNAL_TOKEN` 需要同时配置在 API 服务和 Bot 服务中，否则客服回复无法通过 `/internal/notify` 推送到 SSE。
- 客户侧 Bot Token 通过 `/tokenadd` 私聊提交；不要在群聊、工单或文档中暴露真实 Token。
- `/internal/notify` 只允许本机或内网来源访问；Flask 层会校验 `remote_addr`，如果请求来自本机/内网可信反代且带有 `X-Forwarded-For` 或 `X-Real-IP`，会继续校验真实客户端 IP。
- `API_HOST` 默认使用 `127.0.0.1`，建议保持这个设置，再由 Nginx 转发公网请求。
- 定期备份 `webchat.db` 和 `WEBCHAT_MEDIA_ROOT`。
- Telegram Bot 需要具备创建和关闭论坛话题、发送消息、读取群消息的权限。

## 常见问题

### 网页发消息返回 `KEY_NOT_FOUND`

说明该 `key` 还没有通过 `/kadd` 添加，或网页端使用的 `key` 和 Telegram 中配置的不一致。

### 网页访问返回 `WEB_DISABLED`

说明该入口属于普通用户、已禁用用户，或旧数据中入口缺少 `owner_user_id`。普通用户仍可通过客户侧 Telegram 机器人接待客户；如果需要网页客服入口，请由管理员将用户调整为 VIP 或管理员，并补齐入口归属。

### 客服回复没有推到网页

先确认 `api_server.py` 正在运行，再检查 `tg_bot.py` 是否能访问 `http://127.0.0.1:5055/internal/notify`。如果使用反向代理，确认 `/api/stream` 禁用了缓冲。

### 媒体文件打不开

检查 `WEBCHAT_MEDIA_ROOT` 是否存在、进程是否有写入权限，以及 Nginx 是否正确映射 `/webchat/media/`。

### 机器人不响应管理命令

确认发送管理命令的 Telegram 用户是 `admin` 角色。初始管理员来自 `WEBCHAT_ADMIN_IDS`，也可以由现有管理员通过 `/userset <telegram_user_id> admin` 授权。`/valid`、`/deal` 和 `/end` 属于客服会话命令，不看管理员角色，但必须在对应客服话题内发送。
