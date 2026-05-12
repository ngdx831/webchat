# 数据库说明

项目使用 `webchat.db` 存储用户、全局设置、待处理操作、客服入口、访客会话和聊天事件。数据库表会在代码运行时自动创建。

当前实现会兼容旧版本数据库字段，并在启动服务时尝试补齐缺失列；但本次重构本身不要求保留旧地址或旧数据迁移流程，部署新环境时可以直接按当前表结构初始化。

## `users`

Telegram 用户表。用户首次发送 `/start` 或使用需要身份识别的命令时会写入；`ADMIN_IDS` 中的用户会同步为管理员。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `telegram_user_id` | `INTEGER` | Telegram 用户 ID，主键。 |
| `username` | `TEXT` | Telegram 用户名。 |
| `display_name` | `TEXT` | 展示名，优先来自 Telegram 姓名。 |
| `role` | `TEXT` | 用户角色：`normal`、`vip` 或 `admin`。 |
| `enabled` | `INTEGER` | 是否启用：`1` 启用，`0` 禁用。 |
| `vip_until` | `TEXT` | VIP 到期时间预留字段，当前权限判断主要看 `role`。 |
| `created_at` / `updated_at` | `TEXT` | 创建和更新时间，UTC ISO 格式。 |

角色限制：

| 角色 | Key 数量 | 说明 |
| --- | --- | --- |
| `normal` | 1 个 | 可管理自己的入口、客服群、客户机器人和欢迎文案；网页客服能力关闭。 |
| `vip` | 5 个 | 可使用网页客服入口、快速回复和来源统计。 |
| `admin` | 不限制 | 可管理全部用户和入口。 |

## `settings`

全局设置表，对应设计计划里的 `system_settings`。当前代码中的真实表名为 `settings`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `key` | `TEXT` | 设置项名称，主键。 |
| `value` | `TEXT` | 设置值。 |
| `updated_at` | `TEXT` | 最近更新时间，UTC ISO 格式。 |

目前用于保存 `/helplink` 和 `/admincontact` 设置，后续全局开关也可复用这张表。

## `pending_actions`

待处理操作表，用于保存需要用户下一条私聊消息继续完成的流程，例如 `/tokenadd` 后等待用户发送客户侧 Bot Token。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `telegram_user_id` | `INTEGER` | 发起操作的 Telegram 用户 ID，主键。 |
| `action` | `TEXT` | 待处理动作名称，例如 `tokenadd`。 |
| `key` | `TEXT` | 关联的客服入口。 |
| `payload` | `TEXT` | 预留负载 JSON 或文本。 |
| `expires_at` | `TEXT` | 过期时间。 |
| `created_at` | `TEXT` | 创建时间。 |

## `widgets`

客服入口配置表。一个 `key` 对应一个网页入口和一个 Telegram 论坛群。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `key` | `TEXT` | 入口标识，主键。旧库可能使用 `k` 字段，代码会自动兼容。 |
| `owner_user_id` | `INTEGER` | 入口所属 Telegram 用户 ID。为空时按旧数据兼容处理。 |
| `forum_chat_id` | `INTEGER` | Telegram 超级群 ID。 |
| `display_name` | `TEXT` | 网页端展示的客服名称。 |
| `enabled` | `INTEGER` | 在线状态：`1` 在线，`0` 离线。 |
| `offline_msg` | `TEXT` | 离线提示文案。 |
| `offline_at` | `TEXT` | 最近一次设置离线的时间。 |
| `welcome_text` | `TEXT` | 客户侧 Telegram 机器人 `/start` 欢迎文案。 |

旧库中可能存在 `created_ts`、`updated_ts` 等字段。当前代码会尽量写入这些字段，但不依赖它们。

## `sessions`

访客会话表。一个访客会话对应 Telegram 里的一个论坛话题。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `session_id` | `TEXT` | 会话 ID，主键。 |
| `key` | `TEXT` | 所属客服入口。 |
| `forum_chat_id` | `INTEGER` | 对应 Telegram 超级群 ID。 |
| `thread_id` | `INTEGER` | Telegram 论坛话题 ID。首次发送消息时创建并写入。 |
| `channel` | `TEXT` | 会话渠道：`web` 或 `telegram`。 |
| `source_code` | `TEXT` | 来源编码；无来源时为空。 |
| `visitor_id` | `TEXT` | 网页访客 ID 或 Telegram 用户 ID。 |
| `customer_chat_id` | `INTEGER` | Telegram 客户私聊 ID，仅客户机器人会话使用。 |
| `bot_binding_id` | `INTEGER` | 客户机器人绑定 ID，仅客户机器人会话使用。 |
| `customer_status` | `TEXT` | 客户状态：`none`、`valid` 或 `deal`。 |
| `marked_by` | `TEXT` | 最近一次标记客服。 |
| `marked_at` | `TEXT` | 最近一次标记时间。 |
| `created_at` | `TEXT` | 会话创建时间，UTC ISO 格式。 |
| `last_activity_at` | `TEXT` | 最近一次客户或客服消息时间，UTC ISO 格式。系统提示不会刷新这个时间。 |

## `events`

聊天事件表。访客消息、客服消息、媒体消息和相册笔记都写入这张表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `INTEGER` | 自增主键。 |
| `session_id` | `TEXT` | 所属会话 ID。 |
| `role` | `TEXT` | 消息角色：`user`、`agent` 或 `system`。 |
| `kind` | `TEXT` | 消息类型：`text`、`photo`、`video`、`document`、`media`、`note`。 |
| `text` | `TEXT` | 文本内容。 |
| `caption` | `TEXT` | 媒体说明文字。 |
| `file_id` | `TEXT` | Telegram 文件 ID。 |
| `file_name` | `TEXT` | 文件名。当前主要为兼容字段。 |
| `from_name` | `TEXT` | 客服在 Telegram 中的显示名。 |
| `local_path` | `TEXT` | 媒体文件本地相对路径，例如 `webchat/media/202601/file.jpg`。 |
| `media_json` | `TEXT` | `note` 类型的媒体列表 JSON。 |
| `created_at` | `TEXT` | 事件创建时间，UTC ISO 格式。 |

`note` 类型用于合并 Telegram 相册。`text` 字段保存标题和正文 JSON，`media_json` 保存相册里的媒体列表。

示例：

```json
{
  "title": "商品照片",
  "body": "这是刚拍的实图"
}
```

## `bot_bindings`

客户侧 Telegram 机器人绑定表。一个 `key` 可以绑定一个或多个额外机器人。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `INTEGER` | 自增主键。 |
| `key` | `TEXT` | 所属客服入口。 |
| `owner_user_id` | `INTEGER` | 绑定所属 Telegram 用户 ID。 |
| `bot_token` | `TEXT` | 客户侧 Bot Token。 |
| `bot_username` | `TEXT` | 机器人用户名。 |
| `enabled` | `INTEGER` | 是否启用。 |
| `created_at` / `updated_at` | `TEXT` | 创建和更新时间。 |

## `quick_replies`

快速回复表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `INTEGER` | 自增主键。 |
| `key` | `TEXT` | 所属客服入口。 |
| `title` | `TEXT` | 按钮标题。 |
| `answer` | `TEXT` | 自动回复内容。 |
| `sort_order` | `INTEGER` | 排序值。 |
| `enabled` | `INTEGER` | 是否启用。 |

## `source_clicks`

来源点击表。有 `src` 或 `/start` 参数时记录，不要求客户已经进入人工会话。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `INTEGER` | 自增主键。 |
| `key` | `TEXT` | 所属客服入口。 |
| `source_code` | `TEXT` | 来源编码。 |
| `channel` | `TEXT` | 来源渠道：`web` 或 `telegram`。 |
| `visitor_id` | `TEXT` | 网页访客 ID 或 Telegram 用户 ID。 |
| `clicked_at` | `TEXT` | 点击记录时间。 |

## `source_sessions`

来源会话转化表。客户真正发送人工咨询消息后记录，用于统计来源点击中有多少人进入了会话。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `INTEGER` | 自增主键。 |
| `key` | `TEXT` | 所属客服入口。 |
| `source_code` | `TEXT` | 来源编码。 |
| `channel` | `TEXT` | 来源渠道：`web` 或 `telegram`。 |
| `visitor_id` | `TEXT` | 网页访客 ID 或 Telegram 用户 ID。 |
| `session_id` | `TEXT` | 对应人工客服会话 ID。 |
| `created_at` | `TEXT` | 首次进入人工会话的时间。 |

## `customer_marks`

客户标记表。客服在会话话题内使用 `/valid` 或 `/deal` 后写入。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `INTEGER` | 自增主键。 |
| `session_id` | `TEXT` | 对应人工客服会话 ID。 |
| `key` | `TEXT` | 所属客服入口。 |
| `source_code` | `TEXT` | 来源编码；无来源时为空。 |
| `channel` | `TEXT` | 来源渠道：`web` 或 `telegram`。 |
| `mark` | `TEXT` | 客户标记：`valid` 或 `deal`。 |
| `marked_by` | `TEXT` | 执行标记的客服名称。 |
| `marked_at` | `TEXT` | 标记时间。 |

`/statdel <key> [来源]` 只清理统计表数据，并清空相关会话上的来源统计字段，不删除聊天记录、会话、媒体记录或客服群话题。

## `media_assets`

本地媒体文件记录表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `INTEGER` | 自增主键。 |
| `session_id` | `TEXT` | 所属会话。 |
| `file_id` | `TEXT` | Telegram 文件 ID。 |
| `kind` | `TEXT` | `photo`、`video` 或 `document`。 |
| `local_path` | `TEXT` | 本地相对路径。 |
| `created_at` | `TEXT` | 落盘时间。 |
| `expires_at` | `TEXT` | 过期时间。 |
| `deleted_at` | `TEXT` | 实际删除文件时间；为空表示文件仍可用。 |

## 数据保留策略

客服会话、聊天事件和媒体会按配置定期清理：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `SESSION_TTL_SECONDS` | `5184000` | 会话最大保留时间，默认约 2 个月。 |
| `SESSION_IDLE_TTL_SECONDS` | `5184000` | 最后一次对话后的空闲保留时间，默认约 2 个月。 |
| `MEDIA_TTL_SECONDS` | `259200` | 本地媒体文件保留时间，默认约 3 天。 |
| `EVENT_TTL_SECONDS` | `5184000` | 兼容旧配置名；事件跟随会话一起删除。 |

清理逻辑在 `api/db_helpers.get_conn()` 获取数据库连接时触发（实现位于 `api/cleanup.py`）。过期媒体只删除本地文件并写入 `deleted_at`，不删除聊天事件；过期会话会尝试删除或关闭对应 Telegram 客服群话题，然后删除事件和会话记录。统计表不会被自动清理。

## 媒体路径约定

客服媒体：

- 落盘目录：`WEBCHAT_MEDIA_ROOT`
- 公开路径：`/webchat/media/YYYYMM/file.ext`
- 数据库存储：`webchat/media/YYYYMM/file.ext`

`/api/media/{file_id}` 会先查找本地 `local_path`；媒体已过期时返回占位图；没有本地记录时才回退到 Telegram 文件地址。

## 备份建议

至少备份这些内容：

- `DB_PATH` 指向的数据库文件（默认 `data/webchat.db`）
- `WEBCHAT_MEDIA_ROOT` 指向的媒体目录（默认 `data/media`）

如果数据量不大，可以先停止服务再复制文件。若需要不停机备份，建议使用 SQLite 的 `.backup` 命令。

示例：

```bash
sqlite3 data/webchat.db ".backup 'backup/webchat.db'"
```

恢复时先停止 `api_server.py` 和 `tg_bot.py`，再替换数据库和媒体目录。

## 修改数据的注意事项

- 不要在服务运行时手动改表结构。
- 修改 `widgets` 配置优先使用 Telegram 命令：用户侧使用 `/keyadd`、`/groupbind`、`/welcome`，管理员侧使用 `/kadd` 或 `/adminkeydel` 等命令。
- 修改用户角色和禁用状态优先使用 `/userset`、`/userban`、`/userunban`。
- 删除会话优先在对应 Telegram 话题中使用 `/end`，这样会同步删除或关闭客服群话题、清理数据库和本地媒体。
