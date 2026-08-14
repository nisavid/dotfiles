from __future__ import annotations

import os
import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import NoReturn


def require_age_tooling_or_skip(
    message: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    """Fail required CI jobs and skip only optional local coverage."""

    error: BaseException
    if os.environ.get("REQUIRE_AGE_TOOLING") == "1":
        error = AssertionError(message)
    else:
        error = unittest.SkipTest(message)
    if cause is not None:
        raise error from cause
    raise error


def shared_age_tooling_directory_or_skip(
    binaries: Iterable[str],
    message: str,
) -> Path:
    """Return the shared install directory used as the admission trust anchor."""

    try:
        directories = {Path(binary).parent.resolve(strict=True) for binary in binaries}
    except OSError as error:
        require_age_tooling_or_skip(message, cause=error)
    if len(directories) != 1:
        require_age_tooling_or_skip(message)
    return directories.pop()
