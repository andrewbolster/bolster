### PSNI (Police Service of Northern Ireland) Data Sources

Comprehensive access to PSNI open data for Northern Ireland crime statistics.

## Overview

This module provides programmatic access to Police Service of Northern Ireland (PSNI) crime statistics through OpenDataNI. The data is published quarterly under the Open Government Licence v3.0.

**Key Features:**

- **Monthly crime statistics** from April 2001 onwards (20+ years)
- **Geographic breakdown** by 11 Policing Districts (aligned with LGDs)
- **21 crime categories** based on Home Office classifications
- **Outcome data** including charges, cautions, and resolution rates
- **Cross-dataset integration** via LGD and NUTS3 geographic codes
- **Automatic caching** to minimize bandwidth usage

## ⚠️ Data Limitation Notice

**IMPORTANT**: The OpenDataNI dataset was last updated in **January 2022** and only contains data through **December 2021**. This dataset has not been updated in over 4 years.

For **2022-2025 crime statistics**, you will need to:

- Consult PSNI's quarterly PDF bulletins at [PSNI Official Statistics](https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-recorded-crime-statistics)
- Contact PSNI Statistics Branch: statistics@psni.police.uk
- Manually extract data from published reports

The module will automatically warn you about data staleness when you load the statistics.

## Quick Start

```python
from bolster.data_sources.psni import crime_statistics

# Get latest crime data (NOTE: only through December 2021)
df = crime_statistics.get_latest_crime_statistics()
# ⚠️  Data is 4.1 years old (latest: December 2021). OpenDataNI dataset has not been updated...

print(df.head())

# Filter to Belfast
belfast = crime_statistics.filter_by_district(df, "Belfast City")

# Get total crimes by district for 2021
totals = crime_statistics.get_total_crimes_by_district(df, year=2021)
print(totals.sort_values("total_crimes", ascending=False))
```

## Data Source

**Primary Source:** [OpenDataNI - Police Recorded Crime in Northern Ireland](https://www.opendatani.gov.uk/dataset/police-recorded-crime-in-northern-ireland)

**PSNI Official Statistics:** https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-recorded-crime-statistics

**Update Frequency:** ~~Quarterly~~ **STALE SINCE JANUARY 2022**

- ~~End of July (data to 30 June)~~
- ~~End of October (data to 30 September)~~
- ~~End of January (data to 31 December)~~
- ~~End of May (data to 31 March - completed financial year)~~
- **Last update:** January 27, 2022 (data through December 2021)

**Geographic Coverage:** Northern Ireland
**Time Coverage:** April 2001 to **December 2021** (OpenDataNI dataset)
**Licence:** Open Government Licence v3.0

## Available Datasets

| Dataset | Function | Description |
|---------|----------|-------------|
| Crime Statistics | `get_latest_crime_statistics()` | Monthly police recorded crime by district and type |

## Geographic Breakdowns

### Policing Districts (11)

The 11 Policing Districts map 1:1 to Northern Ireland's Local Government Districts (LGDs), enabling cross-comparison with other NISRA datasets:

| Policing District | LGD Code | NUTS3 Code | Region |
|-------------------|----------|------------|---------|
| Belfast City | N09000003 | UKN01 | Belfast |
| Lisburn & Castlereagh City | N09000007 | UKN06 | Outer Belfast |
| Antrim & Newtownabbey | N09000001 | UKN06 | Outer Belfast |
| Ards & North Down | N09000011 | UKN06 | Outer Belfast |
| Armagh City Banbridge & Craigavon | N09000002 | UKN05 | West and South of NI |
| Newry Mourne & Down | N09000010 | UKN05 | West and South of NI |
| Mid Ulster | N09000009 | UKN05 | West and South of NI |
| Fermanagh & Omagh | N09000006 | UKN03 | West and South of NI |
| Derry City & Strabane | N09000005 | UKN02 | Outer Belfast |
| Causeway Coast & Glens | N09000004 | UKN04 | East of NI |
| Mid & East Antrim | N09000008 | UKN04 | East of NI |

### Geographic Codes

Each crime record includes:

- **LGD Code**: ONS Local Government District code (e.g., `N09000003`)
- **NUTS3 Code**: European regional code (e.g., `UKN01`)
- **NUTS3 Name**: Region name (e.g., "Belfast")

These codes enable integration with other datasets:

```python
# Get geographic codes for cross-referencing
lgd = crime_statistics.get_lgd_code("Belfast City")  # Returns: N09000003
nuts3 = crime_statistics.get_nuts3_code("Belfast City")  # Returns: UKN01

# Filter crime data and cross-reference with NISRA population data
from bolster.data_sources.nisra import population

crime_df = crime_statistics.get_latest_crime_statistics()
pop_df = population.get_latest_population(area="Northern Ireland")

# Join on LGD code for district-level analysis
# (both datasets use the same LGD codes)
```

## Crime Categories

**21 Crime Types** based on Home Office Crime Classifications:

### Violence Crimes

1. Violence with injury (including homicide & death/serious injury by unlawful driving)
1. Violence without injury
1. Harassment
1. Sexual offences

### Property Crimes

5. Robbery
1. Theft - domestic burglary (pre-2017)
1. Theft - non-domestic burglary (pre-2017)
1. Theft - burglary residential (2017+)
1. Theft - burglary business & community (2017+)
1. Theft from the person
1. Theft - vehicle offences
1. Bicycle theft
1. Theft - shoplifting
1. All other theft offences

### Other Crimes

15. Criminal damage
01. Trafficking of drugs
01. Possession of drugs
01. Possession of weapons offences
01. Public order offences
01. Miscellaneous crimes against society

### Aggregate

21. Total police recorded crime

**Note:** Burglary classification changed in April 2017. Residential/Business & Community burglary is a NEW data series and cannot be added to domestic/non-domestic burglary for historical comparison.

## Data Measures

Three types of measures are available:

1. **Police Recorded Crime**: Count of crimes reported to police
1. **Police Recorded Crime Outcomes (number)**: Count of crimes with outcomes
1. **Police Recorded Crime Outcomes (rate %)**: Outcome rate as percentage

**Outcome Types Include:**

- Charge/summons
- Cautions (adult and juvenile)
- Community resolutions
- Penalty notices for disorder
- Offences taken into consideration
- Indictable only offences where no action taken

## Usage Examples

### Basic Data Access

```python
from bolster.data_sources.psni import crime_statistics

# Get all crime data
df = crime_statistics.get_latest_crime_statistics()

# Inspect the data
print(df.head())
print(f"Total records: {len(df):,}")
print(f"Date range: {df['date'].min()} to {df['date'].max()}")
print(f"Districts: {df['policing_district'].nunique()}")
```

### Filtering Data

```python
# Filter by district
belfast = crime_statistics.filter_by_district(df, "Belfast City")

# Multiple districts
cities = crime_statistics.filter_by_district(
    df, ["Belfast City", "Derry City & Strabane", "Lisburn & Castlereagh City"]
)

# Filter by crime type
violence = crime_statistics.filter_by_crime_type(
    df, "Violence with injury (including homicide & death/serious injury by unlawful driving)"
)

# Filter by date range
recent = crime_statistics.filter_by_date_range(df, "2020-01-01", "2021-12-31")

# Combine filters
belfast_violence_2021 = crime_statistics.filter_by_district(
    crime_statistics.filter_by_crime_type(
        crime_statistics.filter_by_date_range(df, "2021-01-01", "2021-12-31"),
        "Violence with injury (including homicide & death/serious injury by unlawful driving)",
    ),
    "Belfast City",
)
```

### Analysis Functions

```python
# Total crimes by district for specific year
totals_2021 = crime_statistics.get_total_crimes_by_district(df, year=2021)
print(totals_2021.sort_values("total_crimes", ascending=False))

# Crime trends over time
trends = crime_statistics.get_crime_trends(
    df,
    crime_type="Violence with injury (including homicide & death/serious injury by unlawful driving)",
    district="Belfast City",
)

# Plot trends
import matplotlib.pyplot as plt

trends.set_index("date")["count"].plot(figsize=(12, 6))
plt.title("Belfast Violence Trends")
plt.ylabel("Monthly Crime Count")
plt.show()

# Outcome rates by district
outcomes = crime_statistics.get_outcome_rates_by_district(df, year=2021)
print(outcomes.sort_values("average_outcome_rate", ascending=False))
```

### Discover Available Data

```python
# Get list of all crime types
crime_types = crime_statistics.get_available_crime_types(df)
for crime_type in crime_types:
    print(f"- {crime_type}")

# Get list of all districts
districts = crime_statistics.get_available_districts(df)
for district in districts:
    lgd = crime_statistics.get_lgd_code(district)
    print(f"{district}: {lgd}")
```

### Cross-Dataset Integration

```python
from bolster.data_sources.psni import crime_statistics
from bolster.data_sources.nisra import population

# Get crime and population data
crime_df = crime_statistics.get_latest_crime_statistics()
pop_df = population.get_latest_population(area="Northern Ireland")

# Calculate crime rate per 1000 population for 2021
# Filter to 2021 total crimes
crimes_2021 = crime_statistics.get_total_crimes_by_district(crime_df, year=2021)

# Filter to 2021 population (all persons)
pop_2021 = (
    pop_df[(pop_df["year"] == 2021) & (pop_df["sex"] == "All persons")]
    .groupby("area_code")["population"]
    .sum()
    .reset_index()
)

# Merge on LGD code
merged = crimes_2021.merge(pop_2021, left_on="lgd_code", right_on="area_code", how="inner")

# Calculate rate per 1000 population
merged["crime_rate_per_1000"] = (merged["total_crimes"] / merged["population"]) * 1000

print(
    merged[["policing_district", "total_crimes", "population", "crime_rate_per_1000"]].sort_values(
        "crime_rate_per_1000", ascending=False
    )
)
```

## Data Quality and Validation

### Validation

All data passes comprehensive validation checks:

```python
# Run validation
crime_statistics.validate_crime_statistics(df)
# Returns: True (if validation passes)
```

**Validation Checks:**

- Non-negative crime counts
- Reasonable date ranges (2001 onwards, not future)
- Expected policing districts present
- Valid LGD and NUTS3 codes
- Outcome rates within 0-100% range

### Known Data Issues

1. **Burglary Classification Change (April 2017)**

   - Pre-2017: Domestic/Non-domestic burglary
   - Post-2017: Residential/Business & Community burglary
   - **These are NEW data series** - cannot be combined for historical comparison

1. **Special Values**

   - `/0` in count column: Outcome rate could not be calculated (converted to `NA`)
   - `0`: No crimes recorded OR outcome rate calculated as zero

1. **Provisional Data**

   - In-year data is subject to revision each quarter
   - Annual revisions may occur for 2015/16 onwards

### Data Quality Standards

- **National Crime Recording Standard (NCRS)**: Used since 2002
- **Home Office Counting Rules (HOCR)**: Official counting methodology

## Limitations

### Geographic Granularity

**Available:**

- ✅ Policing District level (11 districts)
- ✅ Northern Ireland total
- ✅ LGD code mapping for cross-dataset integration
- ✅ NUTS3 regional aggregation

**Not Publicly Available:**

- ❌ Postcode level
- ❌ Data Zones
- ❌ Super Output Areas (SOAs)
- ❌ Electoral Wards

For postcode or small-area analysis, contact PSNI Statistics (statistics@psni.police.uk) for bespoke data requests.

### Alternative Sources

**For street-level data:**

- police.uk API: https://data.police.uk
- Anonymized street coordinates available
- **Limitations for NI:** No outcome data, limited time coverage

## Cache Management

Data is automatically cached to minimize bandwidth usage:

```python
# Force refresh (bypass cache)
df = crime_statistics.get_latest_crime_statistics(force_refresh=True)

# Clear cached files
crime_statistics.clear_cache()

# Cache location: ~/.cache/bolster/psni/
# Cache TTL: 90 days (quarterly updates)
```

## Data Reference

### File Structure

**Source:** CSV file (16.7 MB, 188,000+ rows as of December 2021)

**Columns:**

- `calendar_year`: Year of crime (int)
- `month`: Month name (str: Apr, May, Jun, ...)
- `policing_district`: Geographic area (str)
- `crime_type`: Home Office crime classification (str)
- `data_measure`: Type of measure (str)
- `count`: Value (float - can be count or percentage)
- `date`: First day of month (datetime)
- `lgd_code`: ONS LGD code (str)
- `nuts3_code`: NUTS3 region code (str)
- `nuts3_name`: NUTS3 region name (str)

### Contact

**PSNI Statistics:**

- Email: statistics@psni.police.uk
- Website: https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics

**OpenDataNI:**

- Email: opendatani@nidirect.gov.uk
- Website: https://www.opendatani.gov.uk

## See Also

- **NISRA Population**: Cross-reference for crime rates per capita
- **NISRA Birth/Deaths**: Demographic context
- **NISRA Economic Indicators**: Socioeconomic factors
- **Data Source Development Guide**: `docs/data_source_development.rst`

## License

Data is provided under the Open Government Licence v3.0.

Integration code is part of the Bolster library (see main LICENSE file).
