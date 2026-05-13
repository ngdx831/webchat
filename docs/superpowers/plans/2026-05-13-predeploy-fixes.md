# 部署前阻塞项修复计划

> **面向 AI 代理的工作说明：** 按任务顺序执行，每个任务先补测试或冒烟脚本，再做最小实现，最后运行指定验证命令。当前不启用子代理；如后续用户明确要求并行执行，再拆分给子代理。

**目标：** 修复部署前审计发现的阻塞问题，让网页客服入口、主 Bot、客户侧 Bot、SSE 通知和 `/kls` 权限链路符合 README 与 docs 的验收口径。

**架构：** 保持现有 Flask API、Telegram Bot、SQLite、静态前端分层不变。优先补齐小而明确的路由、前端状态管理和 Bot 命令逻辑，不引入新服务或大范围重构。

**技术栈：** Python 3.11+、Flask、aiogram 3、SQLite、原生 JavaScript、unittest/pytest。

---

## 文件职责

- 修改 `api/routes/static_assets.py`：新增聊天页静态资源路由，返回 `public/chat.css` 和 `public/chat.js`。
- 修改 `api/routes/__init__.py`：注册静态资源 Blueprint。
- 修改 `api/routes/messages.py`：访客发消息后返回服务端 `event_id`，用于前端去重。
- 修改 `public/chat.js`：修复 token 持久化、后台 SSE、通知触发和首条消息重复显示。
- 修改 `bot/customer_bots.py` 和 `bot/app.py`：重构客户侧 Bot polling，避免同一个 Dispatcher 多次并发 `start_polling`。
- 修改 `bot/relay.py`：补齐 `logger`，并让 Telegram 客户侧会话能收到客服笔记里的媒体。
- 修改 `bot/handlers/admin_entries.py`：实现 `/kls` 不带参数查自己，管理员带 `telegram_user_id` 查他人。
- 修改 `README.md`、`docs/OPERATIONS.md`：已先行更新环境变量和 `/kls` 口径；后续代码完成后再做一次术语校对。
- 新增或修改 `tests/`：覆盖静态资源、会话 token、`/kls` 文本逻辑和客户 Bot polling 静态约束。

## 任务 1：修复聊天页静态资源 404

- [ ] 编写失败测试：用 Flask test client 请求 `/<key>`、`/chat.css`、`/chat.js`，预期三者返回 200，且 CSS/JS 的 Content-Type 正确。
- [ ] 新增 `api/routes/static_assets.py`，只允许返回 `chat.css` 和 `chat.js`，不开放任意文件路径。
- [ ] 在 `api/routes/__init__.py` 注册 Blueprint。
- [ ] 运行 `python -m pytest tests/test_web_static_assets.py -q`，确认通过。

## 任务 2：修复网页会话 token、SSE 和通知链路

- [ ] 编写失败测试或前端静态测试：确认 `sessionId` 和 `session_access_token` 使用同一种持久化策略，浏览器重开后不会拿旧 session 发送空 token。
- [ ] 修改 `api/routes/messages.py`，`event_add` 后保存并返回 `event_id`。
- [ ] 修改 `public/chat.js`：发送成功后把服务端 `event_id` 加入 `seenIds`，避免 SSE replay 重复显示首条访客消息。
- [ ] 修改 `public/chat.js`：页面隐藏时不主动关闭 SSE；只在 `pagehide` 或真正离开页面时关闭连接。
- [ ] 修改 `public/chat.js`：将 `session_access_token` 与 `sessionId` 同步保存；如检测到 session 有值但 token 丢失，则生成新 session，避免 401 卡死。
- [ ] 用 Flask 冒烟脚本复测：首次发送、刷新历史、重复发送、无 token 场景均符合预期。

## 任务 3：重构客户侧 Bot polling

- [ ] 补充静态测试：禁止对同一个全局 Dispatcher 为每个客户 Bot 单独并发 `start_polling`。
- [ ] 评估 aiogram 3 的推荐形态：优先为每个客户 Bot 创建独立 Dispatcher，或集中一次性 `start_polling(main_bot, *customer_bots)`。
- [ ] 选择最小改动方案并实现：热绑定时启动独立客户 Bot polling，不影响主 Bot polling；删除绑定时能取消对应任务并关闭 session。
- [ ] 保留现有 `binding_for_bot`、`CUSTOMER_BOTS_BY_BINDING_ID` 的查询语义，避免破坏客服回复回推。
- [ ] 运行 `python -m pytest tests/test_customer_bot_polling_static.py -q` 和 `python -m compileall ...`。

## 任务 4：修复客服回推和媒体链路缺口

- [ ] 在 `bot/relay.py` 增加模块级 `logger = logging.getLogger(__name__)`。
- [ ] 让 `send_event_to_customer(..., kind="note")` 在发送标题正文后，继续遍历 `event["media"]`，按 photo/video/document 发送媒体。
- [ ] 对缺失本地文件的媒体做降级提示，不让单个媒体失败中断整条笔记。
- [ ] 增加轻量单元测试或静态测试，确认 `note` 分支引用 `event["media"]` 并覆盖三类媒体发送路径。

## 任务 5：调整 `/kls` 命令权限与输出

- [ ] 编写命令逻辑测试或提取纯函数测试：普通用户 `/kls` 只返回自己的所有 key；普通用户带参数被拒绝；管理员 `/kls <telegram_user_id>` 返回指定账号 key。
- [ ] 修改 `bot/handlers/admin_entries.py`：删除不可达旧代码，把 `/kls` 做成明确的用户入口查询命令。
- [ ] 保留 `/userkeys <telegram_user_id>`，作为管理员兼容命令。
- [ ] 更新 `/help` 和 `/adminhelp` 文案，让 `/kls` 的参数规则清楚。

## 任务 6：最终验证

- [ ] 运行 `python -m pytest -q`。
- [ ] 运行 `python -m unittest discover -s tests`。
- [ ] 运行 `python -m compileall api_server.py tg_bot.py config.py api bot db shared`。
- [ ] 用 Flask test client 做部署前冒烟：VIP 入口 HTML/JS/CSS、普通用户 `WEB_DISABLED`、消息发送、history token、SSE replay、媒体鉴权。
- [ ] 在有真实 Telegram 测试环境时，手动验证：主 Bot `/start`、`/kls`、客户侧 Bot `/start link123`、网页访客发消息建话题、客服回复推送到网页和 Telegram 客户侧。

## 风险与回滚

- 客户侧 Bot polling 是最大风险点。实现时保持旧的数据表和绑定查询不变，只替换运行时调度方式。
- `WEBCHAT_TOKEN_KEY` 不能随意更换；部署前需要确认生产环境已固定设置。
- 前端 token 持久化会增加 XSS 后果，因此本轮同时保留 CSP、`textContent` 渲染和媒体 URL 协议白名单。
- 如果客户侧 Bot polling 改动影响主 Bot，可先回滚任务 3，保留其他修复上线。
