# Claude Code Configuration

See @AGENTS.md for project structure, standards, and agent workflows.

## Claude-Specific Settings

### Subagents

This project defines three specialized subagents in `.claude/agents/`:

| Agent | Model | Purpose |
|-------|-------|---------|
| `data-explore` | sonnet | Discover and evaluate new data sources |
| `data-build` | opus | Build production modules with tests |
| `data-review` | sonnet | Review PRs for consistency |

Invoke with: "Use the data-explore agent to..."

### Preferred Tools

- Use `uv run` for all Python commands (not `python` or `pip`)
- Use `gh` CLI for GitHub operations
- Run `pre-commit` before committing

### Git Workflow — IMPORTANT

**Never commit directly to `main`.** All changes must go through a PR:

1. `git checkout -b fix/<name>` (or `feat/<name>`)
1. Commit changes on the branch
1. `gh pr create` — include summary and any relevant issue references
1. Wait for CI to pass before merging

This applies even to small fixes. The only exception is post-merge follow-up commits already agreed with the user in the same session (e.g. bumping artifact action versions after a workflow is merged).

### MCP Servers

If available, prefer:

- `mcp__tavily__*` for web search over built-in WebSearch
- `mcp__memory__*` for persistent context across sessions
