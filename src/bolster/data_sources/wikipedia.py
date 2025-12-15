import datetime

import dateparser
import numpy as np
import pandas as pd
import requests


def get_ni_executive_basic_table() -> pd.DataFrame:
    """
    Takes Data from https://en.wikipedia.org/wiki/Northern_Ireland_Executive#Composition_since_devolution
    Table should be called "Historical composition of the Northern Ireland Executive "

    EG
            Established	Dissolved	Duration	Interregnum
    Executive
    1st	1998-07-01	2002-10-14	1566 days	1667 days
    2nd	2007-05-08	2011-03-24	1416 days	53 days
    3rd	2011-05-16	2016-05-16	1827 days	10 days
    4th	2016-05-26	2017-01-16	235 days	1090 days
    5th	2020-01-11	2022-02-03	754 days	730 days
    6th	2024-02-03	NaT	127 days	NaT

    >>> get_ni_executive_basic_table().dtypes
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
    response = requests.get(url, headers=headers)
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
