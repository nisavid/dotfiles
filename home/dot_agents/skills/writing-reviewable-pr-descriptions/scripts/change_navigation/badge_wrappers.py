"""Validate immediate wrappers around shield images."""

from __future__ import annotations

from collections import Counter

from .model import LINKED_SHIELD_RE, PICTURE_SHIELD_RE, SHIELD_IMAGE_RE, alt


def validate_wrappers(text: str, errors: list[str]) -> None:
    all_images = Counter(SHIELD_IMAGE_RE.findall(text))
    wrapped_images = Counter(PICTURE_SHIELD_RE.findall(text))
    wrapped_images.update(image for _, image in LINKED_SHIELD_RE.findall(text))
    for image, count in (all_images - wrapped_images).items():
        for _ in range(count):
            errors.append(
                f"shield lacks an immediate picture or navigation wrapper: {alt(image)}"
            )
