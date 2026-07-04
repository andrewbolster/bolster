# Claude Code Configuration

See @AGENTS.md for project structure, standards, tool preferences, git workflow, and agent definitions.

## Claude-Specific Settings

### Subagents

Three specialized subagents are defined in `.claude/agents/`:

- `data-explore` — discover and evaluate new data sources; posts evaluations to `data-source-candidate` issues
- `data-build` — build production modules with tests and CLI from a RECOMMENDED issue
- `data-review` — review open data-source PRs for consistency against project standards
- `data-maintenance` — monthly review of merged PRs for doc gaps and shared utility candidates

Invoke with: "Use the data-explore agent to..."
