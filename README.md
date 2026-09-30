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
| `/claude-setup global` | Your own setup across projects: rules to promote to `~/.claude/CLAUDE.md` or push down into one repo, contradictions, a global allowlist. Asks per project first. |
| `/claude-setup review` | Go through pending suggestions from the learning hook |
| `/claude-setup learn on` / `learn off` | Turn the optional learning hook on or off |
| `/claude-setup explain <question>` | e.g. "where should our deploy runbook live?" |

Plain requests work too: "is my CLAUDE.md any good?", "Claude keeps ignoring my rules", "set up Claude Code for this repo", "what hooks should I add?"

## What it checks

- **CLAUDE.md quality:** size, signal density, stale commands, contradictions across user/project/local files, and content that belongs in rules or skills.
- **Context economy:** what loads every session, path-scoped rules, imports, and the auto-memory index.
- **Permissions and secrets:** `Bash(*)`, missing `.env` read denies, tracked `.env` files, literal secrets in config, and ignored or dead rules.
- **Hook safety:** unquoted paths, relative scripts that fail open, network calls, and slow hooks on every prompt.
- **Skills and agents:** descriptions that won't trigger (or overtrigger), size limits, least-privilege tools, and duplicates.
- **MCP servers:** unpinned packages, plain http, and secrets that aren't expanded from env.

## Learning hook (optional, off by default)

If you turn it on, it watches for corrections you give Claude ("don't do X", "from now on…", interrupting it, rejecting a tool call) and turns them into suggestions for your setup. It never changes anything itself. Suggestions collect in `.claude/setup-suggestions.md`, and a new session tells you how many are pending, never what they are. Run `/claude-setup review` to approve, edit, or reject them. Rejected ones don't come back.

- A cheap keyword check runs first. Sonnet only runs when that check finds something new, usually $0.01-0.03 per run, capped at 10 runs a day, on your plan's usage.
- **On your computer** it runs once at session end, in the background. The file is kept out of git.
- **In cloud sessions** it runs at the end of a turn when there's something new, and the file is committed so it survives the container. On a shared repo, teammates can see it, so the skill warns you before turning it on there.
- It runs Sonnet only. There's no cheaper-model option.
- Each repo's suggestions file keeps itself current: anything you've already put in place is cleared automatically, and a git merge conflict in the file (two cloud branches) is merged by the hook itself. If you update the plugin, `/claude-setup` audit tells you when your installed hook copy is out of date.

## Privacy

Everything runs locally. Session scanning reads only that project's transcripts under `~/.claude/projects/`, only after you say yes. Global mode asks separately for each project. The learning hook only reads what you typed, and only once you've turned it on. It redacts secret-shaped strings and reports aggregate patterns. Secret values are never printed.

## Testing triggers

`evals/trigger-prompts.md` lists prompts that should and shouldn't activate the skill. `python evals/run_trigger_eval.py <empty-dir>` runs them through `claude -p` in plan mode, so nothing is written. It needs a logged-in `claude` CLI.

## License

MIT
