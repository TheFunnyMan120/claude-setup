# Claude Setup

A Claude Code plugin that sets up, audits, and improves your Claude Code setup.

It learns how your project actually works before giving advice. It reads the codebase (with parallel subagents on big repos) and, if you allow it, your past Claude sessions in that project. Then it either:

- **Builds a setup from scratch**: a lean CLAUDE.md, safe `settings.json`, `.gitignore` entries, and the hooks, skills, and agents your work calls for.
- **Audits an existing setup**: a score out of 100 with concrete `file:line` fixes, plus the hooks, skills, and agents worth adding. It applies only the changes you approve.

## Install

```bash
claude plugin marketplace add TheFunnyMan120/claude-setup
claude plugin install claude-setup@claude-setup
```

To try a local copy:
```bash
claude plugin marketplace add ./claude-setup
claude plugin install claude-setup@claude-setup
```

Requires Python 3 on your PATH, as `python`, `python3`, or `py`.

Or download the zip from the [latest release](https://github.com/TheFunnyMan120/claude-setup/releases/latest), unzip it, and either run `claude plugin marketplace add <unzipped folder>` or copy the folder to `~/.claude/skills/claude-setup` to use it as a plain skill.

## Use

Run it inside any project:

| Command | What it does |
|---|---|
| `/claude-setup` | Picks the mode itself: init if there's no setup, otherwise audit |
| `/claude-setup audit` | Scored report. Changes nothing. |
| `/claude-setup fix` | Audit, then apply the fixes you approve (backs up first) |
| `/claude-setup init` | Build a setup from scratch |
| `/claude-setup explain <question>` | e.g. "where should our deploy runbook live?" |

Plain requests work too: "is my CLAUDE.md any good?", "Claude keeps ignoring my rules", "set up Claude Code for this repo", "what hooks should I add?"

## What it checks

- **CLAUDE.md quality:** size, signal density, stale commands, contradictions across user/project/local files, and content that belongs in rules or skills.
- **Context economy:** what loads every session, path-scoped rules, imports, and the auto-memory index.
- **Permissions and secrets:** `Bash(*)`, missing `.env` read denies, tracked `.env` files, literal secrets in config, and ignored or dead rules.
- **Hook safety:** unquoted paths, relative scripts that fail open, network calls, and slow hooks on every prompt.
- **Skills and agents:** descriptions that won't trigger (or overtrigger), size limits, least-privilege tools, and duplicates.
- **MCP servers:** unpinned packages, plain http, and secrets that aren't expanded from env.

## Privacy

Everything runs locally. Session scanning reads only that project's transcripts under `~/.claude/projects/`, only after you say yes. It redacts secret-shaped strings and reports aggregate patterns. Secret values are never printed.

## Testing triggers

`evals/trigger-prompts.md` lists prompts that should and shouldn't activate the skill. `python evals/run_trigger_eval.py <empty-dir>` runs them through `claude -p` in plan mode, so nothing is written. It needs a logged-in `claude` CLI.

## License

MIT
