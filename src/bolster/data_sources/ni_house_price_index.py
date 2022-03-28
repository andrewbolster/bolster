"""
Working with the Norther Ireland House Price index data

Original Source: https://www.nisra.gov.uk/statistics/housing-community-and-regeneration/northern-ireland-house-price-index

See [here](https://andrewbolster.info/2022/03/NI-House-Price-Index.html) for more details

Generic problems fixed;

* Tables offset from header with notes and annotations
* Inconsistent offset
* Inconsistent treatment of quarterly periods (Q1 2020/Quarter 1 2020/ (2020,Q1) etc)
* Inconsistent header alignment (i.e. leaving sub-category annotations on what is actually the period index header)


"""
import re
from typing import Dict
from typing import Text

import bs4
import pandas as pd
import requests

DEFAULT_URL = "https://www.finance-ni.gov.uk/publications/ni-house-price-index-statistical-reports"
TABLE_TRANSFORMATION_MAP = {}


def pull_source(base_url=DEFAULT_URL) -> Dict[Text, pd.DataFrame]:
    """
    Pull raw NI House Price Index Excel from finance-ni.gov.uk listing

    Parameters
    ----------
    base_url

    Returns
    -------

    """
    base_content = requests.get(base_url).content
    base_soup = bs4.BeautifulSoup(base_content)
    source_url = None
    for a in base_soup.find_all("a"):
        if a.attrs.get("href", "").endswith("xlsx"):
            source_url = a.attrs["href"]

    if source_url is not None:
        source_df = pd.read_excel(source_url, sheet_name=None)  # Load all worksheets in
    else:
        raise RuntimeError(
            f"Could not find valid/relevant Excel source file on {base_url}"
        )

    return source_df


def basic_cleanup(df: pd.DataFrame, offset=1) -> pd.DataFrame:
    """
    Generic cleanup operations for NI HPI data;
    * Re-header from Offset row and translate table to eliminate incorrect headers
    * remove any columns with 'Nan' or 'None' in the given offset-row
    * If 'NI' appears and all the values are 100, remove it.
    * Remove any rows below and including the first 'all nan' row (gets most tail-notes)
    * If 'Sale Year','Sale Quarter' appear in the columns, replace with 'Year','Quarter' respectively
    * For Year; forward fill any none/nan values
    * If Year/Quarter appear, add  a new composite 'Period' column with a PeriodIndex columns representing the
        year/quarter (i.e. 2022-Q1)
    * Reset and drop the index
    * Attempt to infer the new/current column object types

    Parameters
    ----------
    df
    offset

    Returns
    -------

    """
    df = df.copy()
    # Re-header from row 1 (which was row 3 in excel)
    new_header = df.iloc[offset]
    df = df.iloc[offset + 1 :]
    df.columns = new_header

    # remove 'NaN' trailing columns
    df = df[df.columns[pd.notna(df.columns)]]

    # 'NI' is a usually hidden column that appears to be a checksum;
    # if it's all there and all 100, remove it, otherwise, complain.
    # (Note, need to change this 'if' logic to just 'if there's a
    # column with all 100's, but cross that bridge later)
    if "NI" in df:
        assert (
            df["NI"].all() and df["NI"].mean() == 100
        ), "Not all values in df['NI'] == 100"
        df = df.drop("NI", axis=1)

    # Strip rows below the first all-nan row, if there is one
    # (Otherwise this truncates the tables as there is no
    # idxmax in the table of all 'false's)
    if any(df.isna().all(axis=1)):
        idx_first_bad_row = df.isna().all(axis=1).idxmax()
        df = df.loc[: idx_first_bad_row - 1]

    # By Inspection, other tables use 'Sale Year' and 'Sale Quarter'
    if set(df.keys()).issuperset({"Sale Year", "Sale Quarter"}):
        df = df.rename(columns={"Sale Year": "Year", "Sale Quarter": "Quarter"})

    # For 'Year','Quarter' indexed pages, there is an implied Year
    # in Q2/4, so fill it downwards
    if set(df.keys()).issuperset({"Year", "Quarter"}):
        df["Year"] = df["Year"].astype(float).fillna(method="ffill").astype(int)

        # In Pandas we can represent Y/Q combinations as proper datetimes
        # https://stackoverflow.com/questions/53898482/clean-way-to-convert-quarterly-periods-to-datetime-in-pandas
        df.insert(
            loc=0,
            column="Period",
            value=pd.PeriodIndex(
                df.apply(lambda r: f"{r.Year}-{r.Quarter}", axis=1), freq="Q"
            ),
        )

    # reset index, try to fix dtypes, etc, (this should be the last
    # operation before returning!
    df = df.reset_index(drop=True).infer_objects()

    return df


def cleanup_contents(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fix Contents table of NI HPI Stats
    * Shift/rebuild headers
    * Strip Figures because they're gonna be broken anyway

    Parameters
    ----------
    df

    Returns
    -------

    """
    new_header = df.iloc[0]
    df = df[1:].copy()
    df.columns = [*new_header[:-1], "Title"]
    # df['Worksheet Name'] = df['Worksheet Name'].str.replace('Figure', 'Fig')
    df = df[df["Worksheet Name"].str.startswith("Table")]

    return df


TABLE_TRANSFORMATION_MAP["Contents"] = cleanup_contents
# NI HPI Trends
TABLE_TRANSFORMATION_MAP["Table 1"] = basic_cleanup


def cleanup_price_by_property_type_agg(df: pd.DataFrame) -> pd.DataFrame:
    """
    NI HPI & Standardised Price Statistics by Property Type (Aggregate Table)

    Standard cleanup with a split to remove trailing index date data

    Parameters
    ----------
    df

    Returns
    -------

    """
    df = basic_cleanup(df)
    df.columns = [c.split("\n")[0] for c in df.columns]
    return df


# NI HPI & Standardised Price Statistics by Property Type
TABLE_TRANSFORMATION_MAP["Table 2"] = cleanup_price_by_property_type_agg


def cleanup_price_by_property_type(df: pd.DataFrame) -> pd.DataFrame:
    """
    NI HPI & Standardised Price Statistics by Property Type (Per Class)

    Standard cleanup, removing the property class from the table columns

    Parameters
    ----------
    df

    Returns
    -------

    """
    df = basic_cleanup(df)
    new_columns = []
    for c in df.columns:
        if c.endswith("Price Index"):
            new_columns.append("Index")
        elif c.endswith("Standardised Price"):
            new_columns.append("Price")
        else:
            new_columns.append(c)

    df.columns = new_columns

    return df


# NI {property type} Property Price Index
TABLE_TRANSFORMATION_MAP[re.compile("Table 2[a-z]")] = cleanup_price_by_property_type

# NI HPI & Standardised Price Statistics by New/Existing Resold Dwelling Type
TABLE_TRANSFORMATION_MAP["Table 3"] = cleanup_price_by_property_type_agg
TABLE_TRANSFORMATION_MAP[
    re.compile("Table 3[a-z]")
] = cleanup_price_by_property_type_agg


def cleanup_with_munged_quarters_and_total_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Number of Verified Residential Property Sales

    * Regex 'Quarter X' to 'QX' in future 'Sales Quarter' column
    * Drop Year Total rows
    * Clear any Newlines from the future 'Sales Year' column
    * call `basic_cleanup` with offset=3

    Parameters
    ----------
    df

    Returns
    -------

    """
    df = df.copy()
    df.iloc[:, 1] = df.iloc[:, 1].str.replace("Quarter ([1-4])", r"Q\1", regex=True)
    df = df[~df.iloc[:, 1].str.contains("Total").fillna(False)]
    # Lose the year new-lines (needs astype because non str lines are
    # correctly inferred to be ints, so .str methods nan-out
    with pd.option_context("mode.chained_assignment", None):
        df.iloc[:, 0] = df.iloc[:, 0].astype(str).str.replace("\n", "")

    df = basic_cleanup(df, offset=3)
    return df


# Table 4: Number of Verified Residential Property Sales
TABLE_TRANSFORMATION_MAP["Table 4"] = cleanup_with_munged_quarters_and_total_rows


def cleanup_with_LGDs(df):
    """
    Standardised House Price & Index for each Local Government District Northern Ireland
    * Build multi-index of LGD / Metric [Index,Price]

    """
    # Basic Cleanup first
    df = basic_cleanup(df)
    # Build multi-index of LGD / Metric [Index,Price]
    # Two inner-columns per LGD
    lgds = (
        df.columns[3:]
        .str.replace(" Standardised HPI", " HPI")
        .str.replace(" HPI", "")
        .str.replace(" Standardised Price", "")
        .unique()
    )
    df.columns = [
        *df.columns[:3],
        *pd.MultiIndex.from_product(
            [lgds, ["Index", "Price"]], names=["LGD", "Metric"]
        ),
    ]
    return df


# Table 5: Standardised House Price & Index for each Local Government District Northern Ireland
TABLE_TRANSFORMATION_MAP["Table 5"] = cleanup_with_LGDs


def cleanup_merged_year_quarters_and_totals(df):
    """
    Table 5a: Number of Verified Residential Property Sales by Local Government District
    * Parse the 'Sale Year/Quarter' to two separate cols
    * Insert future-headers for Quarter and Year cols
    * Remove rows with 'total' in the first column
    * Disregard the 'Sale Year/Quarter' column
    * perform `basic_cleanup` with offset=2
    """
    # Safety first
    df = df.copy()

    # Extract 'Quarter' and 'Year' columns from the future 'Sale Year/Quarter' column
    dates = (
        df.iloc[:, 0]
        .str.extract("(Q[1-4]) ([0-9]{4})")
        .rename(columns={0: "Quarter", 1: "Year"})
    )
    for c in [
        "Quarter",
        "Year",
    ]:  # insert the dates in order, so they come out in reverse in the insert
        df.insert(1, c, dates[c])
        df.iloc[
            2, 1
        ] = c  # Need to have the right colname for when `basic_cleanup` is called.

    # Remove 'total' rows from the future 'Sale Year/Quarter' column
    df = df[~df.iloc[:, 0].str.contains("Total").fillna(False)]

    # Remove the 'Sale Year/Quarter' column all together
    df = df.iloc[:, 1:]

    # Standard cleanup
    df = basic_cleanup(df, offset=2)

    return df


# Table 5a: Number of Verified Residential Property Sales by Local Government District
TABLE_TRANSFORMATION_MAP["Table 5a"] = cleanup_merged_year_quarters_and_totals
# Table 6: Standardised House Price & Index for all Urban and Rural areas in NI
TABLE_TRANSFORMATION_MAP["Table 6"] = basic_cleanup


def cleanup_missing_year_quarter(df):
    """
    Table 7: Standardised House Price & Index for Rural Areas of Northern Ireland by drive times
    * Insert Year/Quarter future-headers
    * Clean normally
    # TODO THIS MIGHT BE VALID FOR MULTIINDEXING ON DRIVETIME/[Index/Price]
    """
    df = df.copy()
    df.iloc[1, 0] = "Year"
    df.iloc[1, 1] = "Quarter"
    df = basic_cleanup(df)
    return df


# Table 7: Standardised House Price & Index for Rural Areas of Northern Ireland by drive times
TABLE_TRANSFORMATION_MAP["Table 7"] = cleanup_missing_year_quarter

# Table 8: Number of Verified Residential Property Sales of properties in urban and rural areas and properties in rural areas by drive times witihn towns of 10,000 or more and within 1 hour of Belfast
TABLE_TRANSFORMATION_MAP["Table 8"] = cleanup_merged_year_quarters_and_totals

# Table 9: NI Average Sales Prices
TABLE_TRANSFORMATION_MAP["Table 9"] = basic_cleanup
TABLE_TRANSFORMATION_MAP[re.compile("Table 9[a-z]")] = cleanup_missing_year_quarter

# Table 10x: Number of Verified Residential Property Sales by Type in {LDG}
TABLE_TRANSFORMATION_MAP[
    re.compile("Table 10[a-z]")
] = cleanup_merged_year_quarters_and_totals


def cleanup_source(source_df: Dict[Text, pd.DataFrame]) -> Dict[Text, pd.DataFrame]:
    """
    Cleanup all the tables from the NI Housing Price Index, conforming to the best attempt at a 'standard'

    Parameters
    ----------
    source_df

    Returns
    -------

    """
    dest_df = {}
    for table_key, table_transformer in TABLE_TRANSFORMATION_MAP.items():
        if isinstance(table_key, re.Pattern):
            for table in source_df:
                if table_key.match(table):
                    dest_df[table] = table_transformer(source_df[table])
        else:
            dest_df[table_key] = table_transformer(source_df[table_key])

    return dest_df


def build():
    """
    Pulls and Cleans up the latest Northern Ireland House Price Index Data

    Returns
    -------

    """
    source_dfs = pull_source()
    dest_dfs = cleanup_source(source_dfs)
    return dest_dfs
