"""Strict-by-default handling of pinned fallback releases.

A ``get_latest_*`` function must return the data that was asked for or raise an
error naming what is missing. It must never quietly hand back a different
release. Where a module keeps a pinned earlier release, serving it is an
explicit opt-in (``allow_fallback=True``) and the result says so in four places:

- a :class:`FallbackWarning`,
- a ``logger.warning`` line,
- ``df.attrs["fallback"]`` (a dict describing what was requested and served),
- three visible columns: ``fallback_used``, ``requested_period`` and
  ``served_period``.

The columns exist only when a fallback was taken, so a normal result keeps its
usual schema.

Example:
    >>> import pandas as pd
    >>> df = mark_fallback(
    ...     pd.DataFrame({"x": [1]}),
    ...     requested="latest release",
    ...     served="2026 edition",
    ...     reason="index page unavailable",
    ... )
    >>> bool(df["fallback_used"].iloc[0]), df.attrs["fallback"]["served"]
    (True, '2026 edition')
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    import pandas as pd

logger = logging.getLogger(__name__)

FALLBACK_COLUMNS = ("fallback_used", "requested_period", "served_period")


class FallbackWarning(UserWarning):
    """Emitted when a pinned earlier release is served instead of the latest one."""


@dataclass(frozen=True)
class PinnedRelease:
    """An earlier release a module can serve when ``allow_fallback=True``.

    Attributes:
        url: Direct download URL of the pinned release.
        label: Human-readable name of the release, e.g. ``"Oct-Mar 2026 bulletin"``.
    """

    url: str
    label: str


@dataclass(frozen=True)
class ResolvedUrl:
    """A download URL and, if a pinned release was used, why.

    Attributes:
        url: The URL to download.
        fallback_reason: ``None`` when discovery succeeded; otherwise why the
            pinned release was used instead.
        served: Label of the pinned release when ``fallback_reason`` is set.
    """

    url: str
    fallback_reason: str | None = None
    served: str | None = None

    @property
    def used_fallback(self) -> bool:
        """Whether the pinned release was served instead of the discovered one."""
        return self.fallback_reason is not None


def fallback_not_found_message(
    what: str,
    *,
    searched: str,
    detail: str | None = None,
    pinned: PinnedRelease | None = None,
) -> str:
    """Build the standard error text for a failed discovery on the default path.

    Args:
        what: What could not be found, e.g. ``"the latest housing bulletin tables workbook"``.
        searched: Where and for what it was looked for: the page, the link text or
            pattern, the URL tried.
        detail: Why discovery failed, e.g. the underlying error.
        pinned: The pinned release that ``allow_fallback=True`` would serve, if any.

    Returns:
        A message ending with how to opt in to the pinned release.

    Example:
        >>> message = fallback_not_found_message(
        ...     "the latest bulletin",
        ...     searched="https://example.org/hub (link text 'Bulletin')",
        ...     pinned=PinnedRelease("https://example.org/old.xlsx", "2025 edition"),
        ... )
        >>> message.startswith("Could not find the latest bulletin. Searched: https://example.org/hub")
        True
        >>> "2025 edition" in message and "allow_fallback=True" in message
        True
    """
    parts = [f"Could not find {what}."]
    if detail:
        parts.append(f"Cause: {detail}.")
    parts.append(f"Searched: {searched}.")
    if pinned is not None:
        parts.append(
            f"A pinned earlier release exists ({pinned.label}: {pinned.url}); pass allow_fallback=True to use it. "
            "The result will then carry fallback_used, requested_period and served_period columns."
        )
    return " ".join(parts)


def resolve_url(
    discover: Callable[[], str],
    *,
    allow_fallback: bool,
    pinned: PinnedRelease,
    error_cls: type[Exception],
    what: str,
    searched: str,
) -> ResolvedUrl:
    """Discover a download URL, serving the pinned release only if allowed.

    Args:
        discover: Zero-argument callable returning the discovered URL. Any
            exception it raises counts as a failed discovery.
        allow_fallback: If ``False`` a failed discovery raises ``error_cls``; if
            ``True`` it serves ``pinned`` and records why.
        pinned: The earlier release to serve when falling back.
        error_cls: The provider's not-found exception.
        what: What is being looked for (see :func:`fallback_not_found_message`).
        searched: Where it was looked for (see :func:`fallback_not_found_message`).

    Returns:
        The discovered URL, or the pinned one with ``fallback_reason`` set.

    Raises:
        Exception: ``error_cls`` when discovery fails and ``allow_fallback`` is ``False``.

    Example:
        >>> def broken():
        ...     raise OSError("connection refused")
        >>> pinned = PinnedRelease("https://example.org/old.csv", "2025 edition")
        >>> resolved = resolve_url(
        ...     broken, allow_fallback=True, pinned=pinned, error_cls=ValueError, what="the data", searched="the hub"
        ... )
        >>> resolved.url, resolved.served
        ('https://example.org/old.csv', '2025 edition')
    """
    try:
        return ResolvedUrl(discover())
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        if not allow_fallback:
            raise error_cls(fallback_not_found_message(what, searched=searched, detail=detail, pinned=pinned)) from exc
        return ResolvedUrl(pinned.url, fallback_reason=f"{what} not found ({detail})", served=pinned.label)


def mark_fallback(
    df: pd.DataFrame,
    *,
    requested: str,
    served: str,
    reason: str,
    served_url: str | None = None,
) -> pd.DataFrame:
    """Label a result that was built from a fallback release.

    Call only when a fallback was actually taken. Adds the ``fallback_used``,
    ``requested_period`` and ``served_period`` columns, records the details in
    ``df.attrs["fallback"]``, and emits a :class:`FallbackWarning` and a log
    warning.

    Args:
        df: The result built from the fallback release. Modified in place.
        requested: What the caller asked for, e.g. ``"latest published release"``.
        served: What was actually served, e.g. ``"Oct-Mar 2026 bulletin"``.
        reason: Why the fallback was taken.
        served_url: URL of the file that was served, if known.

    Returns:
        ``df``, with the marker columns added.
    """
    message = f"Serving fallback data: requested {requested}, served {served} ({reason})."
    logger.warning(message)
    warnings.warn(message, FallbackWarning, stacklevel=3)
    df["fallback_used"] = True
    df["requested_period"] = requested
    df["served_period"] = served
    df.attrs["fallback"] = {
        "requested": requested,
        "served": served,
        "reason": reason,
        "served_url": served_url,
    }
    return df
