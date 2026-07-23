"""Validate Stack disclosure semantics."""

from __future__ import annotations

import re
from html import unescape

from .model import LINKED_SHIELD_RE, alt, alt_values
from .parsing import summary
from .stack_inventory import inventory, validate_inventory


def validate_stack(block: list[str], errors: list[str]) -> None:
    text = "\n".join(block)
    stack_summary = summary(block, errors, "Stack")
    if 'alt="STACK"' not in stack_summary:
        errors.append("first disclosure must be Stack when Stack is present")
    if not re.match(
        r'^<summary><picture><img alt="STACK"[^>]*></picture>&nbsp;', stack_summary
    ):
        errors.append("Stack summary must use a non-breaking gap after its label")
    if stack_summary.count("&nbsp;") != 1:
        errors.append("Stack summary must use exactly one non-breaking label gap")
    if len(re.findall(r"← this PR", text)) != 1:
        errors.append("Stack expansion must mark exactly one current PR")
    position_match = re.search(r'alt="STACK POSITION: (\d+) OF (\d+)"', stack_summary)
    if not position_match:
        errors.append("Stack summary needs a full-stack position badge")
    if 'alt="BASE:' not in stack_summary:
        errors.append("Stack summary needs a direct BASE badge")
    if (
        'alt="NEXT:' not in stack_summary
        and 'alt="STACK STATUS: TOP"' not in stack_summary
    ):
        errors.append("Stack summary needs NEXT navigation or TOP status")
    if "## Stack" in text:
        errors.append("Stack disclosure must not contain a separate Stack heading")
    _validate_navigation(block, stack_summary, position_match, errors)
    validate_inventory(block, position_match, errors)


def _validate_navigation(
    block: list[str],
    stack_summary: str,
    position_match: re.Match[str] | None,
    errors: list[str],
) -> None:
    badges = alt_values(stack_summary)
    base_badges = [badge for badge in badges if badge.startswith("BASE:")]
    dep_badges = [badge for badge in badges if badge.startswith("DEP:")]
    next_badges = [badge for badge in badges if badge.startswith("NEXT:")]
    top_badges = [badge for badge in badges if badge == "STACK STATUS: TOP"]
    if len(base_badges) != 1:
        errors.append("Stack summary needs exactly one BASE badge")
    expected_prefix = badges[:2] == [
        "STACK",
        position_match.group(0)[5:-1] if position_match else "",
    ]
    navigation_badges = badges[2:]
    expected_navigation = base_badges + dep_badges + (next_badges or top_badges)
    if not expected_prefix or navigation_badges != expected_navigation:
        errors.append(
            "Stack badges must be ordered STACK, position, BASE, DEP, then NEXT or TOP"
        )
    linked_navigation = {
        alt(image) for _, image in LINKED_SHIELD_RE.findall(stack_summary)
    }
    if next_badges and next_badges[0] not in linked_navigation:
        errors.append("NEXT must link to its PR")
    for base_badge in base_badges:
        if re.match(r"BASE: #\d+", base_badge) and base_badge not in linked_navigation:
            errors.append("a PR-valued BASE must link to its PR")
    for dep_badge in dep_badges:
        if dep_badge not in linked_navigation:
            errors.append("every DEP must link to its PR")
    if position_match:
        current = int(position_match.group(1))
        total = int(position_match.group(2))
        if current < 1 or total < 1 or current > total:
            errors.append("Stack position must be within the complete stack")
        elif current < total and (len(next_badges) != 1 or top_badges):
            errors.append("a non-top Stack PR needs exactly one NEXT badge and no TOP")
        elif current == total and (next_badges or len(top_badges) != 1):
            errors.append("the top Stack PR needs exactly one TOP badge and no NEXT")
    items = inventory(block)
    current_indexes = [index for index, item in enumerate(items) if item.current]
    if len(current_indexes) != 1:
        return
    current_index = current_indexes[0]
    stack_repository = items[current_index].repository
    for href, image in LINKED_SHIELD_RE.findall(stack_summary):
        badge_alt = alt(image)
        if badge_alt.startswith(("BASE:", "NEXT:")) and not href.startswith(
            f"https://github.com/{stack_repository}/pull/"
        ):
            errors.append("BASE and NEXT must link within the Stack repository")
    inventory_destinations = {
        item.number: unescape(item.destination_text) for item in items
    }
    for badge in base_badges + dep_badges + next_badges:
        destination = re.fullmatch(r"(?:BASE|DEP|NEXT): #(\d+) — (.+)", badge)
        if destination and int(destination.group(1)) in inventory_destinations:
            expected = inventory_destinations[int(destination.group(1))]
            actual = unescape(f"#{destination.group(1)} — {destination.group(2)}")
            if actual != expected:
                errors.append(
                    f"{badge.split(':', 1)[0]} title must match Stack inventory"
                )
    if current_index > 0:
        expected_base = f"BASE: {unescape(items[current_index - 1].destination_text)}"
        if base_badges != [expected_base] or expected_base not in linked_navigation:
            errors.append("BASE must link to the immediately preceding Stack PR")
    elif set(_navigation_numbers(base_badges)).intersection(
        item.number for item in items
    ):
        errors.append("the bottom Stack PR's BASE must be outside the Stack inventory")
    if current_index + 1 < len(items):
        expected_next = f"NEXT: {unescape(items[current_index + 1].destination_text)}"
        if next_badges != [expected_next] or expected_next not in linked_navigation:
            errors.append("NEXT must link to the immediately following Stack PR")
    base_numbers = _navigation_numbers(base_badges)
    dep_numbers = _navigation_numbers(dep_badges)
    next_numbers = _navigation_numbers(next_badges)
    if len(dep_numbers) != len(set(dep_numbers)):
        errors.append("DEP destinations must be unique")
    reserved_numbers = {item.number for item in items}.union(base_numbers, next_numbers)
    if reserved_numbers.intersection(dep_numbers):
        errors.append("DEP must not repeat BASE or any Stack inventory PR")


def _navigation_numbers(badges: list[str]) -> list[int]:
    numbers: list[int] = []
    for badge in badges:
        match = re.match(r"(?:BASE|DEP|NEXT): #(\d+) — ", badge)
        if match:
            numbers.append(int(match.group(1)))
    return numbers
