"""Utility bits and pieces.

Random helpful functions that don't fit anywhere else:
- timed: decorator to time function execution
- TqdmLoggingHandler: logging that plays nice with tqdm progress bars
- web: resilient web scraping helpers
- rss: RSS/Atom feed parsing utilities
- dt: datetime utilities
- io: file/data helpers
- aws/azure: cloud platform helpers
"""

import datetime
import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

import tqdm

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

version_no = f"{(datetime.date.today() - datetime.date(1988, 5, 17)).total_seconds() / 31557600:.2f}"


class TqdmLoggingHandler(logging.Handler):
    """Custom logging handler that uses tqdm to display log messages.

    Usage: `logging.getLogger().addHandler(TqdmLoggingHandler())`.
    """

    def __init__(self, level=logging.NOTSET):
        """Initialize the handler with the specified logging level."""
        super().__init__(level)

    def emit(self, record):
        """Emit a log record using tqdm.write to avoid interfering with progress bars."""
        try:
            msg = self.format(record)
            tqdm.tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)


def timed(func: F) -> F:
    """This decorator prints the execution time for the decorated function."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.time()
        logger.info(f"Launching {func.__name__}")
        result = func(*args, **kwargs)
        end = time.time()
        logger.info(f"{func.__name__} ran in {round(end - start, 2)}s")
        return result

    return wrapper
