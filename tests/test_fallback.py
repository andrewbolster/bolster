"""Offline tests for the shared strict-by-default fallback helper."""

import logging
import warnings

import pandas as pd
import pytest

from bolster.utils.fallback import (
    FALLBACK_COLUMNS,
    FallbackWarning,
    PinnedRelease,
    ResolvedUrl,
    fallback_not_found_message,
    mark_fallback,
    resolve_url,
)

PINNED = PinnedRelease("https://example.org/old.xlsx", "2025 edition")


class NotFound(Exception):
    """Stand-in for a provider's not-found error."""


def _fail(exc: Exception | None = None):
    def discover() -> str:
        raise exc or OSError("connection refused")

    return discover


class TestFallbackNotFoundMessage:
    def test_names_what_where_and_the_opt_in(self):
        message = fallback_not_found_message(
            "the latest bulletin", searched="https://example.org/hub (link text 'Bulletin')", pinned=PINNED
        )
        assert message.startswith("Could not find the latest bulletin.")
        assert "Searched: https://example.org/hub (link text 'Bulletin')." in message
        assert "2025 edition" in message
        assert "https://example.org/old.xlsx" in message
        assert "allow_fallback=True" in message

    def test_includes_the_cause_when_given(self):
        message = fallback_not_found_message("the data", searched="the hub", detail="OSError: boom", pinned=PINNED)
        assert "Cause: OSError: boom." in message

    def test_without_a_pinned_release_there_is_no_opt_in_hint(self):
        assert "allow_fallback" not in fallback_not_found_message("the data", searched="the hub")


class TestResolveUrl:
    def _resolve(self, discover, allow_fallback):
        return resolve_url(
            discover,
            allow_fallback=allow_fallback,
            pinned=PINNED,
            error_cls=NotFound,
            what="the data",
            searched="the hub page",
        )

    @pytest.mark.parametrize("allow_fallback", [False, True])
    def test_discovery_success_is_never_marked(self, allow_fallback):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            resolved = self._resolve(lambda: "https://example.org/new.xlsx", allow_fallback)
        assert resolved == ResolvedUrl("https://example.org/new.xlsx")
        assert resolved.used_fallback is False
        assert resolved.fallback_reason is None

    def test_default_raises_the_provider_error_with_the_standard_message(self):
        with pytest.raises(NotFound) as excinfo:
            self._resolve(_fail(), allow_fallback=False)
        message = str(excinfo.value)
        assert "Could not find the data." in message
        assert "OSError: connection refused" in message
        assert "Searched: the hub page." in message
        assert "allow_fallback=True" in message
        assert isinstance(excinfo.value.__cause__, OSError)

    def test_opt_in_serves_the_pinned_release_and_says_why(self):
        resolved = self._resolve(_fail(), allow_fallback=True)
        assert resolved.url == PINNED.url
        assert resolved.served == PINNED.label
        assert resolved.used_fallback is True
        assert "the data not found" in (resolved.fallback_reason or "")
        assert "connection refused" in (resolved.fallback_reason or "")

    def test_the_providers_own_error_is_also_a_failed_discovery(self):
        with pytest.raises(NotFound) as excinfo:
            self._resolve(_fail(NotFound("no link")), allow_fallback=False)
        assert "NotFound: no link" in str(excinfo.value)


class TestMarkFallback:
    def _mark(self, df, **overrides):
        kwargs = {
            "requested": "latest release",
            "served": "2025 edition",
            "reason": "index page unavailable",
            "served_url": "https://example.org/old.xlsx",
        }
        kwargs.update(overrides)
        return mark_fallback(df, **kwargs)

    def test_adds_visible_columns_and_attrs(self):
        with pytest.warns(FallbackWarning):
            df = self._mark(pd.DataFrame({"x": [1, 2]}))
        assert list(df.columns) == ["x", *FALLBACK_COLUMNS]
        assert df["fallback_used"].tolist() == [True, True]
        assert set(df["requested_period"]) == {"latest release"}
        assert set(df["served_period"]) == {"2025 edition"}
        assert df.attrs["fallback"] == {
            "requested": "latest release",
            "served": "2025 edition",
            "reason": "index page unavailable",
            "served_url": "https://example.org/old.xlsx",
        }

    def test_warning_and_log_name_both_releases_and_the_reason(self, caplog):
        with caplog.at_level(logging.WARNING, logger="bolster.utils.fallback"), pytest.warns(FallbackWarning) as record:
            self._mark(pd.DataFrame({"x": [1]}))
        for text in ("latest release", "2025 edition", "index page unavailable"):
            assert text in str(record[0].message)
            assert text in caplog.text

    def test_fallback_warning_is_a_user_warning(self):
        assert issubclass(FallbackWarning, UserWarning)

    def test_works_on_an_empty_frame(self):
        with pytest.warns(FallbackWarning):
            df = self._mark(pd.DataFrame())
        assert list(df.columns) == list(FALLBACK_COLUMNS)
        assert df.empty

    def test_served_url_is_optional(self):
        with pytest.warns(FallbackWarning):
            df = mark_fallback(pd.DataFrame({"x": [1]}), requested="a", served="b", reason="c")
        assert df.attrs["fallback"]["served_url"] is None
