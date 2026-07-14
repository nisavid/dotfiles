"""Bounded, resumable execution for already-validated import projections."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Mapping

from .canonical import digest
from .model import deep_freeze


@dataclass(frozen=True)
class ImportRunResult:
    completed_item_ids: tuple[str, ...]
    deferred_item_ids: tuple[str, ...]
    resume_state: Mapping[str, str]
    events: tuple[Mapping[str, str], ...]
    run_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "resume_state", deep_freeze(self.resume_state))
        object.__setattr__(self, "events", tuple(deep_freeze(event) for event in self.events))


def run_import_inspection(
    projection: Any,
    *,
    inspector: Callable[[Any], Any],
    resume_state: Mapping[str, str] | None = None,
    max_items: int = 100,
    requests_per_window: int = 10,
    window_seconds: float = 60.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ImportRunResult:
    """Run a bounded proposal-inspection pass without controller apply."""

    from .importing import ImportError, _sha, validate_projection

    validate_projection(projection)
    if not callable(inspector) or not callable(clock) or not callable(sleep):
        raise ImportError("inspection run callbacks must be callable")
    if type(max_items) is not int or not 1 <= max_items <= 1000:
        raise ImportError("max_items must be an integer from 1 to 1000")
    if type(requests_per_window) is not int or not 1 <= requests_per_window <= 1000:
        raise ImportError("requests_per_window must be an integer from 1 to 1000")
    if not isinstance(window_seconds, (int, float)) or isinstance(window_seconds, bool) or not 0 < window_seconds <= 3600:
        raise ImportError("window_seconds must be greater than zero and at most 3600")

    item_by_id = {item.item_id: item for item in projection.items}
    supplied_state = dict(resume_state or {})
    for item_id, content_digest in supplied_state.items():
        _sha(item_id, "resume item identity")
        _sha(content_digest, "resume item digest")
        if item_id not in item_by_id:
            raise ImportError("resume state references an unknown projection item")
    completed_state = {
        item.item_id: item.content_digest
        for item in projection.items
        if item.item_id in projection.skipped_item_ids
        or supplied_state.get(item.item_id) == item.content_digest
    }
    pending = [item for item in projection.pending_items if item.item_id not in completed_state]
    events: list[dict[str, str]] = []
    request_times: list[float] = []
    for item in pending[:max_items]:
        now = clock()
        request_times = [started for started in request_times if now - started < window_seconds]
        if len(request_times) >= requests_per_window:
            sleep(max(0.0, window_seconds - (now - request_times[0])))
            now = clock()
            request_times = [started for started in request_times if now - started < window_seconds]
            if len(request_times) >= requests_per_window:
                raise ImportError("rate-limit clock did not advance through the window")
        request_times.append(now)
        try:
            inspector(item)
        except Exception:
            events.append({"item_id": item.item_id, "status": "failed"})
            break
        completed_state[item.item_id] = item.content_digest
        events.append({"item_id": item.item_id, "status": "inspected"})

    completed_ids = tuple(item.item_id for item in projection.items if item.item_id in completed_state)
    deferred_ids = tuple(item.item_id for item in projection.pending_items if item.item_id not in completed_state)
    body = {
        "projection_digest": projection.projection_digest,
        "completed": [{"item_id": item_id, "content_digest": completed_state[item_id]} for item_id in completed_ids],
        "deferred_item_ids": list(deferred_ids),
        "events": events,
    }
    return ImportRunResult(
        completed_ids, deferred_ids,
        {item_id: completed_state[item_id] for item_id in completed_ids},
        tuple(events), digest(body),
    )
