import pytest

from url_utils import normalize_url, normalized_links_from_message


@pytest.mark.parametrize(
    "raw, expected",
    [
        # scheme / host / www / trailing slash
        ("HTTP://www.Example.com/", "https://example.com"),
        ("example.com/path/", "https://example.com/path"),
        ("https://m.example.com//a//b", "https://example.com/a/b"),
        # tracking params and fragments
        ("https://example.com/?utm_source=x&id=5&fbclid=abc#top", "https://example.com?id=5"),
        ("https://example.com/?b=2&a=1", "https://example.com?a=1&b=2"),
        # ports
        ("https://example.com:443/x", "https://example.com/x"),
        ("https://example.com:8080/x", "https://example.com:8080/x"),
        # telegram variants all collapse to one form
        ("https://t.me/MyChannel", "https://t.me/mychannel"),
        ("http://telegram.me/mychannel/", "https://t.me/mychannel"),
        ("t.me/s/MyChannel", "https://t.me/mychannel"),
        ("@MyChannel", "https://t.me/mychannel"),
        ("tg://resolve?domain=MyChannel", "https://t.me/mychannel"),
        # invite hashes are case-sensitive
        ("https://t.me/+AbCdEf123", "https://t.me/+AbCdEf123"),
        ("https://t.me/joinchat/AbCdEf", "https://t.me/joinchat/AbCdEf"),
        # youtube
        ("https://youtu.be/dQw4w9WgXcQ?si=tracking", "https://youtube.com/watch?v=dQw4w9WgXcQ"),
        # trailing punctuation from chat messages
        ("(https://example.com/page).", "https://example.com/page"),
    ],
)
def test_normalize(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "hello", "@ab", "https://", "t.me/", "tg://join?invite=x"])
def test_invalid(raw):
    assert normalize_url(raw) is None


def test_drop_telegram_post_id():
    assert normalize_url("t.me/MyChannel/123") == "https://t.me/mychannel/123"
    assert normalize_url("t.me/MyChannel/123", drop_telegram_post_id=True) == "https://t.me/mychannel"


def test_message_extraction_dedupes():
    text = "check https://www.t.me/Foo and t.me/foo/ plus https://example.com/?utm_medium=x."
    assert normalized_links_from_message(text) == ["https://t.me/foo", "https://example.com"]
