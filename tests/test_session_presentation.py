from shared.session_presentation import format_session_header_html, make_topic_name


def test_topic_name_uses_display_name_six_digit_code_and_source_without_key():
    name = make_topic_name("KTV客服", "ktv", "ad01", random_code="123456")

    assert name == "KTV客服-123456-ad01"
    assert "(ktv)" not in name


def test_topic_name_falls_back_to_key_when_display_name_is_blank():
    assert make_topic_name("", "ktv", "", random_code="000001") == "ktv-000001"


def test_web_session_header_marks_channel_and_source():
    header = format_session_header_html(
        session_id="abc123",
        key="ktv",
        display_name="KTV客服",
        enabled=1,
        offline_msg="",
        channel="web",
        source_code="ad01",
    )

    assert "入口：<b>KTV客服</b>（<code>ktv</code>）" in header
    assert "状态：<b>网页在线咨询</b>" in header
    assert "统计来源：<code>ad01</code>" in header
    assert "会话：<code>abc123</code>" in header


def test_telegram_session_header_marks_robot_side_without_empty_source_line():
    header = format_session_header_html(
        session_id="tg-session",
        key="ktv",
        display_name="ktv",
        enabled=1,
        offline_msg="",
        channel="telegram",
        source_code="",
    )

    assert "入口：<b>ktv</b>" in header
    assert "（<code>ktv</code>）" not in header
    assert "状态：<b>机器人侧在线咨询</b>" in header
    assert "统计来源：" not in header
