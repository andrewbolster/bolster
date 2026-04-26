#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["scipy", "numpy", "feedparser", "rich"]
# ///
"""NISRA feed drift detection via TF-IDF.

Fetches the NISRA discovery RSS feed, builds a TF-IDF corpus from existing
data source module docstrings, and classifies each feed entry as:

  covered   — similarity >= COVERED_THRESHOLD  (known dataset, new release)
  adjacent  — similarity >= ADJACENT_THRESHOLD (related, possibly covered)
  new       — similarity <  ADJACENT_THRESHOLD (potential new species)

Exits with code 2 if any 'new' entries are found so CI can act on them.
"""

import argparse
import ast
import json
import pathlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

import feedparser
import numpy as np

COVERED_THRESHOLD = 0.60
ADJACENT_THRESHOLD = 0.40

NISRA_FEED_URL = (
    "https://www.gov.uk/search/research-and-statistics.atom?"
    "content_store_document_type=all_research_and_statistics&"
    "organisations%5B%5D=northern-ireland-statistics-and-research-agency"
)

# Terms so common in NI government publications they add no discriminatory signal
_STOPWORDS = {
    "northern", "ireland", "ni", "statistics", "statistical", "quarterly",
    "monthly", "annual", "weekly", "report", "bulletin", "publication",
    "data", "register", "registered", "registrar", "quarter", "ending",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "2020", "2021", "2022", "2023", "2024", "2025", "2026",
    "in", "of", "the", "and", "for", "to", "by", "at", "or",
    "with", "from", "on", "an", "is", "as",
}

REPO_ROOT = pathlib.Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# TF-IDF (scipy + numpy, no sklearn)
# ---------------------------------------------------------------------------

def _tokenise(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return [t for t in text.split() if len(t) > 1 and t not in _STOPWORDS]


def _build_tfidf(documents: list[str]) -> tuple[np.ndarray, list[str]]:
    tokenised = [_tokenise(d) for d in documents]
    vocab = sorted({tok for tokens in tokenised for tok in tokens})
    vocab_index = {t: i for i, t in enumerate(vocab)}
    n_docs, n_terms = len(documents), len(vocab)

    tf = np.zeros((n_docs, n_terms), dtype=float)
    for di, tokens in enumerate(tokenised):
        counts = Counter(tokens)
        total = sum(counts.values()) or 1
        for tok, cnt in counts.items():
            if tok in vocab_index:
                tf[di, vocab_index[tok]] = cnt / total

    df = np.zeros(n_terms, dtype=float)
    for tokens in tokenised:
        for tok in set(tokens):
            if tok in vocab_index:
                df[vocab_index[tok]] += 1

    idf = np.log((1 + n_docs) / (1 + df)) + 1
    tfidf = tf * idf
    norms = np.linalg.norm(tfidf, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return tfidf / norms, vocab


def _query(text: str, corpus_tfidf: np.ndarray, vocab: list[str]) -> np.ndarray:
    vocab_index = {t: i for i, t in enumerate(vocab)}
    tokens = _tokenise(text)
    counts = Counter(tokens)
    total = sum(counts.values()) or 1
    q = np.zeros(len(vocab), dtype=float)
    for tok, cnt in counts.items():
        if tok in vocab_index:
            q[vocab_index[tok]] = cnt / total
    norm = np.linalg.norm(q)
    if norm == 0:
        return np.zeros(len(corpus_tfidf))
    return corpus_tfidf @ (q / norm)


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

@dataclass
class ModuleDoc:
    name: str
    path: str
    docstring: str
    text: str = field(init=False)

    def __post_init__(self):
        self.text = f"{self.name.replace('_', ' ')} {self.docstring}"


def extract_corpus(root: pathlib.Path) -> list[ModuleDoc]:
    docs = []
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            tree = ast.parse(path.read_text())
            docstring = ast.get_docstring(tree) or ""
            first_line = next((l.strip() for l in docstring.splitlines() if l.strip()), "")
            docs.append(ModuleDoc(
                name=path.stem,
                path=str(path.relative_to(REPO_ROOT)),
                docstring=first_line,
            ))
        except Exception:
            pass
    return docs


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------

def fetch_feed(limit: int = 20) -> list[dict]:
    parsed = feedparser.parse(NISRA_FEED_URL)
    entries = []
    for e in parsed.entries[:limit]:
        entries.append({
            "title": e.get("title", ""),
            "summary": e.get("summary", ""),
            "link": e.get("link", ""),
            "published": e.get("published", None),
        })
    return entries


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

@dataclass
class Classification:
    title: str
    link: str
    published: str | None
    status: str
    best_match: str
    best_match_path: str
    score: float


def classify_feed(
    entries: list[dict],
    corpus: list[ModuleDoc],
    covered_threshold: float = COVERED_THRESHOLD,
    adjacent_threshold: float = ADJACENT_THRESHOLD,
) -> list[Classification]:
    tfidf, vocab = _build_tfidf([m.text for m in corpus])
    results = []
    for entry in entries:
        sims = _query(f"{entry['title']} {entry['summary']}", tfidf, vocab)
        best_idx = int(np.argmax(sims))
        best_score = float(sims[best_idx])
        best = corpus[best_idx]
        if best_score >= covered_threshold:
            status = "covered"
        elif best_score >= adjacent_threshold:
            status = "adjacent"
        else:
            status = "new"
        results.append(Classification(
            title=entry["title"],
            link=entry["link"],
            published=entry["published"],
            status=status,
            best_match=best.name,
            best_match_path=best.path,
            score=best_score,
        ))
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_results(results: list[Classification], verbose: bool = False) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="NISRA Feed Drift Detection", show_lines=True)
    table.add_column("Status", width=10)
    table.add_column("Score", width=6)
    table.add_column("Title", width=55)
    table.add_column("Best match", width=30)

    colours = {"covered": "green", "adjacent": "yellow", "new": "red"}
    for r in results:
        if not verbose and r.status == "covered":
            continue
        c = colours[r.status]
        table.add_row(f"[{c}]{r.status}[/{c}]", f"{r.score:.3f}", r.title, r.best_match)

    console.print(table)


def write_github_summary(results: list[Classification]) -> None:
    import os
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    covered = [r for r in results if r.status == "covered"]
    adjacent = [r for r in results if r.status == "adjacent"]
    new = [r for r in results if r.status == "new"]
    lines = [
        "## NISRA Feed Drift Detection",
        "",
        "| Status | Count |",
        "|--------|-------|",
        f"| ✅ Covered | {len(covered)} |",
        f"| ⚠️ Adjacent | {len(adjacent)} |",
        f"| 🆕 New | {len(new)} |",
        "",
    ]
    if adjacent:
        lines += ["### ⚠️ Adjacent (possibly covered)", ""]
        for r in adjacent:
            lines.append(f"- **{r.title}** (score {r.score:.3f} → `{r.best_match}`)")
        lines.append("")
    if new:
        lines += ["### 🆕 Potentially new datasets", ""]
        for r in new:
            lines.append(f"- **[{r.title}]({r.link})** (score {r.score:.3f}, closest: `{r.best_match}`)")
        lines.append("")
    with open(path, "a") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--covered-threshold", type=float, default=COVERED_THRESHOLD,
                        help=f"Min similarity to classify as covered (default: {COVERED_THRESHOLD})")
    parser.add_argument("--adjacent-threshold", type=float, default=ADJACENT_THRESHOLD,
                        help=f"Min similarity to classify as adjacent (default: {ADJACENT_THRESHOLD})")
    parser.add_argument("--verbose", action="store_true", help="Show covered entries too")
    parser.add_argument("--json-out", type=pathlib.Path, help="Write full results JSON")
    parser.add_argument("--github-summary", action="store_true")
    args = parser.parse_args()

    corpus = extract_corpus(REPO_ROOT / "src" / "bolster" / "data_sources")
    print(f"Corpus: {len(corpus)} modules", file=sys.stderr)

    entries = fetch_feed(limit=args.limit)
    print(f"Feed: {len(entries)} entries", file=sys.stderr)

    results = classify_feed(
        entries, corpus,
        covered_threshold=args.covered_threshold,
        adjacent_threshold=args.adjacent_threshold,
    )

    print_results(results, verbose=args.verbose)

    if args.json_out:
        args.json_out.write_text(json.dumps(
            [{"title": r.title, "link": r.link, "published": r.published,
              "status": r.status, "best_match": r.best_match,
              "best_match_path": r.best_match_path, "score": r.score}
             for r in results],
            indent=2,
        ))

    if args.github_summary:
        write_github_summary(results)

    return 2 if any(r.status == "new" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
