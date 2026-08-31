# Bolster

![PyPI](https://img.shields.io/pypi/v/bolster?style=for-the-badge)
![Python](https://img.shields.io/pypi/pyversions/bolster?style=for-the-badge)
![License](https://img.shields.io/pypi/l/bolster?style=for-the-badge)
![GitHub Actions](https://img.shields.io/github/actions/workflow/status/andrewbolster/bolster/pytest.yml?branch=main&style=for-the-badge)
![Code Coverage](https://img.shields.io/codecov/c/github/andrewbolster/bolster?style=for-the-badge)
![Documentation](https://img.shields.io/readthedocs/bolster?style=for-the-badge)
[![Ruff](https://img.shields.io/badge/Code%20Quality-Ruff-red?logo=ruff&logoColor=white&style=for-the-badge)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/badge/Package%20Manager-uv-green?logo=python&logoColor=white&style=for-the-badge)](https://github.com/astral-sh/uv)

A Python library for accessing Northern Ireland and UK government open data.
Covers population, health, crime, economy, transport, housing, and more —
each source normalised into a clean pandas DataFrame with a matching CLI command.

**Full documentation**: [bolster.readthedocs.io](https://bolster.readthedocs.io)

______________________________________________________________________

## Installation

```bash
pip install bolster
```

Requires Python 3.11+.

______________________________________________________________________

## What can you do with it?

A few examples using real data:

**Who is claiming UC/JSA, and where?**

```python
from bolster.data_sources.nisra import claimant_count

df = claimant_count.get_latest_claimant_count("lgd")
# 33,930 claimants across NI as of May 2026
# Derry City & Strabane has the highest rate at 4.1%
print(
    df[df["date"] == df["date"].max()].sort_values("claimant_rate_total_pct", ascending=False)[
        ["geography", "claimants_total", "claimant_rate_total_pct"]
    ]
)
```

**How many people are on the hypertension register at each GP practice?**

```python
from bolster.data_sources.health_ni import disease_prevalence

# NI-wide: 304,952 patients on the hypertension register in 2024/25
summary = disease_prevalence.get_latest_disease_prevalence(level="ni")

# GP-practice level: ~360 practices across ~17 financial years
gp = disease_prevalence.get_latest_gp_prevalence()
print(gp[gp["disease"] == "Hypertension"].groupby("financial_year")["registered_patients"].sum())
```

**How is NI's economy tracking against pre-pandemic levels?**

```python
from bolster.data_sources.nisra import composite_index

df = composite_index.get_latest_nicei()
# NICEI at 105.9 in Q1 2026 (base 100 = 2016)
# Breakdown by sector: services, production, construction, agriculture
print(df.tail(4)[["year", "quarter", "nicei", "services", "production"]])
```

**What are A&E waiting times doing across HSC Trusts?**

```python
from bolster.data_sources.health_ni import emergency_care_waiting_times

df = emergency_care_waiting_times.get_latest_data()
# Monthly attendance and % seen within 4 hours by Trust and department type
latest = df[df["date"] == df["date"].max()]
print(latest.groupby("trust")["pct_within_4hrs"].mean().sort_values())
```

**What is the median full-time weekly wage in NI?**

```python
from bolster.data_sources.nisra import ashe

df = ashe.get_latest_ashe_timeseries("weekly")
# £713.10 median full-time weekly earnings in 2025
print(df[df["work_pattern"] == "Full-time"].tail(5)[["year", "median_weekly_earnings"]])
```

______________________________________________________________________

## Data sources

Sources are organised by publisher. Each module follows the same pattern:
`get_latest_*()` returns a tidy DataFrame; `bolster <command> --help` gives
CLI access.

### NISRA — NI Statistics and Research Agency

People and society:
[`population`](https://bolster.readthedocs.io/en/latest/data_sources.html#population),
[`births`](https://bolster.readthedocs.io/en/latest/data_sources.html#births),
[`deaths`](https://bolster.readthedocs.io/en/latest/data_sources.html#deaths),
[`marriages`](https://bolster.readthedocs.io/en/latest/data_sources.html#marriages),
[`stillbirths`](https://bolster.readthedocs.io/en/latest/data_sources.html#stillbirths),
[`migration`](https://bolster.readthedocs.io/en/latest/data_sources.html#migration),
[`population_projections`](https://bolster.readthedocs.io/en/latest/data_sources.html#population-projections),
[`baby_names`](https://bolster.readthedocs.io/en/latest/data_sources.html#baby-names),
[`registrar_general`](https://bolster.readthedocs.io/en/latest/data_sources.html#registrar-general-quarterly-tables),
[`deprivation`](https://bolster.readthedocs.io/en/latest/data_sources.html#deprivation-nimdm-2017),
[`wellbeing`](https://bolster.readthedocs.io/en/latest/data_sources.html#wellbeing),
[`public_confidence`](https://bolster.readthedocs.io/en/latest/data_sources.html#public-confidence-in-official-statistics),
[`drug_related_deaths`](https://bolster.readthedocs.io/en/latest/data_sources.html#drug-related-deaths)

Economy and labour:
[`labour_market`](https://bolster.readthedocs.io/en/latest/data_sources.html#labour-market),
[`claimant_count`](https://bolster.readthedocs.io/en/latest/data_sources.html#claimant-count),
[`ashe`](https://bolster.readthedocs.io/en/latest/data_sources.html#annual-survey-of-hours-and-earnings-ashe),
[`quarterly_employment_survey`](https://bolster.readthedocs.io/en/latest/data_sources.html#quarterly-employment-survey),
[`composite_index`](https://bolster.readthedocs.io/en/latest/data_sources.html#composite-economic-index-nicei),
[`index_of_production`](https://bolster.readthedocs.io/en/latest/data_sources.html#index-of-production-services),
[`index_of_services`](https://bolster.readthedocs.io/en/latest/data_sources.html#index-of-production-services),
[`construction_output`](https://bolster.readthedocs.io/en/latest/data_sources.html#construction-output),
[`business_register`](https://bolster.readthedocs.io/en/latest/data_sources.html#business-register-idbr),
[`planning_statistics`](https://bolster.readthedocs.io/en/latest/data_sources.html#planning-statistics),
[`housing_stock`](https://bolster.readthedocs.io/en/latest/data_sources.html#housing-stock),
[`tourism`](https://bolster.readthedocs.io/en/latest/data_sources.html#tourism-occupancy),
[`work_quality`](https://bolster.readthedocs.io/en/latest/data_sources.html#id1)

### Department of Health NI (`health_ni`)

[`disease_prevalence`](https://bolster.readthedocs.io/en/latest/data_sources.html#disease-prevalence) (NI / LGD / HSCT / GP-practice level),
[`cancer_waiting_times`](https://bolster.readthedocs.io/en/latest/data_sources.html#cancer-waiting-times),
[`diagnostic_waiting_times`](https://bolster.readthedocs.io/en/latest/data_sources.html#diagnostic-waiting-times),
[`elective_waiting_times`](https://bolster.readthedocs.io/en/latest/data_sources.html#elective-waiting-times),
[`emergency_care_waiting_times`](https://bolster.readthedocs.io/en/latest/data_sources.html#emergency-care-waiting-times),
[`child_protection`](https://bolster.readthedocs.io/en/latest/data_sources.html#child-protection)

### PSNI — Police Service of Northern Ireland

[`crime_statistics`](https://bolster.readthedocs.io/en/latest/data_sources.html#crime-statistics) (historical),
[`road_traffic_collisions`](https://bolster.readthedocs.io/en/latest/data_sources.html#road-traffic-collisions),
[`stop_and_search`](https://bolster.readthedocs.io/en/latest/data_sources.html#stop-and-search),
[`pace`](https://bolster.readthedocs.io/en/latest/data_sources.html#pace-statistics),
[`police_ombudsman`](https://bolster.readthedocs.io/en/latest/data_sources.html#police-ombudsman)

### Other sources

| Source | Module | What it covers |
|--------|--------|----------------|
| DVA | `dva` | Vehicle, driver, and theory test statistics (monthly) |
| NI Water | `ni_water` | Drinking water quality by supply zone and postcode |
| NI House Price Index | `ni_house_price_index` | Quarterly house price index and sales volumes |
| NI Assembly | `niassembly` | MLAs, oral/written questions, votes (2007–present) |
| EONI | `eoni` | Assembly election results (2016, 2022) |
| Translink | `translink` | Live departures and vehicle positions |
| ONS | `ons_cpi` | CPI / CPIH / RPI inflation indices |
| Bank of England | `boe_base_rate` | Official Bank Rate (1694–present) |
| Companies House | `companies_house` | UK company data |
| Gender Pay Gap | `gender_pay_gap` | UK GPG reporting (250+ employees, 2017–present) |
| DAERA | `daera_waste` | NI municipal waste statistics |
| Justice (NICTS) | `justice` | Mortgage possession actions |
| Met Office | `metoffice` | UK precipitation maps (requires API key) |

______________________________________________________________________

## CLI

Every data source has a matching CLI command:

```bash
bolster nisra deaths                        # latest weekly deaths
bolster nisra claimant-count --breakdown lgd
bolster nisra composite-index
bolster health-ni disease-prevalence --level gp
bolster psni stop-and-search
bolster translink departures "Europa Buscentre"
bolster water-quality BT1 5GS
bolster dva vehicle-tests
bolster --help                              # full command list
```

______________________________________________________________________

## Utilities

Bolster also includes general-purpose helpers used internally:

- **`poolmap()`** — ThreadPoolExecutor with progress bar and error handling
- **`backoff()`** — exponential backoff retry decorator
- **`memoize()`** — instance method cache with hit/miss tracking
- **`get_recursively()`** / **`flatten_dict()`** — nested dict navigation
- **`CachedDownloader`** — disk-cached HTTP download with TTL
- **`session`** — shared `requests.Session` with retry/jitter logic

```python
import bolster

results = bolster.poolmap(lambda x: x**2, range(1000), max_workers=4)


@bolster.backoff(Exception, tries=3, delay=1, backoff=2)
def unreliable(): ...
```

______________________________________________________________________

## Development

```bash
git clone https://github.com/andrewbolster/bolster.git
cd bolster
uv sync --all-extras --dev
uv run pre-commit install
uv run pytest tests/ -q --no-cov        # quick run
uv run pytest tests/ --cov=src/bolster  # with coverage
```

See [AGENTS.md](AGENTS.md) for the data source development workflow and
[CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

______________________________________________________________________

## License

[GNU General Public License v3](https://github.com/andrewbolster/bolster/blob/main/LICENSE)
