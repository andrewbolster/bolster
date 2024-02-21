"""
This module contains utility functions and classes that are used throughout the package.
"""
import datetime
import logging
import time
from functools import wraps

import tqdm

version_no = f"{(datetime.date.today() - datetime.date(1988, 5, 17)).total_seconds() / 31557600:.2f}"


class TqdmLoggingHandler(logging.Handler):
    """
    Custom logging handler that uses tqdm to display log messages.
    i.e. `logging.getLogger().addHandler(TqdmLoggingHandler())`
    """

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)


def timed(func):
    """This decorator prints the execution time for the decorated function."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        logging.info(f"Launching {func.__name__}")
        result = func(*args, **kwargs)
        end = time.time()
        logging.info(f"{func.__name__} ran in {round(end - start, 2)}s")
        return result

    return wrapper
