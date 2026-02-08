import datetime
import logging

import dateparser
import numpy as np
import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)


def get_ni_executive_basic_table() -> pd.DataFrame:
    """Get Northern Ireland Executive composition data from Wikipedia.

    Extracts historical data from the "Historical composition of the Northern Ireland Executive"
    table at: https://en.wikipedia.org/wiki/Northern_Ireland_Executive#Composition_since_devolution

    Returns:
        DataFrame with Executive index and columns:

        - Established: datetime64[ns] - When the executive was formed
        - Dissolved: datetime64[ns] - When the executive ended
        - Duration: timedelta64[ns] - How long the executive lasted
        - Interregnum: timedelta64[ns] - Gap until next executive

    Example:
        >>> df = get_ni_executive_basic_table()
        >>> print(df.dtypes)
        Established     datetime64[ns]
        Dissolved       datetime64[ns]
        Duration       timedelta64[ns]
        Interregnum    timedelta64[ns]
        dtype: object
    """
    # Use a custom user agent to avoid Wikipedia 403 errors
    # Wikipedia blocks default pandas/urllib user agents
    headers = {
        "User-Agent": "Bolster Data Science Library/0.3.4 (https://github.com/andrewbolster/bolster; andrew.bolster@gmail.com)"
    }
    url = "https://en.wikipedia.org/wiki/Northern_Ireland_Executive"
    response = session.get(url, headers=headers)
    response.raise_for_status()
    tables = pd.read_html(response.text)
    tables[4].columns = range(len(tables[4].columns))

    # Get rid of the nasty multi index
    executive_events = tables[4][[0, 1, 2, 3, 4, 5, 6]]
    executive_events.columns = [
        "Executive",
        "Date",
        "Event",
        "vFM",
        "FM",
        "vDFM",
        "DFM",
    ]

    # Get rid of the comments row at the bottom
    executive_events = executive_events[:-1]

    # Clean up the 'Executive' as for some reason wikipedians count the caretakers differently.
    executive_events["Executive"] = executive_events["Executive"].map(lambda x: x.split("(")[0])

    # Use the OFMDFM posts as a proxy for 'active' to flatten out the range of reasons for failure.
    executive_events["Active"] = (
        executive_events[["vFM", "FM", "vDFM", "DFM"]].replace("Vacant", None).replace(np.nan, None).any(axis=1)
    )

    executive_durations = executive_events.groupby(["Executive", "Active"])["Date"].first().unstack()
    executive_durations.columns = ["Dissolved", "Established"]
    executive_durations = executive_durations[reversed(executive_durations.columns)]
    executive_durations = executive_durations.applymap(lambda s: dateparser.parse(s) if isinstance(s, str) else s)
    executive_durations["Duration"] = executive_durations.diff(axis=1).iloc[:, -1:]

    executive_dissolutions = pd.concat(
        [
            executive_durations["Dissolved"],
            executive_durations["Established"].shift(-1),
        ],
        axis=1,
    )
    executive_dissolutions = executive_dissolutions.apply(
        lambda r: r.Established - r.Dissolved
        if not pd.isnull(r.Established)
        else datetime.datetime.today().replace(hour=0, minute=0, second=0, microsecond=0) - r.Dissolved,
        axis=1,
    )

    executive_durations["Interregnum"] = executive_dissolutions

    # Fix last / most recent
    executive_durations.loc[executive_durations.index[-1], "Duration"] = (
        datetime.datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
        - executive_durations["Established"].iloc[-1]
    )

    return executive_durations


def validate_wikipedia_data(data) -> bool:
    """Validate Wikipedia data integrity.

    Args:
        data: Wikipedia data from functions

    Returns:
        True if validation passes, False otherwise
    """
    if not data:
        logger.warning("Wikipedia data is empty")
        return False

    return True
