# PSNI Crime Statistics Data Sources Research

**Research Date:** 2025-12-26\
**Researcher:** Claude Code Agent

## Executive Summary

PSNI (Police Service of Northern Ireland) crime statistics are primarily available through OpenDataNI and the PSNI official website. The **most granular publicly available geographic breakdown is at the Policing District level** (11 districts), which corresponds to the 11 Local Government Districts (Council Areas) of Northern Ireland. **Postcode-level and smaller geographic area data are not publicly available in standard downloads.**

______________________________________________________________________

## 1. PSNI Official Statistics Pages

### Access Status

- **Website:** https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics
- **Status:** Website uses Cloudflare protection that blocks automated access
- **Alternative Access:** Data is mirrored on OpenDataNI (https://www.opendatani.gov.uk) and data.gov.uk

### Key Publications

- **Police Recorded Crime in Northern Ireland Annual Trends** - Main publication with detailed crime type breakdowns
- **User Guide to Police Recorded Crime Statistics** - Methodology and process changes documentation
- **Monthly Updates** - Quarterly data releases within financial years

______________________________________________________________________

## 2. Available Data Sources

### 2.1 OpenDataNI / data.gov.uk Datasets

#### Primary Dataset: Police Recorded Crime in Northern Ireland

- **Publisher:** OpenDataNI
- **URL:** https://www.opendatani.gov.uk/dataset/police-recorded-crime-in-northern-ireland
- **Last Updated:** 31 January 2022 (note: this may not reflect latest data additions)
- **Licence:** Open Government Licence v3.0

**Available Data Files:**

| File | Format | Time Coverage | Geographic Level | Update Frequency |
|------|--------|---------------|------------------|------------------|
| Police Recorded Crime Monthly Data | CSV | Apr 2001 onwards (2001/02 FY) | **Policing District + Northern Ireland total** | Quarterly |
| Police Recorded Crime (Administrative Geographies) | ODS | 2001/02 onwards | Various admin geographies | Not specified |
| Police Recorded Crime - Victim Age | CSV | Apr 2007 onwards (2007/08 FY) | **Northern Ireland level only** | Quarterly |
| Police Recorded Crime - Victim Gender | CSV | Apr 2007 onwards (2007/08 FY) | **Northern Ireland level only** | Quarterly |
| Police Recorded Crime Data Guide | PDF | N/A | N/A | Reference document |

**Download URLs:**

- Monthly Data: `https://admin.opendatani.gov.uk/dataset/80dc9542-7b2a-48f5-bbf4-ccc7040d36af/resource/6fd51851-df78-4469-98c5-4f06953621a0/download/police-recorded-crime-monthly-data.csv`
- Data Guide: `https://admin.opendatani.gov.uk/dataset/80dc9542-7b2a-48f5-bbf4-ccc7040d36af/resource/51cd6a9e-646b-42bf-9daa-8d2cb618764e/download/police-recorded-crime-data-guide.pdf`
- Victim Age: `https://admin.opendatani.gov.uk/dataset/80dc9542-7b2a-48f5-bbf4-ccc7040d36af/resource/ef39c95a-2e47-407a-8526-93bf29b3e87b/download/police-recorded-crime-victim-age.csv`
- Victim Gender: `https://admin.opendatani.gov.uk/dataset/80dc9542-7b2a-48f5-bbf4-ccc7040d36af/resource/9c6c3112-f98f-48b8-93a9-75df50125b8e/download/police-recorded-crime-victim-gender.csv`

#### Additional PSNI Datasets on data.gov.uk

| Dataset | Publisher | Last Updated | Geographic Coverage |
|---------|-----------|--------------|---------------------|
| Domestic Abuse Incidents and Crimes | OpenDataNI | 8 December 2017 | Financial year basis, NI level |
| Anti-Social Behaviour Incidents | OpenDataNI | 31 May 2023 | Financial year basis, NI level |
| Incidents and Crimes with Hate Motivation | OpenDataNI | Various | Financial year basis, NI level |
| Police Recorded Injury Road Traffic Collisions | OpenDataNI/PSNI | Various (2013-2022) | NI level |
| PSNI Street Crime Data (police.uk API) | OpenDataNI | 19 February 2016 | **Street-level (anonymized)** |

### 2.2 police.uk API (Street-Level Crime Data)

- **Website:** https://data.police.uk
- **API Docs:** https://data.police.uk/docs
- **Geographic Coverage:** England, Wales, and **Northern Ireland** (PSNI data included)
- **Geographic Granularity:** **Street-level anonymized coordinates**
  - Crimes mapped to street center points or public places
  - Locations must have 8+ postal addresses or no addresses (privacy protection)
  - Not true postcode-level data
- **Time Coverage:** November 2022 to October 2025 (monthly updates)
- **Crime Categories:** 14 standardized categories (Home Office classifications)
- **Outcome Data:** **NOT available for PSNI** (only available for England/Wales forces)
- **Access Method:** API with lat/long coordinates or custom areas within 1-mile radius
- **Stop and Search:** Not available for Northern Ireland

______________________________________________________________________

## 3. NISRA Signposting

### NISRA Role

- **Website:** https://www.nisra.gov.uk
- **Crime and Justice Section:** https://www.nisra.gov.uk/statistics/crime-and-justice
- **Function:** NISRA acts as a **directory/signposting service** rather than data host for PSNI data

### NISRA References to PSNI Data

- NISRA "Popular statistics" section includes link: **"PSNI recorded crime"** → https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-recorded-crime-statistics
- NISRA provides contact: **statistics@psni.police.uk** for police-related statistical inquiries
- NISRA hosts other justice statistics (courts, prisons, prosecutions) but **not police recorded crime**

### NINIS (Northern Ireland Neighbourhood Information Service)

- **Historical URL:** http://www.ninis2.nisra.gov.uk
- **Status:** **DISCONTINUED** - now redirects to https://datavis.nisra.gov.uk/dissemination/NINIS-redirect.html
- **Previous Function:** Hosted administrative geography breakdowns of crime data
- **Current Status:** NINIS crime data may be archived or migrated; specific replacement unclear

______________________________________________________________________

## 4. Geographic Breakdowns Available

### 4.1 Confirmed Geographic Levels in Monthly Data CSV

**Policing Districts (11 districts matching Local Government Districts):**

1. Northern Ireland (total)
1. Belfast City
1. Lisburn & Castlereagh City
1. Ards & North Down
1. Newry Mourne & Down
1. Armagh City Banbridge & Craigavon
1. Mid Ulster
1. Fermanagh & Omagh
1. Derry City & Strabane
1. Causeway Coast & Glens
1. Mid & East Antrim
1. Antrim & Newtownabbey

**Important Note:** These Policing Districts align with the **11 Local Government Districts** (Council Areas) established in Northern Ireland in 2015, enabling cross-comparison with other administrative datasets.

### 4.2 Geographic Levels NOT Publicly Available

Based on research, the following granular geographic breakdowns are **not available** in standard public downloads:

- ❌ **Postcode level** - Not available
- ❌ **Data Zones** - Not available in current public datasets
- ❌ **Super Output Areas (SOAs)** - Not available in current public datasets
- ❌ **Electoral Wards** - Not available in current public datasets
- ❌ **NUTS regions** - Not relevant (Northern Ireland is NUTS1 region; would need NUTS2/3 which don't match policing districts)

**Note on Administrative Geographies ODS file:** The file listed on OpenDataNI (http://www.ninis2.nisra.gov.uk/Download/Crime%20and%20Justice/Police%20Recorded%20Crime%20(administrative%20geographies).ods) now redirects to NINIS discontinuation notice. This file may have historically contained additional geographic breakdowns but is no longer accessible via standard channels.

### 4.3 Street-Level Data (police.uk API)

- **Available:** Yes, through police.uk API
- **Granularity:** Anonymized street-level coordinates
- **Privacy Protection:** Snapped to street center points or public places with 8+ addresses
- **Not True Postcode Data:** Coordinates are aggregated/anonymized, not precise addresses
- **Limitations for NI:**
  - No outcome data provided by PSNI (unlike England/Wales)
  - No stop and search data
  - Time coverage limited (Nov 2022 - Oct 2025)

______________________________________________________________________

## 5. Data Structure and Content

### 5.1 CSV File Structure (Police Recorded Crime Monthly Data)

**File Size:** 16.7MB (188,245 rows as of download)\
**Format:** CSV (comma-separated)\
**Time Coverage:** April 2001 to December 2021 (20+ years)\
**Update Schedule:** Quarterly

- End of July (data to 30 June)
- End of October (data to 30 September)
- End of January (data to 31 December)
- End of May (data to 31 March - completed financial year)

**Column Structure:**

| Column | Description | Values |
|--------|-------------|--------|
| `Calendar_Year` | Year of reported crime | 2001, 2002, ..., 2021 |
| `Month` | Month of reported crime | Apr, May, Jun, ..., Dec |
| `Policing_District` | Geographic area | Northern Ireland, Belfast City, etc. (12 values) |
| `Crime_Type` | Home Office classification | 21 crime types (see below) |
| `Data_Measure` | Type of metric | Police Recorded Crime, Outcomes (number), Outcomes (rate %) |
| `Count` | Value | Numeric count or percentage |

### 5.2 Crime Categories (21 types)

Based on **Home Office Crime Classifications**:

**Violence Crimes:**

1. Violence with injury (including homicide & death/serious injury by unlawful driving)
1. Violence without injury (including harassment)
1. Harassment (separate category from 2017)
1. Sexual offences

**Robbery:**
5\. Robbery

**Burglary (Classification Changed April 2017):**

- **Pre-2017:**
  6\. Theft - domestic burglary
  7\. Theft - non-domestic burglary
- **Post-2017 (new series, not additive with old):**
  8\. Theft - burglary residential
  9\. Theft - burglary business & community

**Theft Offences:**
10\. Theft from the person
11\. Theft - vehicle offences
12\. Bicycle theft
13\. Theft - shoplifting
14\. All other theft offences

**Other Crimes:**
15\. Criminal damage
16\. Trafficking of drugs
17\. Possession of drugs
18\. Possession of weapons offences
19\. Public order offences
20\. Miscellaneous crimes against society

**Aggregate:**
21\. Total police recorded crime

### 5.3 Data Measures Available

1. **Police Recorded Crime** - Count of crimes reported to police
1. **Police Recorded Crime Outcomes (number)** - Count of crimes with outcomes
1. **Police Recorded Crime Outcomes (rate %)** - Outcome rate as percentage

**Outcome Types Include:**

- Charge/summons
- Cautions (adult and juvenile)
- Community resolutions (formerly discretionary disposals)
- Penalty notices for disorder
- Offences taken into consideration
- Indictable only offences where no action taken (died before proceedings or PPS did not prosecute)

**Special Values:**

- `/0` = Outcome rate could not be calculated (distinct from 0)
- `0` = No crimes recorded OR outcome rate calculated as zero

### 5.4 Victim Demographics (Separate Files)

**Victim Age File:**

- **Time Coverage:** April 2007 onwards (2007/08 FY)
- **Geographic Coverage:** **Northern Ireland level ONLY** (no district breakdowns)
- **Age Bands:** \<18, 18-19, 20-24, 25-29, 30-34, 35-39, 40-44, 45-49, 50-54, 55-59, 60-64, 65+, age unknown, all ages
- **Crime Types:** 10 categories (consolidated compared to main dataset)
- **Additional Measure:** Population rate per 1000 population by age band
- **Exclusions:** State-based crimes, non-person victims (businesses/councils), police officers on duty

**Victim Gender File:**

- **Time Coverage:** April 2007 onwards (2007/08 FY)
- **Geographic Coverage:** **Northern Ireland level ONLY**
- **Gender Categories:** Female, Male, Gender unknown, Total
- **Crime Types:** 10 categories (consolidated)
- **Additional Measure:** Population rate per 1000 population by gender
- **Exclusions:** Same as victim age file

______________________________________________________________________

## 6. Data Quality and Revisions

### Provisional Data

- **In-year data:** Subject to revision each quarter during current financial year
- **Completed years:** Annual revisions may occur for 2015/16 onwards

### Recording Standards

- **National Crime Recording Standard (NCRS)** - Used since 2002
- **Home Office Counting Rules (HOCR)** - Official counting methodology

### Known Data Breaks

- **Burglary Classification Change (April 2017):** Residential/Business & Community burglary is a NEW data series, cannot be added to domestic/non-domestic burglary for historical comparison
- **Harassment:** Became separate category (check data guide for exact date)

______________________________________________________________________

## 7. Geographic Code Mappings and Lookup Tables

### Council Area / Policing District Alignment

The 11 Policing Districts correspond exactly to Northern Ireland's 11 Local Government Districts (established 2015). Since NUTS 2016, each LGD maps 1:1 to its own NUTS3 region:

| Policing District | LGD Code | NUTS3 Code | NUTS3 Region Name |
|-------------------|----------|------------|-------------------|
| Antrim & Newtownabbey | N09000001 | UKN0D | Antrim and Newtownabbey |
| Ards & North Down | N09000011 | UKN09 | Ards and North Down |
| Armagh City Banbridge & Craigavon | N09000002 | UKN07 | Armagh City, Banbridge and Craigavon |
| Belfast City | N09000003 | UKN06 | Belfast |
| Causeway Coast & Glens | N09000004 | UKN0C | Causeway Coast and Glens |
| Derry City & Strabane | N09000005 | UKN0A | Derry City and Strabane |
| Fermanagh & Omagh | N09000006 | UKN0G | Fermanagh and Omagh |
| Lisburn & Castlereagh City | N09000007 | UKN0E | Lisburn and Castlereagh |
| Mid & East Antrim | N09000008 | UKN0F | Mid and East Antrim |
| Mid Ulster | N09000009 | UKN0B | Mid Ulster |
| Newry Mourne & Down | N09000010 | UKN08 | Newry, Mourne and Down |

**NUTS Classification Notes:**

- Northern Ireland as a whole is NUTS1 region UKN
- NUTS2 level: UKN0 (Northern Ireland)
- NUTS3 level (NUTS 2021): 11 regions corresponding 1:1 to LGDs (UKN06-UKN0G)
- The older NUTS 2010/2013 classification used 5 aggregated regions (UKN01-UKN05), which are now obsolete

### Geographic Lookup Resources

**For cross-dataset comparison, you will need:**

1. **ONS Geography Portal:** https://geoportal.statistics.gov.uk/ - Lookup tables for LGD codes, ward codes, SOA codes, postcode to geography mappings
1. **NISRA Geography:** https://www.nisra.gov.uk/support/geography - Northern Ireland-specific geographic products and lookups
1. **Pointer Database:** Northern Ireland postcode to geography lookup (if available through NISRA)

______________________________________________________________________

## 8. Recommendations for Implementation

### For Postcode-Level or Small Area Analysis

Since PSNI does not publish postcode-level or small-area crime data publicly, you have these options:

1. **Use Policing District Level Data**

   - Align with other datasets using LGD codes
   - This is the most granular publicly available administrative geography
   - Suitable for district-level comparisons with NISRA statistics

1. **Use police.uk API for Approximate Locations**

   - Street-level anonymized coordinates available
   - Can aggregate to custom areas
   - **Limitations:** No outcomes for NI, limited time coverage, anonymized locations
   - Good for visualization but not precise geographic analysis

1. **Request Bespoke Data from PSNI**

   - Contact: statistics@psni.police.uk
   - May be able to provide small-area aggregations for research purposes
   - Likely subject to disclosure control and data sharing agreements

1. **Alternative:** Focus on District-Level Integration

   - Combine PSNI district-level crime with other NISRA district-level datasets
   - Use population-weighted aggregations where needed
   - This approach is most feasible for your bolster data sources architecture

### For Cross-Dataset Integration with NISRA Data

**Recommended Approach:**

- Use Policing District as the primary geographic key
- Map to LGD codes using lookup table above
- Integrate with NISRA datasets at LGD level (population, births, deaths, economic indicators)
- Consider NUTS3 aggregation for regional analysis

**File Format Preference:**

- CSV files are clean, well-structured, and ready for pandas
- Documentation (PDF data guide) is comprehensive
- No need for complex Excel parsing

______________________________________________________________________

## 9. Contact Information

### PSNI Statistics

- **Email:** statistics@psni.police.uk
- **Website:** https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics

### OpenDataNI

- **Email:** opendatani@nidirect.gov.uk
- **Website:** https://www.opendatani.gov.uk

### NISRA

- **Crime and Justice Queries:** statistics.research@justice-ni.x.gsi.gov.uk
- **Website:** https://www.nisra.gov.uk

______________________________________________________________________

## 10. Summary of Findings

### ✅ Available

| Feature | Status | Source |
|---------|--------|--------|
| **Crime statistics** | ✅ Available | OpenDataNI, data.gov.uk |
| **File formats** | ✅ CSV, PDF, (ODS unavailable) | OpenDataNI |
| **Update frequency** | ✅ Quarterly | OpenDataNI |
| **Policing District breakdown** | ✅ 11 districts + NI total | Monthly CSV |
| **Council Area mapping** | ✅ 1:1 with Policing Districts | Via LGD codes |
| **NUTS area mapping** | ✅ Via LGD to NUTS3 lookup | External lookup |
| **Time series** | ✅ 2001-present (20+ years) | Monthly CSV |
| **Crime categories** | ✅ 21 types (Home Office classifications) | Monthly CSV |
| **Outcome data** | ✅ Counts and rates by district | Monthly CSV |
| **Victim demographics** | ✅ Age and gender (NI level only) | Separate CSVs |
| **Street-level data** | ✅ Anonymized coordinates | police.uk API |

### ❌ Not Available

| Feature | Status | Alternative |
|---------|--------|-------------|
| **Postcode level** | ❌ Not publicly available | Request from PSNI or use districts |
| **Data Zones** | ❌ Not publicly available | Request from PSNI |
| **Super Output Areas** | ❌ Not publicly available | Request from PSNI |
| **Electoral Wards** | ❌ Not publicly available | Request from PSNI |
| **Outcome data (police.uk)** | ❌ PSNI does not provide | Use OpenDataNI outcomes |
| **Stop and Search** | ❌ Not available for NI | N/A |
| **Administrative geographies ODS** | ❌ NINIS discontinued | Use CSV with LGD codes |

### 🔑 Key Takeaway for Your Implementation

**The most granular publicly available geographic level is Policing District (which maps 1:1 to Local Government Districts).** This enables clean integration with other NISRA datasets that use LGD codes. Postcode or small-area data would require bespoke requests to PSNI.

**Recommended data source:** Police Recorded Crime Monthly Data CSV from OpenDataNI - clean, comprehensive, well-documented, and ready for pandas integration.

______________________________________________________________________

## 8. Data Gap: 2022-2025 Crime Statistics

### Problem Statement

**The OpenDataNI Police Recorded Crime dataset has not been updated since January 27, 2022**, with coverage ending December 2021. This creates a **4-year data gap** from January 2022 to present (December 2025).

### Evidence of Abandonment

**OpenDataNI Dataset Status:**

- **Last Modified:** January 27, 2022
- **Last Data Point:** December 2021
- **Expected Updates:** Quarterly (but none since 2022)
- **Status:** Appears abandoned

**Other PSNI Datasets ARE Being Updated** (proof PSNI can update OpenDataNI):

- **Road Traffic Collisions:** Updated through 2024 (last update: April 2025)
- **Stop and Search Statistics:** Updated through 2024/25 Q3 (last update: July 2025)
- **Anti-Social Behaviour:** Updated through March 2023 (last update: May 2023)

**Conclusion:** The crime statistics dataset specifically has been abandoned, not the entire OpenDataNI integration.

### Current Data Availability

**Where 2022-2025 Crime Data Likely Exists:**

1. **PSNI Official Website** - PDF Quarterly Bulletins

   - **URL:** https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-recorded-crime-statistics
   - **Format:** PDF reports with embedded Excel tables (likely)
   - **Status:** Protected by Cloudflare (blocks automated access)
   - **Access Method:** Manual download via web browser

1. **PSNI Statistics Branch** - Direct Contact

   - **Email:** statistics@psni.police.uk
   - **Request:** CSV/Excel files for 2022-2025 quarterly data
   - **Questions to Ask:**
     - Why was the OpenDataNI dataset discontinued?
     - Are 2022-2025 statistics available in machine-readable format?
     - Current publication schedule and formats?
     - Plans to resume quarterly CSV updates on OpenDataNI?

1. **Freedom of Information (FOI) Request**

   - **Portal:** https://www.psni.police.uk/about-us/freedom-information/make-foi-request
   - **Request:** Structured crime data (CSV/Excel) for 2022-2025
   - **Response Time:** 20 working days (statutory requirement)
   - **Cost:** Free for public interest requests

### Potential Solutions

#### Short-Term Solutions

1. **Manual Download from PSNI Website**

   - Navigate to PSNI statistics page in web browser
   - Download quarterly PDF bulletins for 2022-2025
   - Extract embedded Excel tables (if available)
   - Manually combine with historical data
   - **Pros:** Immediate access
   - **Cons:** Labor-intensive, not reproducible, format may vary

1. **Direct Email Request to PSNI Statistics**

   - Email statistics@psni.police.uk requesting machine-readable data
   - Request same format as OpenDataNI CSV
   - **Pros:** Official channel, may provide clean data
   - **Cons:** Requires manual intervention, unknown response time

1. **RSS Feed Monitoring** (Blocked by Cloudflare)

   - PSNI website has RSS feeds for new publications
   - **Status:** RSS feeds are also protected by Cloudflare (HTTP 403)
   - **Conclusion:** Not viable for automated monitoring

#### Long-Term Solutions

1. **Automated PDF Extraction Pipeline**

   - If PSNI continues PDF-only publication:
     - Download PDFs manually or via browser automation (Selenium/Playwright)
     - Extract tables using PDF parsing libraries (tabula-py, camelot-py)
     - Validate against known data structure
     - Merge with historical OpenDataNI data
   - **Pros:** Semi-automated after initial setup
   - **Cons:** Brittle (breaks if PDF format changes), requires maintenance

1. **Direct PSNI Data Partnership**

   - Formal request for API access or bulk data provision
   - Propose to host updated data on behalf of PSNI (with proper licensing)
   - **Pros:** Most sustainable long-term solution
   - **Cons:** Requires organizational commitment, legal agreements

1. **Community Data Collaboration**

   - Work with other NI data users to:
     - Share extracted 2022-2025 data
     - Collectively maintain updated dataset
     - Lobby PSNI/OpenDataNI for resumed updates
   - **Pros:** Distributed effort, community benefit
   - **Cons:** Coordination overhead, data quality consistency

### Implementation Recommendations

**Immediate Actions:**

1. ✅ **Add staleness warnings** to module (COMPLETED)

   - Warn users that data only goes through Dec 2021
   - Direct users to PSNI website and contact information
   - Implemented in `get_latest_crime_statistics()` function

1. ⏭️ **Contact PSNI Statistics Branch**

   - Email: statistics@psni.police.uk
   - Request: Machine-readable 2022-2025 crime data in same format as OpenDataNI
   - Ask about resuming OpenDataNI updates

1. ⏭️ **Manual Data Collection** (if needed urgently)

   - Navigate to PSNI statistics page manually
   - Download available quarterly reports for 2022-2025
   - Extract any Excel/CSV attachments
   - Document extraction methodology for reproducibility

**Future Enhancements:**

4. **Automated Staleness Detection**

   - Monitor OpenDataNI dataset for updates (check "Last Modified" date)
   - Alert if new data becomes available
   - Implement in future version with configurable notifications

1. **Fallback Data Sources**

   - If PSNI provides alternate download location, add as secondary source
   - Consider police.uk API for recent trends (Nov 2022-Oct 2025 available)
   - Note: police.uk lacks outcome data for NI

1. **PDF Extraction Pipeline** (only if PSNI confirms no CSV availability)

   - Investigate if quarterly PDFs contain extractable tables
   - Build extraction pipeline only if confirmed necessary
   - Document limitations and data quality concerns

### Contact Information

**PSNI Statistics Branch:**

- **Email:** statistics@psni.police.uk
- **Website:** https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics

**OpenDataNI Support:**

- **Email:** opendatani@nidirect.gov.uk
- **Website:** https://www.opendatani.gov.uk

**FOI Requests:**

- **Portal:** https://www.psni.police.uk/about-us/freedom-information
- **Response Time:** 20 working days

______________________________________________________________________

## Appendix: Sample Data Structure

### Sample Rows from Monthly CSV

```csv
Calendar_Year,Month,Policing_District,Crime_Type,Data_Measure,Count
2001,Apr,Northern Ireland,Violence with injury (including homicide & death/serious injury by unlawful driving),Police Recorded Crime,738
2001,Apr,Northern Ireland,Violence without injury,Police Recorded Crime,1380
2001,Apr,Belfast City,Violence with injury (including homicide & death/serious injury by unlawful driving),Police Recorded Crime,241
2021,Dec,Antrim & Newtownabbey,Total police recorded crime,Police Recorded Crime Outcomes (rate %),24.7
```

### File Statistics

- **Total rows:** 188,245
- **Time span:** April 2001 - December 2021
- **Districts:** 12 values (11 districts + NI total + header)
- **Crime types:** 21 categories
- **Data measures:** 3 types
- **File size:** 16.7 MB
