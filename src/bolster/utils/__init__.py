import datetime
import logging

import tqdm

version_no = f"{(datetime.date.today() - datetime.date(1988, 5, 17)).total_seconds() / 31557600:.2f}"


class TqdmLoggingHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)
