# API 文档

本文档描述 `api_server.py` 提供的 HTTP API。默认服务地址为 `http://127.0.0.1:5055`，生产环境通常由 Nginx 反向代理到公网域名。

## 通用约定

除客户页面入口和媒体接口外，响应统一使用 JSON。成功响应一般包含：

```json
{
  "ok": true
}
```

失败响应一般包含：

```json
{
  "ok": false,
  "error": "ERROR_CODE"
}
```

常见错误码：

| 错误码 | HTTP 状态码 | 说明 |
| --- | --- | --- |
| `BAD_KEY` | 400 | `key` 为空、格式不合法，或使用了保留字。 |
| `KEY_NOT_FOUND` | 404 | 没有找到对应客服入口。 |
| `WEB_DISABLED` | 403 | 入口存在，但所属用户不能使用网页客服能力。普通用户或被禁用用户会返回该错误。 |
| `BAD_JSON` | 400 | 请求体不是合法 JSON。 |
| `EMPTY_TEXT` | 400 | 消息文本为空。 |
| `NO_SESSION` | 400 | 缺少 `session_id`。 |
| `RATE_LIMIT` | 429 | 同一 IP 发送消息过快。 |
| `TG_SEND_FAILED` | 502 | 消息发送到 Telegram 失败。 |
| `INTERNAL_ERROR` | 500 | 服务端未捕获异常。 |

`key` 格式规则：

- 长度 1 到 32 位。
- 只能包含英文字母、数字、下划线和短横线。
- 必须以英文字母或数字开头。
- 不能使用 `api`、`widget`、`internal`、`health`、`webchat`、`static`、`assets`、`favicon.ico`、`robots.txt`，也不能以 `api` 开头。

## 网页入口权限

网页客服能力只对 VIP 和管理员名下的入口开放，覆盖以下路径：

- `GET /{key}`
- `GET /widget/{key}`
- `POST /api/msg/{key}`
- `GET /api/history/{key}`
- `GET /api/stream/{session_id}`

权限判断以入口的 `owner_user_id` 和 `users.role` 为准：

| 所属用户状态 | 结果 |
| --- | --- |
| `vip` 或 `admin` 且未禁用 | 允许访问网页客服入口、配置、消息发送、历史消息和 SSE。 |
| `normal` | 返回 403 `WEB_DISABLED`。普通用户可继续使用客户侧 Telegram 机器人能力。 |
| 已禁用 | 返回 403 `WEB_DISABLED`。 |
| 入口不存在 | 返回 404 `KEY_NOT_FOUND`。 |

旧数据中 `owner_user_id` 为空的入口无法通过网页权限校验，会返回 403 `WEB_DISABLED`，建议管理员后续补齐入口归属。

## 健康检查

### `GET /health`

检查 API 服务是否存活。

响应示例：

```json
{
  "ok": true
}
```

## 客户页面入口

### `GET /{key}`

返回网页聊天入口 `public/chat.html`。页面会从浏览器地址读取 `key` 和 `src`，再调用 `/widget/{key}` 获取入口配置。

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `src` | 否 | 来源编码。该参数由前端继续传给 `/widget/{key}` 和 `/api/msg/{key}`。 |

说明：

- 该路由返回 HTML，不返回 JSON。
- `key` 必须符合本文档的 `key` 格式规则。
- 入口所属用户必须是未禁用的 VIP 或管理员；普通用户或已禁用用户返回 403 `WEB_DISABLED`。
- `/chat/{key}` 和 `/api/widget/{key}` 不再作为入口使用。

### `GET /widget/{key}` 作为挂件地址

当浏览器或 iframe 直接访问 `GET /widget/{key}`，且请求不是前端配置请求时，接口会返回 `public/chat.html`，可作为 iframe 挂件地址使用。页面脚本会从 `/widget/{key}` 路径中识别真实 `key`，再携带 `visitor_id` 调用同一路径获取 JSON 配置。

iframe 嵌入不再默认返回 `X-Frame-Options: DENY`，页面 CSP 也不再声明 `frame-ancestors 'none'`。

## 获取客服入口信息

### `GET /widget/{key}`

当前端以配置请求方式调用，例如携带 `visitor_id`，该接口返回客服入口配置、自动回复和来源点击统计。该接口不会创建人工客服会话；客户真正发送人工消息时才创建会话和客服群话题。

入口所属用户必须是未禁用的 VIP 或管理员；普通用户或已禁用用户返回 403 `WEB_DISABLED`。

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `src` | 否 | 来源编码。存在且合法时记录来源点击。 |
| `visitor_id` | 否 | 网页访客 ID。为空时服务端返回新的 `visitor_id`。 |

响应示例：

```json
{
  "ok": true,
  "key": "yaoyao",
  "display_name": "客服瑶瑶",
  "visitor_id": "8fd4fbd4b9874d59a4df26d9f23d13b1",
  "source_code": "abc",
  "enabled": 1,
  "offline_msg": "",
  "offline_at": "",
  "waiting_hint": "客服可能正在处理其他咨询，回复不及时请稍等几分钟，我们会尽快回复您。",
  "quick_replies": [
    {
      "id": 1,
      "title": "价格",
      "answer": "价格请联系客服确认。"
    }
  ]
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `display_name` | 网页端展示的客服名称。 |
| `visitor_id` | 访客 ID，后续发送消息时应带回。 |
| `source_code` | 合法来源编码；无来源时为空。 |
| `enabled` | `1` 表示在线，`0` 表示离线。 |
| `offline_msg` | 离线提示文案。 |
| `offline_at` | 最近一次设置离线的时间。 |
| `waiting_hint` | 展示给客户的等待提示文案。 |
| `quick_replies` | 自动回复列表。点击自动回复不创建会话，也不进入来源统计。 |

## 发送访客消息

### `POST /api/msg/{key}`

把网页访客消息发送到对应 Telegram 论坛话题。首次发送时，如果当前会话还没有话题，系统会自动创建话题。

入口所属用户必须是未禁用的 VIP 或管理员；普通用户或已禁用用户返回 403 `WEB_DISABLED`。

请求体：

```json
{
  "session_id": "20f8c5e4a9f84f31b27a41db45b01aef",
  "visitor_id": "8fd4fbd4b9874d59a4df26d9f23d13b1",
  "source_code": "abc",
  "text": "你好，我想咨询一下。"
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `text` | 是 | 访客消息文本。 |
| `session_id` | 否 | 会话 ID。为空时会自动生成，但前端通常应该传入已有值。 |
| `visitor_id` | 否 | 访客 ID。用于来源会话转化去重。 |
| `source_code` | 否 | 来源编码。存在时记录来源会话转化。 |

响应示例：

```json
{
  "ok": true,
  "session_id": "20f8c5e4a9f84f31b27a41db45b01aef"
}
```

## 获取历史消息

### `GET /api/history/{key}`

获取指定会话最近的历史事件，最多返回 100 条；事件总数超过该上限时响应里 `truncated` 为 `true`，前端会提示更早的消息已不可见。历史事件会转换成和 SSE `msg` 事件一致的前端 payload，因此刷新页面后仍可直接渲染客服发过的图片、视频、文档和相册笔记。

入口所属用户必须是未禁用的 VIP 或管理员；普通用户或已禁用用户返回 403 `WEB_DISABLED`。

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `session_id` | 是 | 会话 ID。 |

响应示例：

```json
{
  "ok": true,
  "truncated": false,
  "events": [
    {
      "id": 1,
      "session_id": "20f8c5e4a9f84f31b27a41db45b01aef",
      "role": "user",
      "kind": "text",
      "text": "你好",
      "caption": "",
      "file_id": "",
      "file_name": "",
      "from_name": "",
      "local_path": "",
      "media_json": "",
      "created_at": "2026-01-01T10:00:00"
    }
  ]
}
```

事件字段说明：

| 字段 | 说明 |
| --- | --- |
| `role` | 消息角色：`user` 表示访客，`agent` 表示客服，`system` 表示系统。 |
| `kind` | 消息类型：`text`、`photo`、`video`、`document`、`media`、`note`。 |
| `text` | 文本内容。 |
| `caption` | 媒体说明文字。 |
| `file_id` | Telegram 文件 ID。 |
| `from_name` | 客服在 Telegram 中的显示名。 |
| `local_path` | 本地媒体相对路径。 |
| `media_json` | 原始相册媒体 JSON，保留用于兼容旧前端。 |
| `media_url` | 媒体访问地址，通常为 `/api/media/{file_id}`。 |
| `media_expired` | 媒体是否已经过期或本地文件是否已经删除。 |
| `media` | `note` 类型的媒体列表，元素包含 `type`、`file_id`、`local_path`、`media_url` 和 `media_expired`。 |
| `title` / `body` | `note` 类型的标题和正文。 |

## 实时消息流

### `GET /api/stream/{session_id}`

使用 SSE 订阅客服回复。

服务端会根据 `session_id` 找到所属入口，并执行同样的网页权限检查。普通用户或已禁用用户的会话返回 403 `WEB_DISABLED`。

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `since_id` | 否 | 断线重连时使用，只补发 ID 大于该值的事件。 |

服务端会发送两类事件：

| 事件名 | 说明 |
| --- | --- |
| `msg` | 新消息事件。 |
| `ping` | 心跳事件，每 30 秒发送一次。 |

前端示例：

```javascript
const source = new EventSource(`/api/stream/${sessionId}`);

source.addEventListener("msg", (event) => {
  const message = JSON.parse(event.data);
  console.log("客服消息：", message);
});

source.addEventListener("ping", () => {
  console.log("stream alive");
});
```

网页聊天页会基于该 SSE 流实现浏览器通知：访客主动发送消息后触发通知权限请求；当页面处于后台、浏览器支持 Notification API、用户已授权通知，且 SSE 收到 `role: "agent"` 的客服消息时弹出通知。历史消息接口返回的旧事件只用于渲染，不触发通知。生产环境通常需要 HTTPS 域名才能使用浏览器通知，`localhost` 调试除外。

`note` 类型事件示例：

```json
{
  "role": "agent",
  "kind": "note",
  "title": "商品照片",
  "body": "这是刚拍的实图",
  "from_name": "客服瑶瑶",
  "media": [
    {
      "type": "photo",
      "file_id": "AgACAgUAAxkBA...",
      "local_path": "media/202601/file.jpg",
      "media_url": "/api/media/AgACAgUAAxkBA...",
      "media_expired": false
    }
  ]
}
```

## 获取媒体文件

### `GET /api/media/{file_id}`

获取 Telegram 媒体文件。接口会优先查找本地已下载文件，找到后重定向到本地静态路径；媒体已过期时返回占位图；没有本地记录时再尝试重定向到 Telegram 文件地址。

可能响应：

- `302`：重定向到本地媒体或 Telegram 文件地址。
- `410`：媒体已过期，返回占位图。
- `400 BAD_FILE_ID`：文件 ID 为空。
- `500 GET_FILE_FAILED`：无法从 Telegram 获取文件。

## 内部通知接口

### `POST /internal/notify`

该接口由 `tg_bot.py` 调用，用来把 Telegram 客服回复通知给 Flask SSE 订阅者。

请求体：

```json
{
  "session_id": "20f8c5e4a9f84f31b27a41db45b01aef",
  "event": {
    "role": "agent",
    "kind": "text",
    "text": "您好，请问需要了解什么？",
    "from_name": "客服瑶瑶"
  }
}
```

安全要求：

- 只允许本机或内网访问；Flask 层会校验 `request.remote_addr`。
- 如果请求来自本机或内网可信反代，并带有 `X-Forwarded-For` 或 `X-Real-IP`，Flask 层会继续校验真实客户端 IP，公网客户端会返回 403 `FORBIDDEN`。
- 不要通过公网暴露。
- 如果必须经过 Nginx，请对 `/internal/` 做 IP 白名单或直接返回 403。
