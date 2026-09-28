# Claude Code

Project guidance for all coding agents lives in @AGENTS.md — structure, commands, standards, shared utilities, release rules and the data-source agent workflows. Read it first; this file only covers what is specific to Claude Code.

## `.claude/` folder

- `agents/` — subagents for the data-source lifecycle. Invoke with "Use the data-explore agent to…":
  - `data-explore` — evaluate `data-source-candidate` issues
  - `data-build` — build a module from a RECOMMENDED issue
  - `data-review` — review open data-source PRs
  - `data-maintenance` — weekly review of merged PRs for doc gaps and shared-utility candidates
- `commands/nisra-feed-review.md` — `/nisra-feed-review`: scan the NISRA RSS feed and open `data-source-candidate` issues
- `constitution.md` — conventions distilled from the existing modules

The agent definitions themselves are specified in AGENTS.md; the files in `.claude/agents/` are the Claude Code wrappers.
