"""Validate Shields style, height, and wrappers."""

from __future__ import annotations

import re
from html import escape, unescape
from urllib.parse import parse_qs, urlsplit

from .badge_colors import validate_color_and_label
from .model import SHIELD_IMAGE_RE, alt, attribute_values, raw_attribute, source, title


SUPPORTED_ALT_RE = re.compile(
    r"^(?:STACK|DIFF|STACK STATUS: TOP|BINARY|MOVED|COPIED|"
    r"STACK POSITION: \d+ OF \d+|"
    r"(?:BASE|DEP|NEXT): .+|"
    r"(?:IMPL|TEST|DOC|GEN|OTHER): \d+ additions, \d+ deletions|"
    r"FILES: (?:\d+ touched|"
    r"\d+ (?:implementation|test|documentation|generated|other) files?|"
    r"\d+ added, \d+ modified, \d+ removed"
    r"(?:, [1-9]\d* moved)?(?:, [1-9]\d* copied)?)|"
    r"\d+ additions, \d+ deletions)$"
)


def validate_shields(text: str, errors: list[str]) -> None:
    for image in SHIELD_IMAGE_RE.findall(text):
        _validate_attribute_cardinality(image, errors)
        image_alt = alt(image)
        _validate_attribute_escaping(image, errors)
        if not SUPPORTED_ALT_RE.fullmatch(image_alt):
            errors.append(f"unsupported or non-uppercase shield label: {image_alt}")
        source_url = source(image)
        expected_style = "for-the-badge" if image_alt in {"STACK", "DIFF"} else "flat"
        style_values = parse_qs(urlsplit(source_url).query).get("style", [])
        if style_values != [expected_style]:
            errors.append(f"{image_alt or 'shield'} must use style={expected_style}")
        validate_color_and_label(image_alt, source_url, errors)


def _validate_attribute_cardinality(image: str, errors: list[str]) -> None:
    image_alt = alt(image)
    for attribute in ("alt", "src"):
        if len(attribute_values(image, attribute)) != 1:
            errors.append(
                f"shield must have exactly one real {attribute} attribute: "
                f"{image_alt or image}"
            )
    heights = attribute_values(image, "height")
    if heights != ["16"]:
        errors.append(f"shield must have exactly one 16px height: {image_alt or image}")

    titles = attribute_values(image, "title")
    title_required = bool(
        re.fullmatch(r"(?:BASE|DEP|NEXT): #\d+ — .+", image_alt)
        or re.fullmatch(r"\d+ additions, \d+ deletions", image_alt)
        or image_alt in {"BINARY", "MOVED", "COPIED"}
    )
    if title_required and (
        len(titles) != 1 or title(image) != _expected_title(image_alt)
    ):
        errors.append(f"{image_alt or 'shield'} needs exactly one matching title")
    elif not title_required and titles:
        errors.append(f"{image_alt or 'shield'} must not define a title")


def _expected_title(image_alt: str) -> str:
    navigation = re.fullmatch(r"(?:BASE|DEP|NEXT): (#\d+ — .+)", image_alt)
    return navigation.group(1) if navigation else image_alt


def _validate_attribute_escaping(image: str, errors: list[str]) -> None:
    for attribute in ("alt", "title"):
        raw = raw_attribute(image, attribute)
        if not raw:
            continue
        semantic = unescape(raw)
        canonical = escape(semantic, quote=True).replace("&#x27;", "'")
        if raw != canonical:
            errors.append(f"shield {attribute} text must use canonical HTML escaping")
