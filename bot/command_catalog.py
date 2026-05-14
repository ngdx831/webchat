from aiogram.types import BotCommand


COMMAND_DESCRIPTIONS = {
    "start": "启动机器人或打开客户入口",
    "help": "查看当前账号可用命令",
    "myinfo": "查看账号角色和 key 数量",
    "id": "查看当前聊天和话题 ID",
    "keyadd": "创建自己的客服入口 key",
    "kls": "查看并管理客服入口 key",
    "keyinfo": "查看 key 详情和操作按钮",
    "keydel": "删除自己的客服入口 key",
    "tokenadd": "绑定客户侧 Telegram 机器人",
    "groupbind": "绑定当前超级群为客服群",
    "botadd": "直接绑定客户机器人 Token",
    "botdel": "删除客户机器人绑定",
    "botls": "查看客户机器人绑定",
    "kstatus": "切换上/下班状态（不带 key 时统一切换）",
    "qradd": "添加自动回复",
    "qrls": "查看和管理自动回复",
    "qrdel": "删除自动回复",
    "stats": "查看来源统计",
    "statdel": "清理来源统计",
    "adminhelp": "查看管理员命令说明",
    "userls": "查看用户列表",
    "userget": "查看指定用户资料",
    "userset": "设置用户角色",
    "userban": "禁用用户",
    "userunban": "解除用户禁用",
    "userkeys": "查看用户名下 key",
    "adminkeyinfo": "查看任意 key 详情",
    "adminkeydel": "删除任意 key",
    "helplink": "设置全局帮助链接",
    "kadd": "管理员添加或更新 key",
    "kdel": "管理员删除 key",
    "valid": "标记当前会话为有效客户",
    "deal": "标记当前会话为成交客户",
    "end": "结束当前客服会话",
}

USER_COMMANDS = [
    "start",
    "help",
    "myinfo",
    "id",
    "keyadd",
    "kls",
    "keyinfo",
    "keydel",
    "tokenadd",
    "groupbind",
    "botadd",
    "botdel",
    "botls",
    "kstatus",
]

VIP_COMMANDS = [
    "qradd",
    "qrls",
    "qrdel",
    "stats",
    "statdel",
]

ADMIN_COMMANDS = [
    "adminhelp",
    "userls",
    "userget",
    "userset",
    "userban",
    "userunban",
    "userkeys",
    "adminkeyinfo",
    "adminkeydel",
    "helplink",
    "kadd",
    "kdel",
]

SESSION_COMMANDS = ["valid", "deal", "end"]

MAIN_BOT_COMMANDS = [
    BotCommand(command=command, description=description)
    for command, description in COMMAND_DESCRIPTIONS.items()
]


def command_help_lines(commands):
    return [f"/{command} - {COMMAND_DESCRIPTIONS[command]}" for command in commands]


async def setup_main_bot_commands(bot) -> None:
    await bot.set_my_commands(MAIN_BOT_COMMANDS)
