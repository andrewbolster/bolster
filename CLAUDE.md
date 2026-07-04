# Claude Code Configuration

See @AGENTS.md for project structure, standards, tool preferences, git workflow, and agent definitions.

## Claude-Specific Settings

### Subagents

Three specialized subagents are defined in `.claude/agents/`:

- `data-explore` — discover and evaluate new data sources
- `data-build` — build production modules with tests and CLI
- `data-review` — review code for consistency against project standards

Invoke with: "Use the data-explore agent to..."
