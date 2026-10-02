"""Generic fuzzy string matching, stdlib only.

Ranks a list of candidate strings by similarity to a query. A candidate that contains
``query`` as a case-insensitive substring always scores ``1.0`` (exact containment is
the strongest signal for a short search term against a longer compound name, e.g.
``"cambria"`` against ``"Shankill, Cambria Street"``); everything else falls back to
:class:`difflib.SequenceMatcher`'s similarity ratio for typo tolerance. No extra
dependency (no ``rapidfuzz``/``thefuzz``) — this is deliberately simple, not a general
NLP similarity measure. The default cutoff (0.6) matches :func:`difflib.get_close_matches`'s
own established default for this same ratio.

Example:
    >>> fuzzy_match("cambria", ["Shankill, Cambria Street", "Great Victoria Street"])
    [('Shankill, Cambria Street', 1.0)]
    >>> fuzzy_match("victoria steet", ["Shankill, Cambria Street", "Great Victoria Street"])
    [('Great Victoria Street', 0.8)]
"""

from difflib import SequenceMatcher


def fuzzy_match(query: str, candidates: list[str], n: int = 5, cutoff: float = 0.6) -> list[tuple[str, float]]:
    """Rank ``candidates`` by similarity to ``query``.

    Args:
        query: Search term.
        candidates: Strings to rank. Not deduplicated — pass unique candidates if that
            matters to the caller.
        n: Maximum number of results to return (default 5).
        cutoff: Minimum score to include, in ``[0, 1]`` (default 0.6, matching
            :func:`difflib.get_close_matches`'s own default for this ratio). Lower to
            allow weaker matches through; ``0`` returns every candidate ranked.

    Returns:
        Up to ``n`` ``(candidate, score)`` pairs, best match first. Empty if nothing
        scores at or above ``cutoff``.

    Example:
        >>> fuzzy_match("cambria", ["Shankill, Cambria Street", "City Hall"])
        [('Shankill, Cambria Street', 1.0)]
        >>> fuzzy_match("completely unrelated", ["Shankill, Cambria Street"])
        []
    """
    query_lower = query.lower()
    scored = []
    for candidate in candidates:
        candidate_lower = candidate.lower()
        score = 1.0 if query_lower in candidate_lower else SequenceMatcher(None, query_lower, candidate_lower).ratio()
        if score >= cutoff:
            scored.append((candidate, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:n]
