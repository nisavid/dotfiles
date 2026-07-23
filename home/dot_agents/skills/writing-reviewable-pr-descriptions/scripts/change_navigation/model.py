"""Define badge patterns shared by change-navigation validators."""

from __future__ import annotations

import re
from html import unescape


ATTRIBUTE_BOUNDARY = r"(?<!\S)"
IMAGE_RE = re.compile(r"<img\b[^>]*>")
SHIELD_IMAGE_RE = re.compile(
    rf'<img\b[^>]*{ATTRIBUTE_BOUNDARY}src="https://img\.shields\.io/[^"]+"[^>]*>'
)
ALT_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}alt="([^"]*)"')
TITLE_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}title="([^"]*)"')
HEIGHT_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}height="16"')
LINKED_PR_BADGE_RE = re.compile(
    r'<a href="https://github\.com/[^/]+/[^/]+/pull/(\d+)"><img\b([^>]*)></a>'
)
LINKED_SHIELD_RE = re.compile(
    rf'<a href="([^"]+)">(<img\b[^>]*{ATTRIBUTE_BOUNDARY}'
    r'src="https://img\.shields\.io/[^"]+"[^>]*>)</a>'
)
PICTURE_SHIELD_RE = re.compile(
    rf"<picture>(<img\b[^>]*{ATTRIBUTE_BOUNDARY}"
    r'src="https://img\.shields\.io/[^"]+"[^>]*>)</picture>'
)
ATOMIC_FILE_BADGE_RE = re.compile(
    rf'{ATTRIBUTE_BOUNDARY}src="https://img\.shields\.io/badge/'
    r"%2B(\d+)-%E2%88%92(\d+)-CF222E"
    r'\?style=flat&labelColor=1A7F37"'
)
CATEGORY_RE = re.compile(rf'{ATTRIBUTE_BOUNDARY}alt="(IMPL|TEST|DOC|GEN|OTHER):')


def raw_attribute(tag: str, name: str) -> str:
    values = attribute_values(tag, name)
    return values[0] if values else ""


def attribute_values(tag: str, name: str) -> list[str]:
    return re.findall(rf'{ATTRIBUTE_BOUNDARY}{re.escape(name)}="([^"]*)"', tag)


def alt(image: str) -> str:
    return unescape(raw_attribute(image, "alt"))


def title(image: str) -> str:
    return unescape(raw_attribute(image, "title"))


def source(image: str) -> str:
    return raw_attribute(image, "src")


def alt_values(text: str) -> list[str]:
    return [unescape(value) for value in ALT_RE.findall(text)]
