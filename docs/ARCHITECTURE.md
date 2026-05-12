# 架构说明

本文档描述 WebChat 的代码分层、模块职责和扩展约定。部署细节见 [OPERATIONS.md](./OPERATIONS.md)，HTTP 接口细节见 [API.md](./API.md)，数据库结构见 [DATABASE.md](./DATABASE.md)。

## 进程模型

项目运行两个独立进程：

- **`api_server.py`**：Flask API 进程，处理网页请求、SSE 推送、媒体代理和 `/internal/notify`。监听 `127.0.0.1:5055`，前置 Nginx。
- **`tg_bot.py`**：Telegram Bot 进程，处理管理命令、客户侧 Bot 私聊、客服群话题回复，并通过 `/internal/notify` 把客服消息推到 Flask SSE。

两个文件本身只是**薄壳入口**，分别 `from api.app import main` 和 `from bot.app import main`，业务逻辑在分包里。

## 分层目录

```text
config.py            # 全局配置（环境变量、路径、TTL、限流阈值）
data/                # 运行时数据（数据库、媒体），默认全部落后端本机
public/chat.html     # 网页聊天前端

shared/              # 跨层公用工具
api/                 # Flask API 层
bot/                 # Telegram Bot 层
db/                  # SQLite 数据访问层
docs/                # 文档
```

依赖方向是单向的：

```text
api/  ──►  db/  ◄──  bot/
  │                    │
  └────►  shared/  ◄───┘
```

`api/` 和 `bot/` 互不直接依赖；它们之间通过 HTTP（`POST /internal/notify`）通信，避免编译期耦合。`shared/` 只放纯函数，不持有运行时状态。

## `db/` —— 数据访问层

按表/领域拆分。对外暴露的入口在 `db/__init__.py`，调用方写 `from db import user_get, session_create_if_missing` 即可，不需要关心来自哪个子模块。

| 子模块 | 负责的表或领域 |
|---|---|
| `connection.py` | `get_conn`、时间工具、列检测辅助 |
| `schema.py` | 建表 DDL、`init_db`、迁移、`cleanup_old` |
| `users.py` | `users` 表，角色常量 `USER_ROLE_NORMAL/VIP/ADMIN` |
| `settings.py` | 全局 KV（`helplink`、`admin_contact` 等） |
| `pending.py` | 待处理交互（如 `/tokenadd` 等待 Token 私聊） |
| `widgets.py` | 客服入口、归属、在线/离线状态、欢迎文案 |
| `sessions.py` | 客服会话、话题映射、过期清理 |
| `events.py` | 消息事件流水 |
| `bot_bindings.py` | 客户侧 Bot 绑定 |
| `quick_replies.py` | 快速回复 |
| `stats.py` | 来源点击与会话转化统计 |
| `marks.py` | `/valid` `/deal` 客户标记 |
| `media.py` | 媒体资产记录 |

**加新表**：在 `db/` 下新建 `xxx.py` 编写 CRUD，把 DDL 加进 `db/schema.py` 的 `init_db`，把公开函数加进 `db/__init__.py` 再导出。

## `api/` —— Flask API 层

```text
api/
├── app.py              # Flask 实例、路由注册、main()
├── telegram_client.py  # Telegram HTTP 调用、话题创建/删除
├── rate_limit.py       # IP 限流 + 内网 IP 判定（保护 /internal/notify）
├── sse.py              # SSE 订阅者注册表与广播
├── cleanup.py          # 过期会话和媒体清理调度
├── validators.py       # KEY/SOURCE 正则、保留字、错误响应
└── routes/
    ├── health.py       # GET /health
    ├── widget.py       # GET /<key>、GET /widget/<key>
    ├── messages.py     # POST /api/msg/<key>、GET /api/history/<key>
    ├── stream.py       # GET /api/stream/<session_id> (SSE)
    ├── media.py        # GET /api/media/<file_id>
    └── internal.py     # POST /internal/notify（仅本机/内网）
```

各路由模块用 Flask Blueprint 暴露视图函数，由 `api/app.py` 统一注册。模块级状态（限流桶、SSE 订阅者表）放在专门的模块里，便于路由共享和单元测试。

**加新路由**：在 `api/routes/` 下新建文件，定义 Blueprint，把它加进 `api/app.py` 的注册列表。

## `bot/` —— Telegram Bot 层

```text
bot/
├── app.py              # Dispatcher 装配、客户侧 Bot 轮询调度、main()
├── customer_bots.py    # 多客户侧 Bot 注册表与 polling 任务
├── telegram_api.py     # Telegram HTTP 调用、文件下载
├── media.py            # 把 Telegram 文件落到 WEBCHAT_MEDIA_ROOT
├── relay.py            # 话题创建、客服↔客户消息中继、notify_web
├── auth.py             # 用户/角色/入口归属/启用状态校验
├── validators.py       # KEY/SOURCE 校验
├── pending.py          # 私聊待处理动作分发（Token 提交等）
└── handlers/
    ├── basic.py        # /start /help /adminhelp /helplink /admincontact /myinfo /id
    ├── user_keys.py    # /keyadd /keyinfo /keydel
    ├── binding.py      # /tokenadd /welcome /groupbind
    ├── admin_users.py  # /userls /userget /userset /userban /userunban /userkeys /adminkeyinfo /adminkeydel
    ├── admin_entries.py # /kadd /kdel /kls /koff /kon /kmsg
    ├── customer_bots.py # /botadd /botdel /botls
    ├── quick_replies.py # /qradd /qrls /qrdel + 内联回调
    ├── stats.py        # /stats /statdel
    ├── session_cmds.py # /valid /deal /end
    └── messages.py     # 客户私聊消息、客服话题回复、相册笔记合并
```

`bot/app.py` 启动时：

1. 初始化数据库 `db.init_db()`。
2. 注册主 Bot 的 Dispatcher（调用 `handlers/__init__.py` 的 `register_all(dp)`）。
3. 从 `db.bot_bindings` 加载所有客户侧 Bot 绑定，逐个起一个 polling 任务（`customer_bots.activate_customer_bot_binding`）。
4. 启动主 Bot polling。

`handlers/` 内的每个文件只负责一组命令，依赖通过 import 引入：纯校验逻辑找 `auth.py` / `validators.py`，DB 操作找 `db/`，发送消息找 `relay.py`，落媒体找 `media.py`。

**加新命令**：在 `bot/handlers/` 下新建或扩展一个文件，注册到 Dispatcher（在 `handlers/__init__.py` 添加 `register_xxx(dp)` 调用），再在 `/help` 或 `/adminhelp` 文案里补一行。

## `shared/` —— 跨层公用

| 模块 | 用途 |
|---|---|
| `event_payload.py` | 把 DB event 行转换为前端可渲染的 payload（文本、媒体、相册笔记） |
| `session_cleanup.py` | 删除会话记录、关闭/删除 Telegram 话题、清理本地媒体 |

只放**无状态纯函数**和**无 Web/Bot 依赖**的工具。`api/` 和 `bot/` 都会用到它们，不能让它们反过来 import `api/` 或 `bot/`。

## 数据流速览

### 网页访客发消息

```text
浏览器 ─► Nginx ─► api/routes/messages.py: POST /api/msg/<key>
                       │
                       ├─► db/sessions.py 创建/复用 session
                       ├─► api/telegram_client.py 在客服群建话题
                       ├─► db/events.py 写消息事件
                       └─► api/sse.py 广播给该 session 的所有 SSE 订阅者
```

### 客服在 Telegram 话题回复

```text
Telegram ─► bot/handlers/messages.py: 论坛话题回复
                 │
                 ├─► bot/media.py 把媒体落到 WEBCHAT_MEDIA_ROOT
                 ├─► db/events.py 写消息事件
                 └─► bot/relay.py notify_web()
                          └─► HTTP POST /internal/notify
                                  └─► api/routes/internal.py
                                          └─► api/sse.py 广播
```

### 客户侧 Telegram 机器人

每个客户侧 Bot 都是一个独立 polling 任务（`bot/customer_bots.py`），收到客户消息后走 `bot/handlers/messages.py: handle_customer_private_message`，逻辑与网页访客发消息镜像（建话题、写事件、转发给客服群）；客服回复时由 `bot/relay.py` 通过对应客户侧 Bot Token 私聊回推。

## 部署拓扑提示

- 当前默认部署：API 进程、Bot 进程、SQLite、媒体目录都在后端同一台机器，前置 Nginx。
- 前后端跨机房（如后端 SG、前端 HK）时，本次重构保持媒体落在后端 `data/media/`，访客通过 `GET /api/media/<file_id>` 经后端取媒体；把媒体迁到前端机器（NFS/SSHFS 挂载、HTTPS 上传、对象存储）是后续独立优化项，会改 `bot/media.py` 和 `api/routes/media.py`。
- `WEBCHAT_MEDIA_ROOT` 用环境变量覆盖即可，应用代码不区分本地路径还是挂载路径。

## 测试与冒烟

最小冒烟（确认 import 图没坏）：

```bash
python -m compileall api_server.py tg_bot.py config.py api bot db shared
python -c "from api.app import create_app; create_app()"
python -c "import bot.app"
```

完整启动验证：先起 `api_server.py`，`curl /health` 返回 `{"ok": true}`；再起 `tg_bot.py`，日志里能看到主 Bot 和已绑定客户侧 Bot 全部上线。
