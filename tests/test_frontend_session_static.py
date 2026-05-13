from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_token_uses_same_persistence_as_session_id():
    source = (ROOT / "public" / "chat.js").read_text(encoding="utf-8")

    assert "storedToken = localStorage.getItem(streamTokenKey) || \"\";" in source
    assert "localStorage.setItem(streamTokenKey, streamToken)" in source
    assert "sessionStorage" not in source
    assert "localStorage.removeItem(sessionKey)" in source
    assert "localStorage.removeItem(streamTokenKey)" in source


def test_chat_keeps_sse_open_while_page_is_hidden_and_marks_sent_event_seen():
    source = (ROOT / "public" / "chat.js").read_text(encoding="utf-8")

    assert "document.hidden && stream" not in source
    assert "markSeen(data.event_id)" in source
    assert "lastEventId = Math.max(lastEventId, Number(data.event_id) || 0)" in source
