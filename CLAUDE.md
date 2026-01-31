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

### MCP Servers

If available, prefer:

- `mcp__tavily__*` for web search over built-in WebSearch
- `mcp__memory__*` for persistent context across sessions
