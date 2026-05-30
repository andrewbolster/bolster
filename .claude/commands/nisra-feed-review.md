## description: Review the NISRA publications feed, enrich unevaluated data-source-candidate issues with data-explore evaluations, and surface net-new candidates not yet tracked.

## User Input

```text
$ARGUMENTS
```

Optional arguments:
- `--enrich-only` — skip feed scan, only enrich existing unevaluated issues
- `--scan-only` — skip enrichment, only report net-new candidates (no GitHub writes)
- `--check-urls` — also spot-check existing module source URLs for staleness

## Goal

Run the full NISRA feed review workflow:
1. Identify which open `data-source-candidate` issues lack a data-explore evaluation comment
2. Scan recent NISRA publications for net-new candidates not yet tracked in issues
3. Run data-explore evaluations for unevaluated issues and net-new candidates
4. **Present all findings to the user for approval before writing anything to GitHub**
5. Post approved evaluation comments and create approved new issues

## Operating Constraints

- **Never post comments or create issues without explicit user approval**
- Do NOT write production code or create files in `src/`
- Disposable scripts in `/tmp/` only for data validation
- External HTTP will likely return 403 — use `WebSearch` and `WebFetch` as fallback for feed content and URL validation
- Follow the data-explore output format defined in `AGENTS.md`

---

## Execution Steps

### Step 1 — Gather current state (parallel)

Run these simultaneously:

**1a. List open data-source-candidate issues**

Use `mcp__github__list_issues` with:
- `owner`: `andrewbolster`
- `repo`: `bolster`
- `state`: `OPEN`
- `labels`: `["data-source-candidate"]`
- `perPage`: 100

For each issue, note: issue number, title, creation date, comment count.
Issues with `comments: 0` are **unevaluated** — these are enrichment targets.

**1b. List implemented modules**

```bash
find src/bolster/data_sources -name "*.py" | grep -v __pycache__ | grep -v __init__ | sort
```

Extract the module names. This is your "already implemented" set.

**1c. Try the NISRA feed CLI**

```bash
uv run bolster nisra feed --limit 50
```

If this returns 403 or fails, fall back to:
- `WebFetch` on `https://www.nisra.gov.uk/published-releases`
- `WebSearch` for "NISRA new statistics site:gov.uk OR site:nisra.gov.uk" filtered to the past 2 weeks

---

### Step 2 — Identify unevaluated issues

From Step 1a: collect all issues with `comments: 0`.
These exist because the automated `nisra-feed-drift.yml` workflow creates thin issues without evaluations.

If running `--enrich-only`: skip to Step 4.

---

### Step 3 — Identify net-new candidates

From the feed/web results in Step 1c, compare each publication against:
- Implemented modules (Step 1b)
- **All** open data-source-candidate issues (Step 1a, regardless of comment count)

A publication is **net-new** only if it matches neither list.

Apply these filters to avoid noise:
- Skip quarterly/annual updates of already-implemented series (e.g. "Monthly Deaths April 2026" when `deaths.py` exists)
- Skip one-off or historical reports unlikely to have regular updates
- Skip PDF-only publications with no machine-readable data
- Skip if a very similar issue already exists (check titles for keyword overlap)

If running `--scan-only`: output the net-new list and stop before Step 4.

---

### Step 4 — Run data-explore evaluations

For each item in (unevaluated issues ∪ net-new candidates), research the dataset using `WebSearch` and `WebFetch`. Produce a structured evaluation following the AGENTS.md data-explore output format:

```markdown
## Data Source Evaluation: [Name]

**Source**: [URL]
**Format**: [Excel/CSV/ODS/PDF/other]
**Accessibility**: [X/5 with rationale — note Cloudflare/403 risks]
**Update frequency**: [quarterly/annual/monthly]
**Historical coverage**: [how far back]
**Publisher**: [organisation]

### What the data contains
[2-3 sentences on key metrics and breakdowns]

### Schema (expected columns)
[Table or list of expected column names/dimensions]

### Integration pattern
[Closest existing module pattern; proposed file path; scraping approach]

### Cross-dataset correlation opportunities
[3 specific ideas linking to existing modules with concrete join keys]

### Derived insights possible
[3 specific analysis ideas — ratios, trends, comparisons]

### Complexity assessment
[Low/Medium/High with rationale — flag Cloudflare blocking explicitly]

**Recommendation**: RECOMMENDED / MAYBE / NOT RECOMMENDED
**Next steps for data-build agent**: [numbered, specific instructions]
```

---

### Step 5 — Present findings to user

Output a summary table before doing anything on GitHub:

```
## NISRA Feed Review — Proposed Actions

### Unevaluated issues to enrich (N)
| Issue | Title | Action |
|-------|-------|--------|
| #NNNN | ... | Post evaluation comment |

### Net-new candidates (N)
| Title | Published | Recommendation | Action |
|-------|-----------|----------------|--------|
| ... | ... | RECOMMENDED | Create issue + post evaluation |

### Skipped / already covered (N)
| Title | Reason |
|-------|--------|
```

Then ask: **"Shall I proceed with all of the above, or select specific items?"**

Do not proceed until the user confirms.

---

### Step 6 — Execute approved actions (parallel where possible)

For each approved item:

**Enriching an existing issue** — post the evaluation as a comment using `mcp__github__add_issue_comment`.

**Creating a new issue** — create with `mcp__github__issue_write` using:
- `labels`: `["enhancement", "data-source-candidate"]`
- Body: the standard data-source-candidate template (see existing issues #1861–#1865 for format) with the evaluation embedded
- Title: `data-source-candidate: [dataset name]`
- Then post the full evaluation as a follow-up comment for consistency

---

### Step 7 — Optional: spot-check module URLs (if `--check-urls`)

For each implemented module, extract its primary source URL (grep for `_URL\s*=` or `_BASE_URL\s*=`) and attempt `WebFetch`. Report:
- **BROKEN**: DNS fails or 404
- **REDIRECTED**: 301/302 to a different path (flag for update)
- **OK**: 200

Only flag if the redirect target differs meaningfully from the hardcoded URL (e.g. `/economic-output-statistics/` → `/economic-output/` is worth flagging; a CDN redirect is not).

---

## Output format

At completion, emit a brief summary:
- N issues enriched
- N new issues created
- N candidates skipped
- N URL issues found (if `--check-urls`)

Suggest running `uv run bolster nisra feed --limit 20` to verify the CLI feed is working, as a smoke test.
