"""Retry helper for transient Docker API errors."""
import logging
import time
from typing import Callable, TypeVar

from docker.errors import APIError

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.4


def retry_docker(
    fn: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    description: str = "Docker call",
) -> T:
    """Call fn() with exponential backoff on transient Docker APIError.

    4xx client errors are not transient; they are raised immediately.
    """
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except APIError as exc:
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", 0)
            if 400 <= status < 500:
                raise
            if i == attempts - 1:
                break
            delay = base_delay * (2 ** i)
            logger.warning(
                "%s failed (attempt %d/%d): %s; retrying in %.1fs",
                description, i + 1, attempts, exc, delay,
            )
            time.sleep(delay)
    raise last_exc