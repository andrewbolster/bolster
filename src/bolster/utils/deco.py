import logging
import time
from functools import wraps


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
