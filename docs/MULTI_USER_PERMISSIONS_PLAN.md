# 多用户权限实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟进进度。

**目标：** 将 WebChat 改造成多用户分权限客服系统，支持普通用户、VIP 用户和管理员按权限管理自己的 `key`、客户机器人、客服群、欢迎文案、快捷回复和统计。

**架构：** 在现有 SQLite 数据模型上加入用户、所有权和全局配置。所有 Telegram 命令和网页 API 统一经过用户权限判断。客户机器人继续使用当前动态 polling 机制，绑定成功后立即生效，重启后从数据库恢复。

**技术栈：** Python、Flask、aiogram、SQLite、unittest。

---

## 文档关系

- 产品和权限规则见 `docs/MULTI_USER_PERMISSIONS_DESIGN.md`。
- 本文档只描述实施步骤、文件范围、测试策略和交付顺序。

## 文件职责

预计修改或新增以下文件：

- `db.py`：新增用户、全局设置、pending action 的表结构和数据访问函数；为 `widgets`、`bot_bindings` 增加 owner 字段兼容迁移。
- `tg_bot.py`：改造命令权限、用户注册、key 管理、token 绑定流程、客服群绑定流程、管理员命令和动态客户机器人加载。
- `api_server.py`：为网页入口和 API 增加用户角色校验，限制普通用户网页客服能力。
- `config.py`：保留 `ADMIN_IDS` 作为管理员初始化来源。
- `tests/`：新增多用户权限、命令权限、网页权限、token 流程和管理员命令测试。
- `docs/API.md`、`docs/DATABASE.md`、`docs/OPERATIONS.md`：实现完成后补充最终行为说明。

## 阶段 1：数据模型和用户基础

### 任务 1.1：新增用户表和权限常量

**文件：**

- 修改：`db.py`
- 测试：`tests/test_multi_user_permissions.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- `init_db` 后存在 `users` 表。
- `user_upsert_from_telegram` 可以创建普通用户。
- `ADMIN_IDS` 对应用户能被识别为管理员。
- 用户角色支持 `normal`、`vip`、`admin`。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_multi_user_permissions
```

预期：缺少用户相关函数或断言失败。

- [ ] **步骤 3：实现最少代码**

在 `db.py` 增加：

- `USER_ROLE_NORMAL = "normal"`
- `USER_ROLE_VIP = "vip"`
- `USER_ROLE_ADMIN = "admin"`
- `user_get(conn, telegram_user_id)`
- `user_upsert_from_telegram(conn, telegram_user_id, username, display_name, default_role="normal")`
- `user_set_role(conn, telegram_user_id, role)`
- `user_set_enabled(conn, telegram_user_id, enabled)`
- `user_list(conn, role="", enabled_only=False, limit=100)`

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_multi_user_permissions
```

预期：新增测试通过。

### 任务 1.2：给 key 和客户机器人绑定所有权

**文件：**

- 修改：`db.py`
- 测试：`tests/test_multi_user_permissions.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- `widgets` 支持 `owner_user_id`。
- `bot_bindings` 支持 `owner_user_id`。
- 创建 `key` 时能记录 owner。
- 列出用户自己的 `key` 时不会返回其他用户数据。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_multi_user_permissions
```

- [ ] **步骤 3：实现最少代码**

在 `db.py` 增加或调整：

- `widget_add(..., owner_user_id=None)`。
- `widget_list_by_owner(conn, owner_user_id)`。
- `widget_count_by_owner(conn, owner_user_id)`。
- `widget_get_owned(conn, key, owner_user_id)`。
- `bot_binding_add(..., owner_user_id=None)`。
- `bot_binding_list_by_owner(conn, owner_user_id, key="")`。

保留旧函数签名兼容现有测试和管理员场景。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_multi_user_permissions
```

## 阶段 2：用户命令和 key 数量限制

### 任务 2.1：实现用户上下文和权限判断

**文件：**

- 修改：`tg_bot.py`
- 测试：`tests/test_tg_bot_users.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- 非管理员首次 `/start` 会创建普通用户。
- `ADMIN_IDS` 用户 `/start` 后是管理员。
- 禁用用户执行普通命令时被拒绝。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_tg_bot_users
```

- [ ] **步骤 3：实现最少代码**

在 `tg_bot.py` 增加辅助函数：

- `current_user_from_message(conn, msg)`。
- `is_vip_or_admin(user)`。
- `is_admin_user(user)`。
- `require_enabled_user(user)`。
- `require_owned_key(conn, user, key)`。
- `key_limit_for_role(role)`。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_tg_bot_users
```

### 任务 2.2：新增 `/keyadd`、`/keyinfo`、`/keydel`、`/myinfo`

**文件：**

- 修改：`tg_bot.py`
- 测试：`tests/test_tg_bot_users.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- 普通用户最多创建 1 个 `key`。
- VIP 用户最多创建 5 个 `key`。
- 管理员不限制 `key` 数量。
- 用户不能查看或删除其他用户的 `key`。
- `/myinfo` 显示角色、key 数量、key 概览，不显示统计。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_tg_bot_users
```

- [ ] **步骤 3：实现最少代码**

新增命令：

- `/keyadd <key> <显示名>`
- `/keyinfo <key>`
- `/keydel <key>`
- `/myinfo`

调整：

- `/kls` 不再允许无参数列出所有 `key`。
- 保留管理员查看全部的能力到后续 `/userkeys` 和 `/adminkeyinfo`。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_tg_bot_users
```

## 阶段 3：功能权限控制

### 任务 3.1：限制网页客服入口

**文件：**

- 修改：`api_server.py`、`db.py`
- 测试：`tests/test_api_permissions.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- 普通用户的 `GET /widget/<key>` 返回 `WEB_DISABLED` 或等价错误。
- VIP 用户的 `GET /widget/<key>` 正常返回。
- 被禁用用户的 `key` 网页不可用。
- 不存在的 `key` 仍返回 `KEY_NOT_FOUND`。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_api_permissions
```

- [ ] **步骤 3：实现最少代码**

在 `api_server.py` 中：

- 查询 `widget` 后继续查询 owner 用户。
- `normal` 或 disabled owner 禁止网页客服。
- 对 `/api/msg/<key>`、`/api/history/<key>`、`/<key>`、`/widget/<key>` 应用同样规则。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_api_permissions
```

### 任务 3.2：限制统计和快捷回复

**文件：**

- 修改：`tg_bot.py`
- 测试：`tests/test_tg_bot_users.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- 普通用户执行 `/stats`、`/statdel`、`/qradd`、`/qrls`、`/qrdel` 时被拒绝。
- VIP 用户可以管理自己 `key` 的统计和快捷回复。
- VIP 用户不能操作其他用户的 `key`。
- 管理员可以操作任意 `key`。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_tg_bot_users
```

- [ ] **步骤 3：实现最少代码**

调整现有命令：

- `/stats <key> [来源]`
- `/statdel <key> [来源]`
- `/qradd <key> <标题>|<答案>`
- `/qrls <key>`
- `/qrdel <key> <编号>`

每个命令先执行用户身份、角色和 key 所有权校验。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_tg_bot_users
```

## 阶段 4：token 绑定和客服群绑定

### 任务 4.1：实现 pending action 表

**文件：**

- 修改：`db.py`
- 测试：`tests/test_pending_actions.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- 创建 pending action。
- 按用户读取未过期 pending action。
- 完成后删除 pending action。
- 过期 action 不再生效。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_pending_actions
```

- [ ] **步骤 3：实现最少代码**

在 `db.py` 增加：

- `pending_action_set(conn, telegram_user_id, action, key="", payload="", ttl_seconds=300)`。
- `pending_action_get(conn, telegram_user_id)`。
- `pending_action_clear(conn, telegram_user_id)`。
- `pending_action_cleanup(conn)`。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_pending_actions
```

### 任务 4.2：将 `/botadd` 改为 `/tokenadd <key>` 交互流程

**文件：**

- 修改：`tg_bot.py`
- 测试：`tests/test_tg_bot_runtime.py`、`tests/test_tg_bot_users.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- `/tokenadd <key>` 创建 `await_token` pending action。
- 用户下一条私聊消息作为 token 处理。
- token 验证成功后写入 `bot_bindings`，owner 正确。
- token 绑定成功后立即启动客户机器人 polling。
- 普通用户、VIP 用户和管理员都可以给自己有权限的 `key` 绑定 token。
- 用户不能给别人的 `key` 绑定 token。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_tg_bot_runtime tests.test_tg_bot_users
```

- [ ] **步骤 3：实现最少代码**

调整：

- 新增 `/tokenadd <key>`。
- 将旧 `/botadd <key> <bot_token> [bot_username]` 标记为管理员兼容命令，或直接提示改用 `/tokenadd`。
- 在普通消息处理入口优先检查 pending action。
- token 处理成功后调用现有 `activate_customer_bot_binding`。
- 成功或失败后清理 pending action。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_tg_bot_runtime tests.test_tg_bot_users
```

### 任务 4.3：实现 `/groupbind <key>`

**文件：**

- 修改：`tg_bot.py`、`db.py`
- 测试：`tests/test_tg_bot_group_bind.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- `/groupbind <key>` 只能在 supergroup 中使用。
- 绑定时读取当前 `chat.id`，不要求手动输入群 ID。
- 用户只能把自己的 `key` 绑定到当前群。
- 管理员可以绑定任意 `key`。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_tg_bot_group_bind
```

- [ ] **步骤 3：实现最少代码**

新增 `/groupbind <key>` 命令：

- 校验当前群类型。
- 校验用户和 `key` 所有权。
- 更新 `widgets.forum_chat_id`。

第一版可先不实现进群按钮跳转，确保手动绑定稳定。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_tg_bot_group_bind
```

## 阶段 5：欢迎文案、帮助链接和 help

### 任务 5.1：实现全局设置

**文件：**

- 修改：`db.py`、`tg_bot.py`
- 测试：`tests/test_settings_and_help.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- 管理员可以设置 `help_link`。
- 管理员可以设置 `admin_contact`。
- 非管理员不能修改全局设置。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_settings_and_help
```

- [ ] **步骤 3：实现最少代码**

新增：

- `setting_get(conn, key, default="")`
- `setting_set(conn, key, value)`
- `/helplink <URL>`
- `/admincontact <联系方式文本>`

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_settings_and_help
```

### 任务 5.2：实现自定义欢迎文案

**文件：**

- 修改：`db.py`、`tg_bot.py`
- 测试：`tests/test_settings_and_help.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- `/welcome <key>` 创建 `await_welcome` pending action。
- 用户下一条私聊消息保存为该 `key` 的欢迎文案。
- 客户侧机器人 `/start` 显示该欢迎文案和全局帮助链接。
- 普通用户客户机器人 `/start` 不显示快捷回复按钮。
- VIP 用户客户机器人 `/start` 显示快捷回复按钮。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_settings_and_help
```

- [ ] **步骤 3：实现最少代码**

调整：

- `widgets` 增加 `welcome_text`。
- 新增 `/welcome <key>`。
- 客户侧机器人 `customer_cmd_start` 读取 `welcome_text` 和 `help_link`。
- 快捷回复按钮显示前校验 owner 角色。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_settings_and_help
```

### 任务 5.3：按身份显示 `/help` 和 `/adminhelp`

**文件：**

- 修改：`tg_bot.py`
- 测试：`tests/test_settings_and_help.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- 普通用户 `/help` 显示普通命令和管理员联系方式。
- VIP 用户 `/help` 显示 VIP 命令。
- 管理员 `/start` 提示 `/adminhelp`。
- 管理员 `/adminhelp` 显示管理员命令。
- 非管理员 `/adminhelp` 被拒绝。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_settings_and_help
```

- [ ] **步骤 3：实现最少代码**

调整：

- `/start`
- `/help`
- 新增 `/adminhelp`

帮助内容需要和 `docs/MULTI_USER_PERMISSIONS_DESIGN.md` 中的命令保持一致。

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_settings_and_help
```

## 阶段 6：管理员管理命令

### 任务 6.1：实现用户查询和角色管理

**文件：**

- 修改：`tg_bot.py`、`db.py`
- 测试：`tests/test_admin_commands.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- `/userls` 查询用户。
- `/userget <telegram_user_id>` 查询单个用户。
- `/userset <telegram_user_id> <normal|vip|admin>` 修改角色。
- `/userban <telegram_user_id>` 禁用用户。
- `/userunban <telegram_user_id>` 启用用户。
- 非管理员不能执行上述命令。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_admin_commands
```

- [ ] **步骤 3：实现最少代码**

新增管理员命令：

- `/userls [normal|vip|admin|disabled]`
- `/userget <telegram_user_id>`
- `/userset <telegram_user_id> <normal|vip|admin>`
- `/userban <telegram_user_id>`
- `/userunban <telegram_user_id>`

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_admin_commands
```

### 任务 6.2：实现用户 key 管理命令

**文件：**

- 修改：`tg_bot.py`、`db.py`
- 测试：`tests/test_admin_commands.py`

- [ ] **步骤 1：编写失败测试**

覆盖：

- `/userkeys <telegram_user_id>` 查看某用户所有 `key`。
- `/adminkeyinfo <key>` 查看任意 `key` 完整信息。
- `/adminkeydel <key>` 删除任意 `key`。
- 删除 `key` 时清理相关客户机器人绑定和运行中的 polling task。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
python -m unittest tests.test_admin_commands
```

- [ ] **步骤 3：实现最少代码**

新增管理员命令：

- `/userkeys <telegram_user_id>`
- `/adminkeyinfo <key>`
- `/adminkeydel <key>`

- [ ] **步骤 4：运行测试确认通过**

运行：

```bash
python -m unittest tests.test_admin_commands
```

## 阶段 7：文档和回归测试

### 任务 7.1：更新正式项目文档

**文件：**

- 修改：`README.md`
- 修改：`docs/API.md`
- 修改：`docs/DATABASE.md`
- 修改：`docs/OPERATIONS.md`

- [ ] **步骤 1：更新 README**

补充：

- 用户角色。
- key 数量限制。
- 普通用户、VIP 用户、管理员权限。
- 新命令概览。
- `/tokenadd` 和 `/groupbind` 使用说明。

- [ ] **步骤 2：更新数据库文档**

补充：

- `users`
- `system_settings`
- `pending_actions`
- `widgets.owner_user_id`
- `widgets.welcome_text`
- `bot_bindings.owner_user_id`

- [ ] **步骤 3：更新 API 文档**

补充：

- 普通用户网页客服不可用的错误码。
- VIP / 管理员网页入口可用规则。

- [ ] **步骤 4：更新运维文档**

补充：

- 管理员初始化。
- 手动开通 VIP。
- 客户机器人 token 安全注意事项。
- 多用户权限排查方式。

### 任务 7.2：全量验证

**文件：**

- 全项目

- [ ] **步骤 1：运行单元测试**

运行：

```bash
python -m unittest discover -s tests
```

预期：全部通过。

- [ ] **步骤 2：运行语法检查**

运行：

```bash
python -m py_compile api_server.py config.py db.py event_payload.py session_cleanup.py tg_bot.py
```

预期：无输出，退出码为 0。

- [ ] **步骤 3：手动验收核心流程**

在测试环境中验证：

- 普通用户创建 1 个 `key` 后不能创建第 2 个。
- VIP 用户可以创建 5 个 `key`。
- 管理员可以修改用户角色。
- 普通用户网页入口不可用。
- VIP 用户网页入口可用。
- `/tokenadd <key>` 绑定客户机器人后无需重启即可响应。
- 重启 `tg_bot.py` 后客户机器人绑定仍能恢复。
- 客户侧机器人 `/start` 显示自定义欢迎文案和帮助链接。
- `/groupbind <key>` 能把当前客服群绑定到指定 `key`。

## 实施建议

建议按阶段顺序执行，不要一次性改完所有命令。

推荐提交节奏：

1. 数据模型和用户基础。
2. key 所有权和数量限制。
3. 普通/VIP 功能权限。
4. token 绑定流程。
5. 客服群绑定流程。
6. 欢迎文案和帮助。
7. 管理员命令。
8. 文档和回归测试。

每个阶段都应先写失败测试，再实现，再运行全量测试。

## 风险点

- 多租户改造最容易遗漏所有权校验，尤其是旧命令复用时。
- 现有函数大量直接按 `key` 查询，改造时需要区分「管理员按 key 查询」和「用户按自己的 key 查询」。
- 客户机器人 token 属于敏感信息，命令交互中需要尽量删除用户发送的 token 消息。
- 普通用户的 `key` 在 Telegram 客户机器人可用，但网页客服不可用，需要清晰区分入口权限。
- `/kls` 等旧命令如果保留，必须避免管理员误看到大量用户数据。
- 客服群绑定按钮流程依赖 Telegram 深链和回调，建议放在 `/groupbind <key>` 稳定后再做。
