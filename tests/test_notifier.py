import socket
from unittest.mock import MagicMock, patch

import config
from src.notifier import send_alert


def _mock_urlopen(status=200):
    response = MagicMock()
    response.status = status
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    return patch("urllib.request.urlopen", return_value=response)


def test_returns_true_on_success():
    with _mock_urlopen(200):
        assert send_alert("title", "message") is True


def test_returns_false_on_exception():
    with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
        assert send_alert("title", "message") is False


def test_passes_timeout_to_urlopen(monkeypatch):
    monkeypatch.setattr(config, "NTFY_TOPIC", "my-topic")

    with patch(
        "urllib.request.urlopen", side_effect=socket.timeout("timed out")
    ) as mock_open:
        assert send_alert("title", "message") is False

    assert mock_open.call_args.kwargs["timeout"] == 10


def test_returns_true_silently_when_topic_is_empty(monkeypatch):
    monkeypatch.setattr(config, "NTFY_TOPIC", "")
    with patch("urllib.request.urlopen") as mock_open:
        result = send_alert("title", "message")
    assert result is True
    mock_open.assert_not_called()


def test_returns_true_silently_when_topic_is_none(monkeypatch):
    monkeypatch.setattr(config, "NTFY_TOPIC", None)
    with patch("urllib.request.urlopen") as mock_open:
        result = send_alert("title", "message")
    assert result is True
    mock_open.assert_not_called()


def test_posts_to_correct_url(monkeypatch):
    monkeypatch.setattr(config, "NTFY_TOPIC", "my-topic")
    monkeypatch.setattr(config, "NTFY_URL", "https://ntfy.sh")
    captured = []

    def fake_urlopen(req, *args, **kwargs):
        captured.append(req)
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    with patch("urllib.request.urlopen", fake_urlopen):
        send_alert("title", "message")

    assert captured[0].full_url == "https://ntfy.sh/my-topic"


def test_sets_title_and_priority_headers(monkeypatch):
    monkeypatch.setattr(config, "NTFY_TOPIC", "my-topic")
    captured = []

    def fake_urlopen(req, *args, **kwargs):
        captured.append(req)
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    with patch("urllib.request.urlopen", fake_urlopen):
        send_alert("my title", "body", priority="high")

    assert captured[0].get_header("Title") == "my title"
    assert captured[0].get_header("Priority") == "high"


def test_supports_unicode_title_header(monkeypatch):
    monkeypatch.setattr(config, "NTFY_TOPIC", "my-topic")
    captured = []

    def fake_urlopen(req, *args, **kwargs):
        captured.append(req)
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    title = "Deal €50"
    with patch("urllib.request.urlopen", fake_urlopen):
        send_alert(title, "body")

    header = captured[0].get_header("Title")
    assert header == title.encode("utf-8").decode("latin-1")


def test_sends_message_as_bytes(monkeypatch):
    monkeypatch.setattr(config, "NTFY_TOPIC", "my-topic")
    captured = []

    def fake_urlopen(req, *args, **kwargs):
        captured.append(req)
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    with patch("urllib.request.urlopen", fake_urlopen):
        send_alert("t", "hello world")

    assert captured[0].data == b"hello world"
