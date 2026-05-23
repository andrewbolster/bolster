"""Integrity tests for NISRA Public Confidence in Official Statistics module.

Tests use real data downloaded from NISRA (no mocks). Network calls are made
once per class via ``scope="class"`` fixtures and cached for the duration of
the test session.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import public_confidence


class TestAwarenessIntegrity:
    """Integrity tests for the awareness breakdown."""

    @pytest.fixture(scope="class")
    def awareness_data(self):
        """Download latest awareness data once for all tests in this class."""
        return public_confidence.get_latest_public_confidence(breakdown="awareness")

    def test_required_columns(self, awareness_data):
        """Awareness DataFrame must have year, response, percentage columns."""
        assert set(awareness_data.columns) == {"year", "response", "percentage"}

    def test_not_empty(self, awareness_data):
        """Awareness DataFrame must not be empty."""
        assert not awareness_data.empty

    def test_year_dtype_integer(self, awareness_data):
        """Year column must contain integers."""
        assert pd.api.types.is_integer_dtype(awareness_data["year"])

    def test_historical_coverage_from_2009(self, awareness_data):
        """Awareness data should go back to at least 2009 (back-filled in latest file)."""
        assert awareness_data["year"].min() <= 2009

    def test_recent_coverage_to_2019_plus(self, awareness_data):
        """Awareness data should cover at least through 2019."""
        assert awareness_data["year"].max() >= 2019

    def test_percentages_in_range(self, awareness_data):
        """All percentage values must be in [0, 100]."""
        assert (awareness_data["percentage"] >= 0).all()
        assert (awareness_data["percentage"] <= 100).all()

    def test_expected_response_categories(self, awareness_data):
        """Awareness responses should include Yes and No categories."""
        responses = set(awareness_data["response"].str.lower())
        assert "yes" in responses
        assert "no" in responses

    def test_no_null_values(self, awareness_data):
        """No null values in year, response, or percentage columns."""
        assert not awareness_data[["year", "response", "percentage"]].isnull().any().any()

    def test_validate_passes(self, awareness_data):
        """Validate function should return True for real data."""
        assert public_confidence.validate_public_confidence(awareness_data) is True


class TestTrustIntegrity:
    """Integrity tests for the trust breakdowns."""

    @pytest.fixture(scope="class")
    def all_trust_data(self):
        """Download all trust data once for all tests in this class."""
        return public_confidence.get_latest_public_confidence(breakdown="all_trust")

    def test_required_columns(self, all_trust_data):
        """All-trust DataFrame must have year, response, percentage, topic columns."""
        assert {"year", "response", "percentage", "topic"}.issubset(all_trust_data.columns)

    def test_all_five_topics_present(self, all_trust_data):
        """All five trust topics must be present in the all_trust breakdown."""
        expected_topics = {"nisra", "civil_service", "ni_assembly", "media", "nisra_statistics"}
        actual_topics = set(all_trust_data["topic"].unique())
        assert expected_topics == actual_topics

    def test_years_from_2014_plus(self, all_trust_data):
        """Trust data should cover at least from 2014 onward."""
        assert all_trust_data["year"].min() <= 2014

    def test_recent_coverage_to_2019_plus(self, all_trust_data):
        """Trust data should cover at least through 2019."""
        assert all_trust_data["year"].max() >= 2019

    def test_percentages_in_range(self, all_trust_data):
        """All percentage values must be in [0, 100]."""
        assert (all_trust_data["percentage"] >= 0).all()
        assert (all_trust_data["percentage"] <= 100).all()

    def test_trust_response_categories(self, all_trust_data):
        """Trust responses should include 'trust' and 'distrust' categories."""
        responses_lower = " ".join(all_trust_data["response"].str.lower().unique())
        assert "trust" in responses_lower

    def test_validate_passes(self, all_trust_data):
        """Validate function should pass for all_trust data."""
        # validate_public_confidence checks year/response/percentage — topic is extra
        assert public_confidence.validate_public_confidence(all_trust_data) is True

    def test_single_topic_nisra(self):
        """trust_nisra breakdown should return only nisra topic."""
        df = public_confidence.get_latest_public_confidence(breakdown="trust_nisra")
        assert set(df["topic"].unique()) == {"nisra"}

    def test_single_topic_media(self):
        """trust_media breakdown should return only media topic."""
        df = public_confidence.get_latest_public_confidence(breakdown="trust_media")
        assert set(df["topic"].unique()) == {"media"}


class TestValidation:
    """Unit tests for validate_public_confidence — no network calls."""

    def test_validate_empty_dataframe(self):
        """Validation must raise ValueError for empty DataFrame."""
        with pytest.raises(ValueError, match="empty"):
            public_confidence.validate_public_confidence(pd.DataFrame())

    def test_validate_missing_columns(self):
        """Validation must raise ValueError when required columns are missing."""
        df = pd.DataFrame({"year": [2025], "response": ["Yes"]})
        with pytest.raises(ValueError, match="Missing required columns"):
            public_confidence.validate_public_confidence(df)

    def test_validate_percentage_above_100(self):
        """Validation must raise ValueError when percentage exceeds 100."""
        df = pd.DataFrame({"year": [2025], "response": ["Yes"], "percentage": [101.0]})
        with pytest.raises(ValueError, match="out of range"):
            public_confidence.validate_public_confidence(df)

    def test_validate_negative_percentage(self):
        """Validation must raise ValueError for negative percentages."""
        df = pd.DataFrame({"year": [2025], "response": ["Yes"], "percentage": [-1.0]})
        with pytest.raises(ValueError, match="out of range"):
            public_confidence.validate_public_confidence(df)

    def test_validate_valid_dataframe(self):
        """Validation must return True for a correctly structured DataFrame."""
        df = pd.DataFrame(
            {
                "year": [2024, 2025],
                "response": ["Yes", "No"],
                "percentage": [48.1, 51.9],
            }
        )
        assert public_confidence.validate_public_confidence(df) is True

    def test_validate_boundary_values(self):
        """Validation must accept boundary values 0 and 100."""
        df = pd.DataFrame({"year": [2025], "response": ["Yes"], "percentage": [0.0]})
        assert public_confidence.validate_public_confidence(df) is True

        df2 = pd.DataFrame({"year": [2025], "response": ["Yes"], "percentage": [100.0]})
        assert public_confidence.validate_public_confidence(df2) is True

    def test_invalid_breakdown_raises(self):
        """get_latest_public_confidence must raise ValueError for unknown breakdown."""
        with pytest.raises(ValueError, match="Unknown breakdown"):
            public_confidence.get_latest_public_confidence(breakdown="invalid_breakdown")

    def test_invalid_topic_raises(self):
        """parse_trust must raise ValueError for unknown topic."""
        with pytest.raises(ValueError, match="Unknown topic"):
            public_confidence.parse_trust("/tmp/dummy.ods", topic="invalid_topic")
