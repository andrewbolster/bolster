#!/usr/bin/env python
"""Tests for stats/distributions module."""

from bolster.stats.distributions import _get_available_distributions, best_fit_distribution


class TestModuleImports:
    """Test module imports and basic functionality."""

    def test_functions_importable(self):
        """Test that the main functions are importable."""
        assert callable(best_fit_distribution)
        assert callable(_get_available_distributions)


class TestGetAvailableDistributions:
    """Test the _get_available_distributions helper function."""

    def test_get_available_distributions_basic(self):
        """Test that _get_available_distributions returns a list of distributions."""
        distributions = _get_available_distributions()

        assert isinstance(distributions, list)
        assert len(distributions) > 0

        # All returned items should have expected attributes
        for dist in distributions:
            assert hasattr(dist, "name")
            assert hasattr(dist, "fit")
            assert hasattr(dist, "pdf")

    def test_get_available_distributions_include_slow(self):
        """Test that include_slow parameter affects the result."""
        distributions_fast = _get_available_distributions(include_slow=False)
        distributions_slow = _get_available_distributions(include_slow=True)

        # With slow distributions should have same or more distributions
        assert len(distributions_slow) >= len(distributions_fast)

    def test_common_distributions_available(self):
        """Test that common distributions are available."""
        distributions = _get_available_distributions()
        distribution_names = [d.name for d in distributions]

        # These should be available in most scipy versions
        common_distributions = ["norm", "uniform", "expon", "gamma", "beta"]

        for dist_name in common_distributions:
            assert dist_name in distribution_names, f"{dist_name} should be available"


class TestBestFitDistributionBasic:
    """Test basic functionality of best_fit_distribution."""

    def test_function_signature(self):
        """Test the function signature and parameters."""
        import inspect

        sig = inspect.signature(best_fit_distribution)
        params = list(sig.parameters.keys())

        expected_params = ["data", "bins", "ax", "include_slow", "discriminator"]
        for param in expected_params:
            assert param in params

        # Check default values
        assert sig.parameters["bins"].default == 200
        assert sig.parameters["ax"].default is None
        assert sig.parameters["include_slow"].default is False
        assert sig.parameters["discriminator"].default == "sse"

    def test_function_docstring(self):
        """Test that the function has a docstring."""
        assert best_fit_distribution.__doc__ is not None
        assert "Model data by finding best fit distribution" in best_fit_distribution.__doc__
