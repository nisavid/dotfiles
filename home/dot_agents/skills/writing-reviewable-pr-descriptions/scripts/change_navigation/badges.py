"""Coordinate validation of Shields presentation and metadata."""

from __future__ import annotations

from collections import Counter

from .badge_links import validate_linked_badges
from .badge_presentation import validate_shields
from .badge_wrappers import validate_wrappers
from .model import IMAGE_RE, SHIELD_IMAGE_RE, alt


def validate_badges(text: str, errors: list[str]) -> None:
    _validate_images(text, errors)
    validate_shields(text, errors)
    validate_linked_badges(text, errors)
    validate_wrappers(text, errors)


def _validate_images(text: str, errors: list[str]) -> None:
    images = Counter(IMAGE_RE.findall(text))
    shields = Counter(SHIELD_IMAGE_RE.findall(text))
    for image, count in (images - shields).items():
        for _ in range(count):
            errors.append(
                "navigation image is not a structurally valid Shields badge: "
                f"{alt(image) or image}"
            )
