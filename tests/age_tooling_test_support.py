from __future__ import annotations

import os
import unittest
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
