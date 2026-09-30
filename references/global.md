# Global mode

Sets up the *person* across projects: `~/.claude/CLAUDE.md`, user-level settings and skills, and where each piece of knowledge lives. Project mode reads one codebase closely. Global mode reads many projects shallowly and only says what a cross-project view can see.

## Contents
- [Consent](#consent)
- [Run](#run)
- [What to look for](#what-to-look-for)
- [Project edits](#project-edits)
- [Cloud sessions](#cloud-sessions)
- [Report](#report)

## Consent

Global mode reads sessions from many projects and spawns more agents, so it always asks first, **per project**:
1. `python "${CLAUDE_SKILL_DIR}/scripts/sessions.py" --list-projects` lists paths, session counts, and last-active dates. It reads no prompts.
2. Show the list and ask which projects to include (all, some, or none). Nothing else runs until they answer.
3. Say roughly how many agents this will take (one per 3-4 projects), and wait for the go-ahead.

## Run

- **Your own read:** `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.claude/rules/`, `~/.claude/skills/`, `~/.claude/agents/`, and the account skills in your own context (they aren't on disk).
- **Per chosen project, in parallel `Explore` subagents** (3-4 projects each). Each one runs `sessions.py --project <path>` and `inventory.py --project <path> --no-user`, reads the project's CLAUDE.md files and `.claude/setup-suggestions.md` if present, and returns: always-loaded rules (verbatim, short), corrections and repeated tasks from sessions, approved commands, MCP servers configured vs used, and the open **Global** items from the suggestions file. It does **not** do a full codebase analysis.

## What to look for

| Finding | Evidence | Change |
|---|---|---|
| **Promote** | The same rule, correction, or suggestions-file Global item in 3+ projects | Move it to `~/.claude/CLAUDE.md`; remove the project copies |
| **Demote** | A global rule that only ever comes up in one project | Move it into that project |
| **Contradiction** | Global says X, a project says not-X | Ask which wins; a project override is fine if deliberate |
| **Global allowlist** | The same read-only commands approved in most projects | User-level `permissions.allow` (never broad `Bash(*)`) |
| **User-level skill** | The same multi-step workflow across projects | A skill in `~/.claude/skills/`; one-project workflows stay there |
| **MCP by usage** | A tool used constantly via Bash (`gh`, `psql`), or servers configured but unused | Suggest the server, or disable it where it's unused (not uninstall everywhere) |
| **Local-only preference** | A preference that lives only in `~/.claude` | Say it never reaches cloud sessions; offer an account skill or the repo |

The line test still applies: global CLAUDE.md is loaded in every session, so keep it under ~30 lines of things that change Claude's behavior everywhere.

## Project edits

Suggest a project edit only for what the cross-project view uniquely sees: duplicates, contradictions, and misplaced rules. For anything deeper, say "run `/claude-setup audit` in that repo."

After approval, also sync the suggestions files. In every chosen project's `.claude/setup-suggestions.md`, mark Global items you just applied, e.g. `python learn.py resolve <id> --status applied --cwd <project>`, so no repo keeps showing a suggestion that's already done. Items get stable IDs, but the same idea can have different IDs in different repos: match by meaning, not just ID.

## Cloud sessions

A cloud container has: account skills (synced), connectors, and what's committed in the repo. It does **not** have the local `~/.claude/CLAUDE.md`, auto-memory, or past transcripts (only the current session's). In the cloud, say that global mode has little to read, and offer what still works: the repo's own setup and its suggestions file. Global items approved in the cloud stay pending until a local session.

## Report

Lead with the top 3 changes. Then: Promote / Demote / Contradictions / Allowlist / Skills / MCP / Local-only. Every item names the projects it came from. Apply only what's approved, with the same backup rules as fix mode.
