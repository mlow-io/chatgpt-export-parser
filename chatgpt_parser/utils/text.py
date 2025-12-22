import re
from typing import Iterable, Optional, Tuple
from urllib.parse import urlparse
from ..config import URL_REGEX

def escape_markdown_text(text: Optional[str]) -> str:
    if text is None:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def extract_urls_from_text(text: str) -> Iterable[Tuple[str, int, int]]:
    if not text:
        return []
    for m in URL_REGEX.finditer(text):
        url = m.group(0).rstrip(").,]>\"'")
        start = m.start()
        end = start + len(url)
        yield url, start, end


def parse_url(url: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    try:
        parsed = urlparse(url)
        return parsed.scheme or None, parsed.netloc or None, parsed.path or None, parsed.query or None
    except Exception:
        return None, None, None, None

def markdown_escape(text: str) -> str:
    """Escapes newlines for use in markdown table cells or single-line contexts."""
    return text.replace("\n", " ").strip()
