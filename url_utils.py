"""URL normalization helpers for ProtocolDroid's duplicate-link detection.

Goal: two links that point at the same thing should normalize to the same string.

    normalize_url("HTTP://www.T.me/MyChannel/?utm_source=x")  ->  "https://t.me/mychannel"
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that never change what a link points to.
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "si", "ref", "ref_src",
    "mc_cid", "mc_eid", "feature", "source", "spm",
}
TRACKING_PREFIXES = ("utm_",)

TELEGRAM_HOSTS = {"t.me", "telegram.me", "telegram.dog"}

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")
_URL_IN_TEXT_RE = re.compile(
    r"(?:https?://|tg://|www\.|(?:t|telegram)\.me/|telegram\.dog/)[^\s<>]+",
    re.IGNORECASE,
)
_TRAILING_PUNCT = ".,;:!?)]}\"'"


def _is_tracking(key: str) -> bool:
    key = key.lower()
    return key in TRACKING_PARAMS or key.startswith(TRACKING_PREFIXES)


def _clean_query(query: str) -> list[tuple[str, str]]:
    pairs = parse_qsl(query, keep_blank_values=True)
    return sorted((k, v) for k, v in pairs if not _is_tracking(k))


def _normalize_telegram(
    path: str, query_pairs: list[tuple[str, str]], drop_post_id: bool
) -> str | None:
    segments = [s for s in path.split("/") if s]

    # t.me/s/channel is just the web preview of t.me/channel
    if segments and segments[0] == "s":
        segments = segments[1:]
    if not segments:
        return None

    first = segments[0]

    # Invite links: the hash is case-sensitive, so don't lowercase it.
    if first == "joinchat" and len(segments) > 1:
        return f"https://t.me/joinchat/{segments[1]}"
    if first.startswith("+"):
        return f"https://t.me/{first}"

    # Private channel post links (t.me/c/<id>/<post>) - keep as-is.
    if first == "c":
        return "https://t.me/" + "/".join(segments)

    # Public usernames are case-insensitive.
    parts = [first.lower()]
    if not drop_post_id:
        parts += segments[1:]

    result = "https://t.me/" + "/".join(parts)
    if query_pairs:
        result += "?" + urlencode(query_pairs)
    return result


def normalize_url(raw: str, drop_telegram_post_id: bool = False) -> str | None:
    """Return a canonical form of `raw`, or None if it isn't a usable link.

    drop_telegram_post_id: if True, t.me/channel/123 -> t.me/channel, so
    different posts from the same channel count as the same source.
    """
    if not raw:
        return None

    text = raw.strip().lstrip("(<[{\"'").rstrip(_TRAILING_PUNCT + ">")
    if not text:
        return None

    # @username -> t.me/username
    if text.startswith("@"):
        username = text[1:]
        return f"https://t.me/{username.lower()}" if _USERNAME_RE.match(username) else None

    # tg://resolve?domain=username -> t.me/username
    if text.lower().startswith("tg://"):
        parts = urlsplit(text)
        if parts.netloc.lower() == "resolve":
            domain = dict(parse_qsl(parts.query)).get("domain")
            if domain and _USERNAME_RE.match(domain):
                return f"https://t.me/{domain.lower()}"
        return None

    if not _SCHEME_RE.match(text):
        text = "https://" + text

    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None

    if not host or "." not in host:
        return None

    host = re.sub(r"^(www\.|m\.|mobile\.)", "", host)
    if host == "twitter.com":
        host = "x.com"
    path = re.sub(r"/{2,}", "/", parts.path)
    query_pairs = _clean_query(parts.query)

    if host in TELEGRAM_HOSTS:
        return _normalize_telegram(path, query_pairs, drop_telegram_post_id)

    # youtu.be/ID -> youtube.com/watch?v=ID
    if host == "youtu.be":
        video_id = path.strip("/")
        if not video_id:
            return None
        host, path = "youtube.com", "/watch"
        query_pairs = sorted([("v", video_id)] + [p for p in query_pairs if p[0] != "v"])

    # x.com: usernames are case-insensitive, and ?s= / ?t= are share-tracking params
    if host == "x.com":
        path = path.lower()
        query_pairs = [p for p in query_pairs if p[0] not in ("s", "t")]

    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = path.rstrip("/")
    query = urlencode(query_pairs)

    return urlunsplit(("https", netloc, path, query, ""))


def telegram_username(normalized_url: str) -> str | None:
    """Return the username if this is a plain public link like https://t.me/username.

    Post links (t.me/user/123), invite links (t.me/+hash, joinchat) and bot
    deep links (t.me/bot?start=x) return None.
    """
    match = re.fullmatch(r"https://t\.me/([a-z0-9_]{4,32})", normalized_url or "")
    return match.group(1) if match else None


def extract_urls(text: str) -> list[str]:
    """Pull link-looking chunks out of a message (not yet normalized)."""
    if not text:
        return []
    return [m.group(0).rstrip(_TRAILING_PUNCT) for m in _URL_IN_TEXT_RE.finditer(text)]


def normalized_links_from_message(text: str, drop_telegram_post_id: bool = False) -> list[str]:
    """Extract, normalize, and de-duplicate links from one message, keeping order."""
    seen: dict[str, None] = {}
    for raw in extract_urls(text):
        norm = normalize_url(raw, drop_telegram_post_id)
        if norm:
            seen.setdefault(norm)
    return list(seen)
