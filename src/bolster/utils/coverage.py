"""Match publication titles against the implemented data-source catalogue.

``bolster nisra feed --check-coverage`` needs to say whether a newly published release is already
served by a module. The catalogue it matches against is built from two sources that are always
current: the Click command tree (command names and their one-line help) and the files under
``bolster/data_sources`` (module path, the leading docstring lines and the public ``get_*`` function
names, read as text so that no module is imported or parsed).

A title and a catalogue entry are both reduced to *distinctive tokens*: lower-cased words with
years, months, quarter markers and generic publication words removed, and a crude stem so that
``registrations``, ``registered`` and ``register`` agree. Each token is weighted by how rare it is
across the catalogue (``log(1 + N / df)``), so a word that appears in many entries, such as
``death``, counts for little on its own. The score of an entry is the share of the title's total
weight that the entry contains, so a title is only well covered when *most of what makes it
distinctive* is present in one entry.

Entries are ranked by ``score + NAME_BONUS * name_overlap``, where ``name_overlap`` is the share of
the entry's own name tokens (``labour_market`` -> ``labour``, ``market``) found in the title. That
makes the module named after the topic beat a module that merely mentions it.

Labels:

* ``covered``: score at least :data:`COVERED_MIN`, and either at least :data:`COVERED_MIN_SHARED`
  shared tokens or an entry whose whole name appears in the title (``Monthly Marriages`` ->
  ``nisra/marriages``).
* ``possible overlap``: score at least :data:`OVERLAP_MIN`, and either at least
  :data:`OVERLAP_MIN_SHARED` shared tokens or part of the entry's name in the title. A human should
  look at the named entry.
* ``not covered``: anything weaker.

The thresholds were tuned against hand-labelled publication titles (see ``tests/test_coverage.py``);
raise them to make the check stricter, lower them to make it more forgiving.

Example:
    >>> entry = CatalogueEntry("module", "psni/stop_and_search", "Stop and search statistics",
    ...                        tokenise("stop and search statistics psni"), tokenise("stop and search"))
    >>> match_title("Stop and Search statistics for Northern Ireland, period ending 30 September 2026",
    ...             Catalogue.from_entries([entry])).label
    'covered'
"""

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import click

COVERED = "covered"
POSSIBLE_OVERLAP = "possible overlap"
NOT_COVERED = "not covered"

COVERED_MIN = 0.85
COVERED_MIN_SHARED = 2
OVERLAP_MIN = 0.4
OVERLAP_MIN_SHARED = 2
NAME_BONUS = 0.3

STEM_LENGTH = 6
"""Tokens are truncated to this many characters after plural/-ing/-ed/-e stripping."""

DOCSTRING_LINES = 12
"""Leading docstring lines that contribute tokens to a module entry."""

FUNCTION_NAMES = 40
"""Most public ``get_*`` function names that contribute tokens to a module entry."""

_GENERIC_WORDS = frozenset(
    [
        "the",
        "of",
        "in",
        "for",
        "and",
        "to",
        "a",
        "an",
        "on",
        "at",
        "by",
        "with",
        "from",
        "or",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "northern",
        "ireland",
        "ni",
        "uk",
        "nisra",
        "gov",
        "government",
        "department",
        "official",
        "statistics",
        "statistical",
        "stats",
        "bulletin",
        "report",
        "reports",
        "results",
        "result",
        "data",
        "dataset",
        "datasets",
        "update",
        "updates",
        "tables",
        "table",
        "summary",
        "key",
        "facts",
        "findings",
        "annual",
        "quarterly",
        "monthly",
        "weekly",
        "yearly",
        "year",
        "years",
        "period",
        "ending",
        "end",
        "survey",
        "surveys",
        "series",
        "figures",
        "edition",
        "release",
        "published",
        "publication",
        "publications",
        "provisional",
        "experimental",
        "overview",
        "headline",
        "dashboard",
        "analysis",
        "research",
        "annex",
        "supplementary",
        "technical",
        "notes",
        "guidance",
        "tool",
        "bolster",
        "module",
        "source",
        "new",
        "get",
        "validate",
        "parse",
        "download",
        "fetch",
        "latest",
        "load",
        "read",
        "provides",
        "access",
        "function",
        "dataframe",
    ]
)
_MONTHS = frozenset(
    [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
    ]
)
_QUARTER = re.compile(r"^(q[1-4]|qtr\d?|quarter|quarters|week|weeks)$")
_WORD = re.compile(r"[a-z0-9]+")
_LEADING_DOCSTRING = re.compile(r"""\A\s*(?:#[^\n]*\n\s*)*[rRuU]?(\"\"\"|''')(.*?)\1""", re.DOTALL)
_GETTER = re.compile(r"^def (get_[a-z0-9_]+)\(", re.MULTILINE)


@dataclass(frozen=True)
class CatalogueEntry:
    """One implemented thing a title can be matched against."""

    kind: str
    """``"module"`` (a file under ``data_sources``) or ``"command"`` (a Click command)."""
    name: str
    """Module path such as ``psni/stop_and_search``, or command invocation such as ``nisra deaths``."""
    summary: str
    tokens: frozenset[str]
    name_tokens: frozenset[str] = frozenset()
    """Tokens of the name alone (``nisra/labour_market`` -> ``labour``, ``market``)."""


@dataclass(frozen=True)
class Match:
    """Result of matching one title."""

    label: str
    score: float
    entry: CatalogueEntry | None
    shared: tuple[str, ...]
    alternatives: tuple[tuple[CatalogueEntry, float], ...] = ()


@dataclass
class Catalogue:
    """Catalogue entries plus the token weights derived from them."""

    entries: list[CatalogueEntry]
    weights: dict[str, float] = field(default_factory=dict)
    default_weight: float = 1.0

    @classmethod
    def from_entries(cls, entries: list[CatalogueEntry]) -> "Catalogue":
        """Compute token weights (``log(1 + N / df)``) from ``entries``."""
        document_frequency: dict[str, int] = {}
        for entry in entries:
            for token in entry.tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        total = max(len(entries), 1)
        weights = {token: math.log(1 + total / df) for token, df in document_frequency.items()}
        return cls(entries=entries, weights=weights, default_weight=math.log(1 + total))

    def weight(self, token: str) -> float:
        """Weight of ``token``; a token no entry contains is maximally distinctive."""
        return self.weights.get(token, self.default_weight)


def _stem(word: str) -> str:
    """Strip plural, ``-ing``, ``-ed`` and trailing ``-e``, then truncate (``registrations`` -> ``regist``)."""
    if len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word[:STEM_LENGTH]


def tokenise(text: str) -> frozenset[str]:
    """Distinctive stemmed tokens of ``text``: no generic words, years, months or quarter markers."""
    tokens = set()
    for word in _WORD.findall(text.lower()):
        if word.isdigit() or word in _GENERIC_WORDS or word in _MONTHS or _QUARTER.match(word) or len(word) < 2:
            continue
        tokens.add(_stem(word))
    return frozenset(tokens)


def _read_module(path: Path) -> tuple[list[str], list[str]]:
    """Leading docstring lines and public ``get_*`` names of ``path`` ('' / empty if unreadable)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], []
    found = _LEADING_DOCSTRING.match(text)
    doc_lines = found.group(2).strip().splitlines()[:DOCSTRING_LINES] if found else []
    return doc_lines, _GETTER.findall(text)[:FUNCTION_NAMES]


def module_entries(root: Path | None = None) -> list[CatalogueEntry]:
    """One entry per public module under ``bolster/data_sources`` (underscore-prefixed helpers are skipped)."""
    root = root or Path(__file__).resolve().parent.parent / "data_sources"
    entries = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        relative = path.relative_to(root).with_suffix("")
        if any(part.startswith("_") for part in relative.parts):
            continue
        doc_lines, getters = _read_module(path)
        path_text = relative.as_posix().replace("_", " ").replace("/", " ")
        # The provider directory (psni, justice, ...) is not part of what the module is *called*.
        own_name = " ".join(relative.parts[1:] if len(relative.parts) > 1 else relative.parts).replace("_", " ")
        summary = doc_lines[0].strip() if doc_lines else ""
        tokens = tokenise(" ".join([path_text, *doc_lines, *(getter.replace("_", " ") for getter in getters)]))
        entries.append(CatalogueEntry("module", relative.as_posix(), summary, tokens, tokenise(own_name)))
    return entries


def command_entries(group: click.Group, prefix: str = "") -> list[CatalogueEntry]:
    """One entry per command in the Click tree, from the invocation and its one-line help."""
    entries = []
    for name, command in sorted(group.commands.items()):
        invocation = f"{prefix} {name}".strip()
        summary = command.get_short_help_str(120)
        tokens = tokenise(invocation.replace("-", " ")) | tokenise(summary)
        # No name tokens: a command called ``apprenticeships`` must not make every apprenticeship series covered.
        entries.append(CatalogueEntry("command", invocation, summary, tokens))
        if isinstance(command, click.Group):
            entries.extend(command_entries(command, invocation))
    return entries


def build_catalogue(group: click.Group | None = None, root: Path | None = None) -> Catalogue:
    """Catalogue of implemented modules and, when ``group`` is given, the commands that expose them."""
    entries = module_entries(root)
    if group is not None:
        entries.extend(command_entries(group))
    return Catalogue.from_entries(entries)


def _name_overlap(title_tokens: frozenset[str], entry: CatalogueEntry) -> float:
    if not entry.name_tokens:
        return 0.0
    return len(entry.name_tokens & title_tokens) / len(entry.name_tokens)


def match_title(title: str, catalogue: Catalogue, alternatives: int = 2) -> Match:
    """Label ``title`` as covered, a possible overlap or not covered, naming the best entry.

    Args:
        title: Publication title, e.g. from the NISRA feed.
        catalogue: From :func:`build_catalogue`.
        alternatives: How many runner-up entries to return for a human to judge.

    Returns:
        A :class:`Match`. ``entry`` is the best-ranked entry (``None`` if nothing shares a token).
    """
    title_tokens = tokenise(title)
    total = sum(catalogue.weight(token) for token in title_tokens)
    scored = []
    for entry in catalogue.entries:
        shared = title_tokens & entry.tokens
        if not shared or not total:
            continue
        score = sum(catalogue.weight(token) for token in shared) / total
        overlap = _name_overlap(title_tokens, entry)
        # Modules rank above commands on equal rank: a module path is what a builder needs.
        scored.append(
            (score + NAME_BONUS * overlap, entry.kind == "module", score, overlap, entry, tuple(sorted(shared)))
        )
    if not scored:
        return Match(NOT_COVERED, 0.0, None, ())
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    _, _, score, overlap, entry, shared = scored[0]
    if score >= COVERED_MIN and (len(shared) >= COVERED_MIN_SHARED or overlap == 1.0):
        label = COVERED
    elif score >= OVERLAP_MIN and (len(shared) >= OVERLAP_MIN_SHARED or overlap > 0):
        label = POSSIBLE_OVERLAP
    else:
        label = NOT_COVERED
    runners = tuple((row[4], row[2]) for row in scored[1 : 1 + alternatives])
    return Match(label, round(score, 3), entry, shared, runners)
