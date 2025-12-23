# NISRA Q2 2024 Data Validation Report

Generated: 2025-12-23

This report contains parsed Q2 2024 statistics from NISRA data sources. These figures should be manually cross-validated against official bulletins.

______________________________________________________________________

## 1. NI COMPOSITE ECONOMIC INDEX (NICEI) - Q2 2024

**Source:** NISRA Economic Output Statistics
**Publication:** NI Composite Economic Index Q2 2024
**Publication URL:** https://www.nisra.gov.uk/publications/ni-composite-economic-index-q2-2024
**Published:** September 26, 2024

### Parsed Headline Figures:

- **Overall NICEI:** 103.36 (base: 2022=100)
- **Year-on-Year Growth:** +2.05%
- **Quarter-on-Quarter Growth:** +0.67% (vs Q1 2024: 102.67)

### Sector Breakdown:

| Sector | Index Value |
|--------|-------------|
| Private Sector | 103.99 |
| Public Sector | 101.30 |
| Services | 105.02 |
| Production | 96.11 |
| Construction | 113.64 |
| Agriculture | 98.18 |

### Validation Notes:

- Data source: NICEI Excel tables parsed via `composite_index.py`
- Base year: 2022=100
- Status: Requires manual validation against PDF bulletin

______________________________________________________________________

## 2. CONSTRUCTION OUTPUT - Q2 2024

**Source:** NISRA Economic Output Statistics
**Publication:** Construction Output Statistics Q2 2024
**Publication URL:** https://www.nisra.gov.uk/publications/construction-output-statistics-q2-2024
**Published:** September 26, 2024
**PDF Bulletin:** https://www.nisra.gov.uk/system/files/statistics/NIconq22024.pdf

### Parsed Headline Figures:

- **All Work Index:** 112.4 (base: 2022=100)
- **Year-on-Year Growth:** +7.39%
- **Quarter-on-Quarter Growth:** +4.43% (vs Q1 2024: 107.6)

### Breakdown:

| Category | Index Value |
|----------|-------------|
| New Work | 101.9 |
| Repair & Maintenance | 134.4 |

### Validation Notes:

- Data source: Construction Output Excel tables parsed via `construction_output.py`
- Base year: 2022=100
- All Work and New Work: Not seasonally adjusted (NSA)
- Repair & Maintenance: Seasonally adjusted (SA)
- Status: Requires manual validation against PDF bulletin

______________________________________________________________________

## 3. INDEX OF SERVICES - Q2 2024

**Source:** NISRA Economic Output Statistics
**Publication:** Index of Services Q2 2024
**Publication URL:** https://www.nisra.gov.uk/publications/index-services-ios-statistical-bulletin-and-tables-quarter-2-2024
**Published:** September 12, 2024

### Parsed Headline Figures:

- **NI Services Index:** 102.6 (base: 2022=100)
- **UK Services Index:** 101.7 (base: 2022=100)
- **NI Year-on-Year Growth:** +3.22%
- **NI Quarter-on-Quarter Growth:** +1.29% (vs Q1 2024: 101.3)

### Validation Notes:

- Data source: Index of Services Excel tables parsed via `economic_indicators.py`
- Base year: 2022=100
- NI outperformed UK in Q2 2024 (102.6 vs 101.7)
- Status: Requires manual validation against PDF bulletin

______________________________________________________________________

## 4. LABOUR MARKET - Q2 2024 (April-June 2024)

**Source:** NISRA Labour Market Statistics
**Publication:** Labour Market Report August 2024 (covering Apr-Jun 2024 period)
**Publication URL:** https://www.nisra.gov.uk/publications/labour-market-report-august-2024
**Note:** Labour Market uses Apr-Jun format rather than Q2

### Key Indicators (from latest parsed data):

The Labour Market data follows a rolling 3-month period format (e.g., "April to June 2024") rather than standard quarterly reporting.

**Economic Inactivity Rate** is available from parsed quarterly tables.

### Validation Notes:

- Data source: Labour Force Survey quarterly tables parsed via `labour_market.py`
- Labour Market reports use 3-month rolling periods
- The August 2024 report would contain April-June 2024 data
- Key metrics to validate:
  - Employment rate (ages 16-64)
  - Unemployment rate
  - Economic inactivity rate
  - Year-on-year changes
- Status: Requires manual validation against Labour Market Report bulletin

______________________________________________________________________

## Validation Checklist

To manually validate these figures against official NISRA bulletins:

### 1. Access NISRA Publications

- Visit: https://www.nisra.gov.uk/publications
- Filter by year: 2024
- Search for Q2 2024 bulletins

### 2. Download Official PDF Bulletins

- NICEI Q2 2024 PDF bulletin
- Construction Output Q2 2024 PDF bulletin (https://www.nisra.gov.uk/system/files/statistics/NIconq22024.pdf)
- Index of Services Q2 2024 PDF bulletin
- Labour Market Report August 2024 (for Apr-Jun data)

### 3. Cross-check Headline Figures

Compare the following from PDF bulletins:

- Index values (base 2022=100)
- Year-on-year growth rates
- Quarter-on-quarter growth rates
- Sector breakdowns
- Any data revisions or methodological notes

### 4. Common Discrepancies to Watch For

- **Revised vs Provisional Figures:** Earlier quarters may have been revised
- **Seasonally Adjusted vs Non-Seasonally Adjusted:**
  - Construction: All Work and New Work are NSA; R&M is SA
  - Check bulletin footnotes for adjustment status
- **Base Year Changes:** All indices use 2022=100
- **Methodological Updates:** Note any changes in calculation methods

### 5. Data Revision Notes

NISRA routinely revises previous quarters' data when new information becomes available. Check bulletin text for:

- Revisions to Q1 2024 or earlier quarters
- Changes in seasonal adjustment factors
- Updates to benchmark data

______________________________________________________________________

## Summary Statistics Comparison

| Indicator | Q2 2024 Value | YoY Growth | QoQ Growth |
|-----------|---------------|------------|------------|
| NICEI | 103.36 | +2.05% | +0.67% |
| Construction Output (All Work) | 112.4 | +7.39% | +4.43% |
| Index of Services (NI) | 102.6 | +3.22% | +1.29% |

### Key Observations:

1. **Construction sector** showed strongest growth (+7.39% YoY)
1. **Services sector** outperformed (+3.22% YoY)
1. **Overall economy** (NICEI) grew moderately (+2.05% YoY)
1. **NI Services outperformed UK** (102.6 vs 101.7)

______________________________________________________________________

## Known Publication URLs

### Successfully Located:

- **Construction Output Q2 2024:** https://www.nisra.gov.uk/publications/construction-output-statistics-q2-2024

  - PDF: https://www.nisra.gov.uk/system/files/statistics/NIconq22024.pdf
  - Excel Tables available

- **Index of Services Q2 2024:** https://www.nisra.gov.uk/publications/index-services-ios-statistical-bulletin-and-tables-quarter-2-2024

  - Published: September 12, 2024
  - Excel Tables available

### Requires Further Investigation:

- **NICEI Q2 2024:** Direct publication link returned 403 error

  - Try: https://www.nisra.gov.uk/publications/nicei-q2-2024
  - Or search archive: https://www.nisra.gov.uk/publications/archive-publications-ni-composite-economic-index

- **Labour Market August 2024:** Main publication page accessible

  - URL: https://www.nisra.gov.uk/publications/labour-market-report-august-2024
  - Contains Apr-Jun 2024 quarterly data
  - Requires accessing linked Excel files for detailed statistics

______________________________________________________________________

## Data Sources and Parsers

All data extracted using custom NISRA parsers:

- `/Users/bolster/src/bolster/src/bolster/data_sources/nisra/composite_index.py`
- `/Users/bolster/src/bolster/src/bolster/data_sources/nisra/construction_output.py`
- `/Users/bolster/src/bolster/src/bolster/data_sources/nisra/economic_indicators.py`
- `/Users/bolster/src/bolster/src/bolster/data_sources/nisra/labour_market.py`

Parsers automatically:

1. Scrape NISRA publication pages for latest data
1. Download Excel files
1. Parse structured tables
1. Return pandas DataFrames with standardized schemas

______________________________________________________________________

## Next Steps

1. **Manual PDF Validation:** Download and review Q2 2024 PDF bulletins to confirm:

   - Headline index values match
   - Growth rate calculations are consistent
   - No significant data revisions affecting Q2 2024

1. **Press Release Review:** Check for NISRA press releases that may contain:

   - Key messages and interpretations
   - Special notes about data quality
   - Commentary on economic conditions

1. **Methodology Check:** Review any methodology papers or notes for:

   - Changes in data collection
   - Updates to seasonal adjustment
   - Rebasing or reclassification

1. **Historical Comparison:** Validate Q2 2024 against historical trends:

   - Is growth within expected range?
   - Any unusual patterns or outliers?
   - Consistency with UK-wide trends?

______________________________________________________________________

**Report Status:** PRELIMINARY - Requires Manual Validation
**Last Updated:** 2025-12-23
**Generated By:** Claude Code (NISRA Data Parsers)
