"""Integrity tests for NISRA Annual Survey of Hours and Earnings (ASHE) Module.

These tests validate real data quality, structure, and consistency for the
ASHE earnings statistics module.

Test coverage includes:
- Data structure and types
- Data completeness and ranges
- Timeseries continuity
- Earnings value relationships
- Growth rate calculations
- Helper function behavior
- Geographic data validation
- Sector data validation
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import ashe


class TestASHETimeseriesIntegrity:
    """Integrity tests for ASHE timeseries data."""

    @pytest.fixture(scope="class")
    def latest_weekly(self):
        """Fixture to load latest weekly earnings data once for all tests."""
        return ashe.get_latest_ashe_timeseries(metric="weekly", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_hourly(self):
        """Fixture to load latest hourly earnings data once for all tests."""
        return ashe.get_latest_ashe_timeseries(metric="hourly", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_annual(self):
        """Fixture to load latest annual earnings data once for all tests."""
        return ashe.get_latest_ashe_timeseries(metric="annual", force_refresh=False)

    def test_weekly_data_structure(self, latest_weekly):
        """Test that weekly earnings data has correct structure."""
        assert isinstance(latest_weekly, pd.DataFrame)
        assert len(latest_weekly) > 0

        # Check required columns
        required_cols = ["year", "work_pattern", "median_weekly_earnings"]
        assert all(col in latest_weekly.columns for col in required_cols)

    def test_weekly_data_types(self, latest_weekly):
        """Test that weekly earnings columns have correct data types."""
        assert pd.api.types.is_integer_dtype(latest_weekly["year"])
        assert latest_weekly["work_pattern"].dtype == "object"
        assert pd.api.types.is_float_dtype(latest_weekly["median_weekly_earnings"])

    def test_work_pattern_values(self, latest_weekly):
        """Test that work pattern values are valid."""
        valid_patterns = {"Full-time", "Part-time", "All"}
        assert set(latest_weekly["work_pattern"].unique()) == valid_patterns

    def test_year_range(self, latest_weekly):
        """Test that year range is reasonable (1997-present)."""
        assert latest_weekly["year"].min() == 1997
        assert latest_weekly["year"].max() >= 2025

    def test_weekly_earnings_positive(self, latest_weekly):
        """Test that earnings values are positive."""
        assert (latest_weekly["median_weekly_earnings"] > 0).all()

    def test_no_missing_values(self, latest_weekly):
        """Test that there are no missing values in key columns."""
        assert not latest_weekly["year"].isna().any()
        assert not latest_weekly["work_pattern"].isna().any()
        assert not latest_weekly["median_weekly_earnings"].isna().any()

    def test_chronological_order(self, latest_weekly):
        """Test that data includes all years in sequence."""
        all_pattern = latest_weekly[latest_weekly["work_pattern"] == "All"]
        years = sorted(all_pattern["year"].unique())
        # Check for consecutive years
        for i in range(len(years) - 1):
            assert years[i + 1] == years[i] + 1

    def test_three_records_per_year(self, latest_weekly):
        """Test that each year has exactly 3 records (Full-time, Part-time, All)."""
        records_per_year = latest_weekly.groupby("year").size()
        assert (records_per_year == 3).all()

    def test_hourly_data_structure(self, latest_hourly):
        """Test that hourly earnings data has correct structure."""
        assert isinstance(latest_hourly, pd.DataFrame)
        required_cols = ["year", "work_pattern", "median_hourly_earnings"]
        assert all(col in latest_hourly.columns for col in required_cols)

    def test_annual_data_structure(self, latest_annual):
        """Test that annual earnings data has correct structure."""
        assert isinstance(latest_annual, pd.DataFrame)
        required_cols = ["year", "work_pattern", "median_annual_earnings"]
        assert all(col in latest_annual.columns for col in required_cols)

    def test_annual_data_starts_1999(self, latest_annual):
        """Test that annual earnings data starts from 1999."""
        assert latest_annual["year"].min() == 1999


class TestASHEGeographyIntegrity:
    """Integrity tests for ASHE geographic data."""

    @pytest.fixture(scope="class")
    def latest_workplace(self):
        """Fixture for workplace-based geographic earnings."""
        return ashe.get_latest_ashe_geography(basis="workplace", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_residence(self):
        """Fixture for residence-based geographic earnings."""
        return ashe.get_latest_ashe_geography(basis="residence", force_refresh=False)

    def test_workplace_data_structure(self, latest_workplace):
        """Test that workplace geography data has correct structure."""
        assert isinstance(latest_workplace, pd.DataFrame)
        required_cols = ["year", "lgd", "basis", "median_weekly_earnings"]
        assert all(col in latest_workplace.columns for col in required_cols)

    def test_workplace_has_11_lgds(self, latest_workplace):
        """Test that data includes all 11 LGDs."""
        assert len(latest_workplace) == 11

    def test_lgd_names_valid(self, latest_workplace):
        """Test that LGD names are valid."""
        expected_lgds = {
            "Antrim and Newtownabbey",
            "Ards and North Down",
            "Armagh City, Banbridge and Craigavon",
            "Belfast",
            "Causeway Coast and Glens",
            "Derry City and Strabane",
            "Fermanagh and Omagh",
            "Lisburn and Castlereagh",
            "Mid and East Antrim",
            "Mid Ulster",
            "Newry, Mourne and Down",
        }
        assert set(latest_workplace["lgd"].unique()) == expected_lgds

    def test_basis_value(self, latest_workplace):
        """Test that basis column has correct value."""
        assert (latest_workplace["basis"] == "workplace").all()

    def test_residence_data_structure(self, latest_residence):
        """Test that residence geography data has correct structure."""
        assert isinstance(latest_residence, pd.DataFrame)
        assert len(latest_residence) == 11

    def test_residence_basis_value(self, latest_residence):
        """Test that residence data has correct basis."""
        assert (latest_residence["basis"] == "residence").all()


class TestASHESectorIntegrity:
    """Integrity tests for ASHE sector data."""

    @pytest.fixture(scope="class")
    def latest_sector(self):
        """Fixture for sector earnings data."""
        return ashe.get_latest_ashe_sector(force_refresh=False)

    def test_sector_data_structure(self, latest_sector):
        """Test that sector data has correct structure."""
        assert isinstance(latest_sector, pd.DataFrame)
        required_cols = ["year", "location", "sector", "median_weekly_earnings"]
        assert all(col in latest_sector.columns for col in required_cols)

    def test_sector_data_starts_2005(self, latest_sector):
        """Test that sector data starts from 2005."""
        assert latest_sector["year"].min() == 2005

    def test_sector_values_valid(self, latest_sector):
        """Test that sector values are valid."""
        valid_sectors = {"Public", "Private"}
        assert set(latest_sector["sector"].unique()) == valid_sectors

    def test_location_values_valid(self, latest_sector):
        """Test that location values are valid."""
        valid_locations = {"Northern Ireland", "United Kingdom"}
        assert set(latest_sector["location"].unique()) == valid_locations

    def test_four_records_per_year(self, latest_sector):
        """Test that each year has 4 records (NI Public/Private, UK Public/Private)."""
        records_per_year = latest_sector.groupby("year").size()
        assert (records_per_year == 4).all()

    def test_sector_has_both_locations(self, latest_sector):
        """Test that sector data has entries for both NI and UK."""
        latest_year = latest_sector["year"].max()
        year_data = latest_sector[latest_sector["year"] == latest_year]
        assert len(year_data[year_data["location"] == "Northern Ireland"]) == 2
        assert len(year_data[year_data["location"] == "United Kingdom"]) == 2


class TestHelperFunctionsIntegrity:
    """Integrity tests for helper functions."""

    @pytest.fixture(scope="class")
    def latest_weekly(self):
        """Fixture for weekly earnings data."""
        return ashe.get_latest_ashe_timeseries(metric="weekly", force_refresh=False)

    def test_get_earnings_by_year(self, latest_weekly):
        """Test filtering by year."""
        df_2025 = ashe.get_earnings_by_year(latest_weekly, 2025)

        assert len(df_2025) == 3  # Should have 3 work patterns
        assert (df_2025["year"] == 2025).all()

    def test_calculate_growth_rates(self, latest_weekly):
        """Test growth rate calculation."""
        df_growth = ashe.calculate_growth_rates(latest_weekly)

        # Should have growth rate column
        assert "earnings_yoy_growth" in df_growth.columns

        # First record for each work pattern should have NaN (no prior year)
        for pattern in ["Full-time", "Part-time", "All"]:
            first_record = df_growth[df_growth["work_pattern"] == pattern].iloc[0]
            assert pd.isna(first_record["earnings_yoy_growth"])

        # Later records should have values
        all_pattern = df_growth[df_growth["work_pattern"] == "All"]
        assert not all_pattern["earnings_yoy_growth"].iloc[1:].isna().all()

    def test_growth_rates_multiple_patterns(self, latest_weekly):
        """Test that growth rates are calculated separately for each work pattern."""
        df_growth = ashe.calculate_growth_rates(latest_weekly)

        # Each work pattern should have its own growth trajectory
        for pattern in ["Full-time", "Part-time", "All"]:
            pattern_data = df_growth[df_growth["work_pattern"] == pattern]
            growth_values = pattern_data["earnings_yoy_growth"].dropna()
            # Should have variation in growth rates
            assert growth_values.std() > 0.5


class TestASHEDataQuality:
    """Test data quality checks."""

    @pytest.fixture(scope="class")
    def latest_weekly(self):
        """Fixture for weekly earnings data."""
        return ashe.get_latest_ashe_timeseries(metric="weekly", force_refresh=False)

    def test_recent_data_available(self, latest_weekly):
        """Test that most recent year is recent."""
        latest_year = latest_weekly["year"].max()
        assert latest_year >= 2025


class TestASHEGenderPayGap:
    """Integrity tests for ASHE gender pay gap timeseries (Figure 14)."""

    @pytest.fixture(scope="class")
    def gpg(self):
        return ashe.get_gender_pay_gap()

    def test_required_columns(self, gpg):
        assert set(gpg.columns) == {"year", "location", "gender_pay_gap_pct"}

    def test_locations(self, gpg):
        assert set(gpg["location"].unique()) == {"Northern Ireland", "United Kingdom"}

    def test_two_records_per_year(self, gpg):
        counts = gpg.groupby("year").size()
        assert (counts == 2).all()

    def test_starts_2005(self, gpg):
        assert gpg["year"].min() == 2005

    def test_recent_year_present(self, gpg):
        assert gpg["year"].max() >= 2025

    def test_gap_plausible_range(self, gpg):
        """GPG should be between 0% and 40% — no negative values expected at population level."""
        assert (gpg["gender_pay_gap_pct"] >= 0).all()
        assert (gpg["gender_pay_gap_pct"] < 40).all()

    def test_ni_gap_below_uk(self, gpg):
        """NI GPG has historically been below the UK average across all years."""
        for year in gpg["year"].unique():
            yr = gpg[gpg["year"] == year]
            ni = yr[yr["location"] == "Northern Ireland"]["gender_pay_gap_pct"].values[0]
            uk = yr[yr["location"] == "United Kingdom"]["gender_pay_gap_pct"].values[0]
            assert ni < uk, f"NI GPG ({ni}%) >= UK GPG ({uk}%) in {year}"

    def test_gap_narrowing_trend(self, gpg):
        """Both NI and UK GPG should be lower in 2025 than in 2005."""
        for loc in ("Northern Ireland", "United Kingdom"):
            loc_df = gpg[gpg["location"] == loc].sort_values("year")
            gap_2005 = loc_df[loc_df["year"] == 2005]["gender_pay_gap_pct"].values[0]
            gap_latest = loc_df.iloc[-1]["gender_pay_gap_pct"]
            assert gap_latest < gap_2005, f"{loc}: gap has not narrowed since 2005"


class TestASHEHourlyEarningsBySectorGender:
    """Integrity tests for ASHE hourly earnings by sector and gender (Figure 15)."""

    @pytest.fixture(scope="class")
    def df(self):
        return ashe.get_hourly_earnings_by_sector_gender()

    def test_required_columns(self, df):
        assert set(df.columns) == {"year", "sector", "sex", "median_hourly_earnings"}

    def test_sectors(self, df):
        assert set(df["sector"].unique()) == {"Public", "Private"}

    def test_sexes(self, df):
        assert set(df["sex"].unique()) == {"Male", "Female"}

    def test_four_records_per_year(self, df):
        counts = df.groupby("year").size()
        assert (counts == 4).all()

    def test_starts_2005(self, df):
        assert df["year"].min() == 2005

    def test_earnings_positive(self, df):
        assert (df["median_hourly_earnings"] > 0).all()

    def test_public_sector_pays_more_than_private(self, df):
        """Public sector median hourly earnings should exceed private in NI for all years."""
        for year in df["year"].unique():
            yr = df[df["year"] == year]
            for sex in ("Male", "Female"):
                pub = yr[(yr["sector"] == "Public") & (yr["sex"] == sex)]["median_hourly_earnings"].values[0]
                priv = yr[(yr["sector"] == "Private") & (yr["sex"] == sex)]["median_hourly_earnings"].values[0]
                assert pub > priv, f"{sex} public (£{pub}) <= private (£{priv}) in {year}"

    def test_males_earn_more_than_females_in_each_sector(self, df):
        """Male median hourly earnings should exceed female in each sector for most years.

        In 2020, NI public sector females earned slightly more than males (£15.65 vs £15.31),
        likely reflecting COVID-era public sector composition effects. We check that the
        male premium holds in >=80% of year-sector combinations rather than requiring it
        for every single year.
        """
        exceptions = []
        for year in df["year"].unique():
            yr = df[df["year"] == year]
            for sector in ("Public", "Private"):
                male = yr[(yr["sector"] == sector) & (yr["sex"] == "Male")]["median_hourly_earnings"].values[0]
                female = yr[(yr["sector"] == sector) & (yr["sex"] == "Female")]["median_hourly_earnings"].values[0]
                if male <= female:
                    exceptions.append((year, sector, male, female))

        total = len(df["year"].unique()) * 2  # 2 sectors per year
        exception_rate = len(exceptions) / total
        assert exception_rate < 0.20, (
            f"Male earnings exceeded female in too few cases. Exceptions: {exceptions}"
        )


class TestASHEHourlyEarningsByAgeGender:
    """Integrity tests for ASHE hourly earnings by age and gender (Figure 16)."""

    @pytest.fixture(scope="class")
    def df(self):
        return ashe.get_hourly_earnings_by_age_gender()

    def test_required_columns(self, df):
        assert set(df.columns) == {"age_group", "sex", "median_hourly_earnings"}

    def test_age_groups(self, df):
        expected = {"18-21", "22-29", "30-39", "40-49", "50-59", "60+"}
        assert set(df["age_group"].unique()) == expected

    def test_sexes(self, df):
        assert set(df["sex"].unique()) == {"Male", "Female"}

    def test_two_records_per_age_group(self, df):
        counts = df.groupby("age_group").size()
        assert (counts == 2).all()

    def test_earnings_positive(self, df):
        assert (df["median_hourly_earnings"] > 0).all()

    def test_peak_earnings_in_middle_age(self, df):
        """Earnings should peak in 40-49 or 50-59 band (career seniority effect)."""
        for sex in ("Male", "Female"):
            sex_df = df[df["sex"] == sex]
            peak_age = sex_df.loc[sex_df["median_hourly_earnings"].idxmax(), "age_group"]
            assert peak_age in {"40-49", "50-59"}, f"{sex} peak earnings in unexpected band: {peak_age}"

    def test_youngest_earns_least(self, df):
        """18-21 band should have the lowest earnings for both sexes."""
        for sex in ("Male", "Female"):
            sex_df = df[df["sex"] == sex]
            min_age = sex_df.loc[sex_df["median_hourly_earnings"].idxmin(), "age_group"]
            assert min_age == "18-21", f"{sex} minimum earnings not in 18-21 band: {min_age}"


class TestASHEHourlyEarningsByOccupationGender:
    """Integrity tests for ASHE hourly earnings by occupation and gender (Figure 17)."""

    @pytest.fixture(scope="class")
    def df(self):
        return ashe.get_hourly_earnings_by_occupation_gender()

    def test_required_columns(self, df):
        assert set(df.columns) == {"occupation", "sex", "median_hourly_earnings"}

    def test_nine_occupation_groups(self, df):
        assert df["occupation"].nunique() == 9

    def test_sexes(self, df):
        assert set(df["sex"].unique()) == {"Male", "Female"}

    def test_earnings_positive(self, df):
        assert (df["median_hourly_earnings"] > 0).all()

    def test_managers_highest_paid(self, df):
        """Managers/directors should be the highest-paid occupation for both sexes."""
        for sex in ("Male", "Female"):
            sex_df = df[df["sex"] == sex]
            top_occ = sex_df.loc[sex_df["median_hourly_earnings"].idxmax(), "occupation"]
            assert "Managers" in top_occ, f"{sex} highest-paid occupation unexpected: {top_occ}"

    def test_gap_positive_in_all_occupations(self, df):
        """Male earnings should exceed female in all NI occupation groups (per NISRA)."""
        wide = df.pivot(index="occupation", columns="sex", values="median_hourly_earnings")
        gap = wide["Male"] - wide["Female"]
        assert (gap > 0).all(), f"Female earns more than male in: {gap[gap <= 0].index.tolist()}"


class TestASHEHourlyEarningsByPatternGender:
    """Integrity tests for ASHE hourly earnings by working pattern and gender (Figure 18)."""

    @pytest.fixture(scope="class")
    def df(self):
        return ashe.get_hourly_earnings_by_pattern_gender()

    def test_required_columns(self, df):
        assert set(df.columns) == {"work_pattern", "sex", "median_hourly_earnings"}

    def test_work_patterns(self, df):
        assert set(df["work_pattern"].unique()) == {"Full-time", "Part-time", "All Employees"}

    def test_sexes(self, df):
        assert set(df["sex"].unique()) == {"Male", "Female"}

    def test_earnings_positive(self, df):
        assert (df["median_hourly_earnings"] > 0).all()

    def test_fulltime_earns_more_than_parttime(self, df):
        """Full-time hourly earnings should exceed part-time for both sexes."""
        for sex in ("Male", "Female"):
            sex_df = df[df["sex"] == sex].set_index("work_pattern")
            assert sex_df.loc["Full-time", "median_hourly_earnings"] > sex_df.loc["Part-time", "median_hourly_earnings"]

    def test_parttime_females_earn_more_than_parttime_males(self, df):
        """NI data shows part-time females earn more per hour than part-time males."""
        pt = df[df["work_pattern"] == "Part-time"].set_index("sex")
        assert pt.loc["Female", "median_hourly_earnings"] > pt.loc["Male", "median_hourly_earnings"], (
            "Part-time female hourly earnings should exceed male in NI"
        )


class TestASHENIUKEarningsComparison:
    """Integrity tests for ASHE Figure 1: NI vs UK full-time weekly earnings timeseries."""

    @pytest.fixture(scope="class")
    def df(self):
        return ashe.get_ni_uk_earnings_comparison()

    def test_required_columns(self, df):
        assert set(df.columns) == {"year", "location", "median_weekly_earnings_fulltime"}

    def test_locations(self, df):
        assert set(df["location"].unique()) == {"NI", "UK"}

    def test_two_records_per_year(self, df):
        counts = df.groupby("year").size()
        assert (counts == 2).all()

    def test_starts_2005(self, df):
        assert df["year"].min() == 2005

    def test_earnings_positive(self, df):
        assert (df["median_weekly_earnings_fulltime"] > 0).all()

    def test_uk_earns_more_than_ni(self, df):
        """UK full-time median weekly earnings should exceed NI for all years."""
        for year in df["year"].unique():
            yr = df[df["year"] == year].set_index("location")
            uk = yr.loc["UK", "median_weekly_earnings_fulltime"]
            ni = yr.loc["NI", "median_weekly_earnings_fulltime"]
            assert uk > ni, f"UK (£{uk}) <= NI (£{ni}) in {year}"

    def test_earnings_growing_over_time(self, df):
        """NI earnings should be higher in the latest year than in 2005."""
        ni = df[df["location"] == "NI"].set_index("year")
        assert ni.loc[ni.index.max(), "median_weekly_earnings_fulltime"] > ni.loc[2005, "median_weekly_earnings_fulltime"]


class TestASHEUKRegionalPayRatio:
    """Integrity tests for ASHE Figure 13: high-to-low pay ratio by UK region."""

    @pytest.fixture(scope="class")
    def df(self):
        return ashe.get_uk_regional_pay_ratio()

    def test_required_columns(self, df):
        assert set(df.columns) == {"region", "ratio"}

    def test_northern_ireland_present(self, df):
        assert "Northern Ireland" in df["region"].values

    def test_london_present(self, df):
        assert "London" in df["region"].values

    def test_ratios_positive(self, df):
        assert (df["ratio"] > 0).all()

    def test_london_highest_ratio(self, df):
        """London should have the highest pay ratio."""
        assert df.loc[df["ratio"].idxmax(), "region"] == "London"

    def test_ni_below_uk_average(self, df):
        """NI pay ratio should be below the UK average."""
        ni = df[df["region"] == "Northern Ireland"]["ratio"].values[0]
        uk = df[df["region"] == "United Kingdom"]["ratio"].values[0]
        assert ni < uk, f"NI ratio ({ni}) should be below UK ({uk})"


class TestASHEHoursDistribution:
    """Integrity tests for ASHE Figure 9: weekly paid hours distribution."""

    @pytest.fixture(scope="class")
    def df(self):
        return ashe.get_hours_distribution()

    def test_required_columns(self, df):
        assert set(df.columns) == {"paid_hours_worked", "percentage"}

    def test_hours_range(self, df):
        assert df["paid_hours_worked"].min() >= 0
        assert df["paid_hours_worked"].max() >= 60

    def test_percentages_positive(self, df):
        assert (df["percentage"] >= 0).all()

    def test_percentages_sum_to_100(self, df):
        assert abs(df["percentage"].sum() - 100) < 2.0

    def test_37_hours_is_modal(self, df):
        """37 hours/week is the most common working week in NI."""
        modal_hours = df.loc[df["percentage"].idxmax(), "paid_hours_worked"]
        assert modal_hours == 37


class TestASHEWorkingPatternPayGap:
    """Integrity tests for ASHE Figure 19: working pattern pay gap timeseries."""

    @pytest.fixture(scope="class")
    def df(self):
        return ashe.get_working_pattern_pay_gap()

    def test_required_columns(self, df):
        assert set(df.columns) == {"year", "location", "working_pattern_pay_gap_pct"}

    def test_locations(self, df):
        assert set(df["location"].unique()) == {"NI", "UK"}

    def test_two_records_per_year(self, df):
        counts = df.groupby("year").size()
        assert (counts == 2).all()

    def test_starts_2005(self, df):
        assert df["year"].min() == 2005

    def test_gap_positive(self, df):
        """Full-time workers always earn more per hour than part-time — gap should be positive."""
        assert (df["working_pattern_pay_gap_pct"] > 0).all()

    def test_ni_gap_below_uk(self, df):
        """NI working pattern pay gap should be below UK in most years."""
        pivot = df.pivot(index="year", columns="location", values="working_pattern_pay_gap_pct")
        ni_below = (pivot["NI"] < pivot["UK"]).sum()
        total = len(pivot)
        assert ni_below / total >= 0.75, f"NI gap only below UK in {ni_below}/{total} years"


class TestASHEMeanHoursByPatternGender:
    """Integrity tests for ASHE Figure 20: mean weekly hours by pattern and gender."""

    @pytest.fixture(scope="class")
    def df(self):
        return ashe.get_mean_hours_by_pattern_gender()

    def test_required_columns(self, df):
        assert set(df.columns) == {"work_pattern", "male_mean_hours", "female_mean_hours", "all_mean_hours"}

    def test_work_patterns(self, df):
        assert set(df["work_pattern"].unique()) == {"Part-time", "Full-time", "All Employees"}

    def test_hours_positive(self, df):
        for col in ("male_mean_hours", "female_mean_hours", "all_mean_hours"):
            assert (df[col] > 0).all()

    def test_fulltime_longer_than_parttime(self, df):
        """Full-time mean hours should exceed part-time for all columns."""
        ft = df[df["work_pattern"] == "Full-time"].iloc[0]
        pt = df[df["work_pattern"] == "Part-time"].iloc[0]
        for col in ("male_mean_hours", "female_mean_hours", "all_mean_hours"):
            assert ft[col] > pt[col], f"Full-time {col} ({ft[col]}) <= part-time ({pt[col]})"

    def test_males_work_longer_fulltime(self, df):
        """Male full-time mean hours exceed female full-time mean hours."""
        ft = df[df["work_pattern"] == "Full-time"].iloc[0]
        assert ft["male_mean_hours"] > ft["female_mean_hours"]

    def test_females_work_longer_parttime(self, df):
        """Female part-time mean hours exceed male part-time mean hours in NI."""
        pt = df[df["work_pattern"] == "Part-time"].iloc[0]
        assert pt["female_mean_hours"] > pt["male_mean_hours"]
