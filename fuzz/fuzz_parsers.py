"""Atheris fuzz harness for bolster string-parsing utilities.

Run locally:
    pip install atheris
    python fuzz/fuzz_parsers.py -max_total_time=60

In CI: fuzz.yml runs this with a short wall-clock limit.
Any uncaught exception (other than ValueError/TypeError from expected
bad input) is reported as a crash.
"""

import contextlib
import sys

import atheris

with atheris.instrument_imports():
    from bolster.data_sources.nisra._base import make_absolute_url, parse_month_year


def TestOneInput(data: bytes) -> None:
    """Fuzz entry point called by Atheris with mutated bytes."""
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(256)
    fmt = fdp.ConsumeUnicodeNoSurrogates(32)
    base = fdp.ConsumeUnicodeNoSurrogates(128)

    parse_month_year(text)
    if fmt:
        with contextlib.suppress(ValueError, TypeError):
            parse_month_year(text, format=fmt)

    make_absolute_url(text, "https://www.nisra.gov.uk")
    make_absolute_url("relative/path.xlsx", base or "https://www.nisra.gov.uk")


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
